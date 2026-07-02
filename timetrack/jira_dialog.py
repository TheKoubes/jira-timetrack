"""Worklog manager dialog: pick a day, edit & send pending blocks, delete sent.

The dialog owns which day is displayed — a combobox of recent days shows
each day's send status, switching it reloads the table. ``fetch`` loads a
day's blocks and the ``on_send``/``on_delete`` callbacks receive the
displayed day. Edits made here (times, ticket, comment) shape only what
goes to Jira — the local timeline is edited elsewhere (the record editor).
"""

import tkinter as tk
from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from tkinter import messagebox, ttk

from timetrack.editing import EditError, format_time, parse_time
from timetrack.jira import WorklogItem
from timetrack.summary import format_duration

FONT = ("Segoe UI", 10)
NAME_MAX = 42  # zkrácení názvu ticketu, ať okno neroste donekonečna


def _short(text: str) -> str:
    return text if len(text) <= NAME_MAX else text[: NAME_MAX - 1] + "…"


class JiraDialog:
    def __init__(
        self,
        root: tk.Tk,
        day: date,
        fetch: Callable[[date], tuple[list[WorklogItem], list[str]]],
        day_choices: Callable[[], list[tuple[date, str]]],
        on_send: Callable[[date, list[WorklogItem]], None],
        on_delete: Callable[[date, WorklogItem], None],
        on_meta: Callable[[list[str]], None] | None = None,
        ticket_names: dict[str, str] | None = None,
    ):
        self.day = day
        self.fetch = fetch
        self.day_choices = day_choices
        self.on_send = on_send
        self.on_delete = on_delete
        self.on_meta = on_meta  # async: account + název, výsledek přes show_meta()
        self.ticket_names = ticket_names or {}  # cache ticket → název, pro okamžité zobrazení

        self.window = tk.Toplevel(root)
        self.window.resizable(False, False)
        self.window.attributes("-topmost", True)

        header = tk.Frame(self.window)
        header.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(header, text="Den:", font=FONT).pack(side="left", padx=(0, 6))
        self.day_var = tk.StringVar(self.window)
        self.combo = ttk.Combobox(header, textvariable=self.day_var, state="readonly", width=46)
        self.combo.pack(side="left")
        self.combo.bind("<<ComboboxSelected>>", self._day_selected)

        self.table = tk.Frame(self.window)
        self.table.pack(fill="x", padx=12, pady=(0, 4))

        self.info = tk.Label(self.window, anchor="w", font=(FONT[0], 8), fg="#888888")
        self.info.pack(fill="x", padx=12)

        hint = tk.Label(
            self.window,
            text="Pole s * jsou povinná · úpravy ovlivní jen Jiru, ne lokální záznamy"
            " · komentář se pamatuje a po smazání z Jiry se předvyplní pro příště.",
            anchor="w",
            font=(FONT[0], 8),
            fg="#888888",
        )
        hint.pack(fill="x", padx=12)

        self.error = tk.Label(self.window, anchor="w", font=(FONT[0], 9), fg="#bb2222")
        self.error.pack(fill="x", padx=12, pady=(2, 0))

        self.total = tk.Label(self.window, anchor="w", font=(FONT[0], 10, "bold"))
        self.total.pack(fill="x", padx=12, pady=(4, 4))

        buttons = tk.Frame(self.window)
        buttons.pack(fill="x", padx=12, pady=(0, 10))
        tk.Button(buttons, text="Odeslat", width=12, command=self._send).pack(side="right")
        tk.Button(buttons, text="Zavřít", width=12, command=self.window.destroy).pack(
            side="right", padx=(0, 8)
        )

        self.window.bind("<Escape>", lambda _e: self.window.destroy())
        self.rows: list[dict] = []
        self._day_by_label: dict[str, date] = {}
        self._show_day(day)
        self._center()

    def refresh(self) -> None:
        """Reload the displayed day (after a deletion changed what is sent)."""
        self._show_day(self.day)

    def delete_failed(self, message: str) -> None:
        self.error.config(text=message)
        for row in self.rows:
            if row.get("button"):
                row["button"].config(state="normal", text="Smazat z Jiry")

    def show_meta(self, meta: dict[str, dict]) -> None:
        """Fill in asynchronously fetched account + název (ticket → {account, name})."""
        for row in self.rows:
            ticket = row["item"].ticket
            if ticket not in meta:
                continue
            account_label = row.get("account_label")
            if account_label and account_label.winfo_exists():
                account_label.config(text=meta[ticket].get("account") or "—")
            name_label = row.get("name_label")
            if name_label and name_label.winfo_exists():
                name_label.config(text=_short(meta[ticket].get("name", "")))
        # Doplněné názvy/accounty okno rozšířily až po vycentrování — srovnat
        # pozici, ale bez kradení fokusu (uživatel může zrovna psát komentář).
        self._center(focus=False)

    def _show_day(self, day: date) -> None:
        self.day = day
        self.window.title(f"Odeslat do Jiry — {day.isoformat()}")
        choices = self.day_choices()
        self._day_by_label = {label: d for d, label in choices}
        label_by_day = {d: label for d, label in choices}
        self.combo.config(values=[label for _d, label in choices])
        self.day_var.set(label_by_day.get(day, day.isoformat()))
        items, collapsed = self.fetch(day)
        self._build(items)
        self.info.config(
            text=f"Po zaokrouhlení spadly na 0: {', '.join(collapsed)}" if collapsed else ""
        )
        self.error.config(text="")
        if self.on_meta and items:
            self.on_meta([item.ticket for item in items])
        self._center(focus=False)  # přepnutí dne mění šířku tabulky

    def _day_selected(self, _event) -> None:
        day = self._day_by_label.get(self.day_var.get())
        if day and day != self.day:
            self._show_day(day)

    def _build(self, items: list[WorklogItem]) -> None:
        for widget in self.table.winfo_children():
            widget.destroy()
        self.rows = []
        if not items:
            tk.Label(
                self.table,
                text="Žádné worklogy pro tento den.",
                font=FONT,
                fg="#888888",
            ).grid(row=0, column=0, sticky="w", pady=6)
            self._update_total()
            return
        headers = ("", "Ticket*", "Název", "Account", "Od*", "Do*", "Komentář*", "")
        for column, header in enumerate(headers):
            tk.Label(self.table, text=header, font=(FONT[0], 9, "bold"), anchor="w").grid(
                row=0, column=column, sticky="w", padx=(0, 8)
            )

        pending = "…" if self.on_meta else ""
        for index, item in enumerate(items, start=1):
            end = item.started + timedelta(seconds=item.seconds)
            comment = item.comment if item.comment is not None else item.default_comment
            account_label = tk.Label(self.table, text=pending, fg="#666666", font=FONT)
            name_label = tk.Label(
                self.table, text=_short(self.ticket_names.get(item.ticket, "")), fg="#666666", font=FONT
            )
            if item.is_sent:
                row = {
                    "item": item, "sent": True,
                    "account_label": account_label, "name_label": name_label,
                }
                widgets = [
                    tk.Label(self.table, text="✓ v Jiře", fg="#227722", font=FONT),
                    tk.Label(self.table, text=item.ticket, font=FONT),
                    name_label,
                    account_label,
                    tk.Label(self.table, text=format_time(item.started), font=FONT),
                    tk.Label(self.table, text=format_time(end), font=FONT),
                    tk.Label(self.table, text=_short(comment), font=FONT, anchor="w"),
                ]
                row["button"] = tk.Button(
                    self.table, text="Smazat z Jiry", command=lambda r=row: self._delete(r)
                )
                widgets.append(row["button"])
            else:
                row = {
                    "item": item,
                    "sent": False,
                    "account_label": account_label,
                    "name_label": name_label,
                    "checked": tk.BooleanVar(self.window, value=True),
                    "ticket": tk.StringVar(self.window, item.ticket),
                    "od": tk.StringVar(self.window, format_time(item.started)),
                    "do": tk.StringVar(self.window, format_time(end)),
                    "comment": tk.StringVar(self.window, comment),
                }
                widgets = [
                    tk.Checkbutton(
                        self.table, variable=row["checked"], command=self._update_total
                    ),
                    tk.Entry(self.table, textvariable=row["ticket"], width=22, font=FONT),
                    name_label,
                    account_label,
                    tk.Entry(self.table, textvariable=row["od"], width=8, font=FONT),
                    tk.Entry(self.table, textvariable=row["do"], width=8, font=FONT),
                    tk.Entry(self.table, textvariable=row["comment"], width=50, font=FONT),
                    tk.Label(self.table, text=""),
                ]
            for column, widget in enumerate(widgets):
                widget.grid(row=index, column=column, sticky="w", padx=(0, 8), pady=1)
            self.rows.append(row)
        self._update_total()

    def _delete(self, row: dict) -> None:
        item = row["item"]
        if not messagebox.askyesno(
            "TimeTrack",
            f"Smazat worklog {item.ticket} ({item.range_label}) z Jiry?",
            parent=self.window,
        ):
            return
        row["button"].config(state="disabled", text="maže se…")
        self.on_delete(self.day, item)

    def _send(self) -> None:
        try:
            edited = self._collect()
        except EditError as error:
            self.error.config(text=str(error))
            return
        if not edited:
            self.error.config(text="Není zaškrtnutý žádný výkaz k odeslání.")
            return
        self.window.destroy()
        self.on_send(self.day, edited)

    def _collect(self) -> list[WorklogItem]:
        edited: list[WorklogItem] = []
        ranges = []
        for row in self.rows:
            item = row["item"]
            if row["sent"]:
                ranges.append(
                    (item.started, item.started + timedelta(seconds=item.seconds), item.ticket)
                )
                continue
            if not row["checked"].get():
                continue
            ticket = row["ticket"].get().strip()
            if not ticket:
                raise EditError("Ticket nesmí být prázdný.")
            if not row["od"].get().strip() or not row["do"].get().strip():
                raise EditError(f"{ticket}: vyplň Od i Do.")
            tz = item.started.tzinfo
            start = parse_time(row["od"].get(), self.day, tz)
            end = parse_time(row["do"].get(), self.day, tz)
            if end <= start:
                raise EditError(f"{ticket}: konec musí být po začátku.")
            comment = row["comment"].get().strip()
            if not comment:
                raise EditError(f"{ticket}: vyplň komentář.")
            edited.append(
                replace(
                    item,
                    ticket=ticket,
                    started=start,
                    seconds=int((end - start).total_seconds()),
                    comment=comment,
                )
            )
            ranges.append((start, end, ticket))
        ranges.sort(key=lambda r: r[0])
        for earlier, later in zip(ranges, ranges[1:]):
            if later[0] < earlier[1]:
                raise EditError(f"Výkazy {earlier[2]} a {later[2]} se překrývají.")
        return edited

    def _update_total(self) -> None:
        seconds = sum(
            row["item"].seconds
            for row in self.rows
            if not row["sent"] and row["checked"].get()
        )
        self.total.config(text=f"Celkem k odeslání: {format_duration(timedelta(seconds=seconds))}")

    def _center(self, focus: bool = True) -> None:
        self.window.update_idletasks()
        width = self.window.winfo_reqwidth()
        # max(0, …): okno širší než obrazovka nesmí utéct do záporného X —
        # tlačítka vpravo by na malém displeji zmizela mimo obraz.
        x = max(0, (self.window.winfo_screenwidth() - width) // 2)
        y = self.window.winfo_screenheight() // 5
        self.window.geometry(f"+{x}+{y}")
        if focus:
            self.window.lift()
            self.window.focus_force()
