"""Table dialog for editing a day's records. Knows nothing about files.

The day is switchable (combobox of recent days); switching reloads the table.
``fetch`` returns the day's intervals, ``on_save`` persists them. A new row
can be added (prefilled to the largest gap), deleting offers gap vs. extend.
"""

import tkinter as tk
from collections.abc import Callable
from datetime import date, datetime
from tkinter import messagebox, ttk

from timetrack.editing import (
    EditedInterval,
    EditError,
    format_time,
    join_notes,
    parse_time,
    split_notes,
)

FONT = ("Segoe UI", 10)
HEADERS = ("Začátek", "Konec", "Aktivita", "Poznámky", "")


class EditDialog:
    def __init__(
        self,
        root: tk.Tk,
        day: date,
        fetch: Callable[[date], list[EditedInterval]],
        day_choices: Callable[[], list[tuple[date, str]]],
        on_save: Callable[[date, list[EditedInterval]], str | None],
    ):
        self.fetch = fetch
        self.on_save = on_save
        self.day = day
        self.tz = None
        self.rows: list[dict] = []
        self._grid_row = 1

        self.window = tk.Toplevel(root)
        self.window.resizable(False, False)
        self.window.attributes("-topmost", True)

        header = tk.Frame(self.window)
        header.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(header, text="Den:", font=FONT).pack(side="left", padx=(0, 6))
        self.day_var = tk.StringVar(self.window)
        self.combo = ttk.Combobox(header, textvariable=self.day_var, state="readonly", width=44)
        self.combo.pack(side="left")
        self.combo.bind("<<ComboboxSelected>>", self._day_selected)
        choices = day_choices()
        self._label_to_day = {label: d for d, label in choices}
        self._day_to_label = {d: label for d, label in choices}
        self.combo.config(values=[label for _d, label in choices])

        self.table = tk.Frame(self.window)
        self.table.pack(fill="x", padx=12, pady=(0, 4))

        controls = tk.Frame(self.window)
        controls.pack(fill="x", padx=12)
        tk.Button(controls, text="+ Přidat řádek", command=self._add_row).pack(side="left")

        self.hint = tk.Label(
            self.window,
            text="Časy H:MM[:SS] · prázdný konec = běžící aktivita · poznámky odděluj ' // '",
            anchor="w", font=(FONT[0], 8), fg="#888888",
        )
        self.hint.pack(fill="x", padx=12, pady=(4, 0))

        self.error = tk.Label(self.window, anchor="w", font=(FONT[0], 9), fg="#bb2222")
        self.error.pack(fill="x", padx=12, pady=(2, 0))

        buttons = tk.Frame(self.window)
        buttons.pack(fill="x", padx=12, pady=(4, 10))
        tk.Button(buttons, text="Uložit", width=12, command=self._save).pack(side="right")
        tk.Button(buttons, text="Zavřít", width=12, command=self.window.destroy).pack(
            side="right", padx=(0, 8)
        )

        self.window.bind("<Escape>", lambda _e: self.window.destroy())
        self._show_day(day)
        self._center()

    # --- day switching -----------------------------------------------------

    def _show_day(self, day: date) -> None:
        self.day = day
        self.window.title(f"Upravit záznamy — {day.isoformat()}")
        self.day_var.set(self._day_to_label.get(day, day.isoformat()))
        intervals = self.fetch(day)
        self.tz = intervals[0].start.tzinfo if intervals else datetime.now().astimezone().tzinfo
        self._build_table(intervals)
        self.error.config(text="")

    def _day_selected(self, _event) -> None:
        day = self._label_to_day.get(self.day_var.get())
        if day and day != self.day:
            self._show_day(day)

    def _build_table(self, intervals: list[EditedInterval]) -> None:
        for widget in self.table.winfo_children():
            widget.destroy()
        self.rows = []
        self._grid_row = 1
        for column, head in enumerate(HEADERS):
            tk.Label(self.table, text=head, font=(FONT[0], 9, "bold"), anchor="w").grid(
                row=0, column=column, sticky="w", padx=(0, 8)
            )
        for interval in intervals:
            self._make_row(
                interval,
                format_time(interval.start),
                "" if interval.end is None else format_time(interval.end),
                interval.text,
                join_notes(interval.notes),
            )

    # --- rows --------------------------------------------------------------

    def _make_row(self, interval, start, end, text, notes) -> dict:
        row = {
            "interval": interval,  # None = nově přidaný
            "deleted": False,
            "start": tk.StringVar(self.window, start),
            "end": tk.StringVar(self.window, end),
            "text": tk.StringVar(self.window, text),
            "notes": tk.StringVar(self.window, notes),
        }
        widgets = [
            tk.Entry(self.table, textvariable=row["start"], width=9, font=FONT),
            tk.Entry(self.table, textvariable=row["end"], width=9, font=FONT),
            tk.Entry(self.table, textvariable=row["text"], width=42, font=FONT),
            tk.Entry(self.table, textvariable=row["notes"], width=30, font=FONT),
            tk.Button(self.table, text="✕", width=3, command=lambda r=row: self._delete(r)),
        ]
        for column, widget in enumerate(widgets):
            widget.grid(row=self._grid_row, column=column, sticky="w", padx=(0, 8), pady=1)
        row["widgets"] = widgets
        self._grid_row += 1
        self.rows.append(row)
        return row

    def _add_row(self) -> None:
        start, end = self._suggest_gap()
        self._make_row(None, start, end, "", "")
        self._resize()

    def _suggest_gap(self) -> tuple[str, str]:
        """Largest gap between existing rows as (start, end); else after the last."""
        spans = []
        for row in self.rows:
            if row["deleted"]:
                continue
            try:
                s = parse_time(row["start"].get(), self.day, self.tz)
                e = parse_time(row["end"].get(), self.day, self.tz) if row["end"].get().strip() else None
            except EditError:
                continue
            spans.append((s, e))
        spans.sort(key=lambda p: p[0])
        best = None
        for (_s1, e1), (s2, _e2) in zip(spans, spans[1:]):
            if e1 and s2 > e1 and (best is None or (s2 - e1) > (best[1] - best[0])):
                best = (e1, s2)
        if best:
            return format_time(best[0]), format_time(best[1])
        if spans and spans[-1][1]:
            return format_time(spans[-1][1]), ""  # za poslední aktivitou
        return "", ""

    def _delete(self, row: dict) -> None:
        previous = None
        for candidate in self.rows:
            if candidate is row:
                break
            if not candidate["deleted"]:
                previous = candidate
        if previous is None:
            if not messagebox.askyesno(
                "TimeTrack", "Smazat aktivitu? Po jejím čase zůstane mezera.", parent=self.window
            ):
                return
        else:
            answer = messagebox.askyesnocancel(
                "TimeTrack",
                "Natáhnout předchozí aktivitu přes uvolněný čas?\n"
                "Ano = natáhnout, Ne = nechat mezeru.",
                parent=self.window,
            )
            if answer is None:
                return
            if answer:
                previous["end"].set(row["end"].get())
        row["deleted"] = True
        for widget in row["widgets"]:
            widget.grid_remove()
        self._resize()

    # --- save --------------------------------------------------------------

    def _save(self) -> None:
        try:
            intervals = [self._parse_row(row) for row in self.rows if not row["deleted"]]
        except EditError as error:
            self.error.config(text=str(error))
            return
        error = self.on_save(self.day, intervals)
        if error:
            self.error.config(text=error)
            return
        self.window.destroy()

    def _parse_row(self, row: dict) -> EditedInterval:
        source = row["interval"]
        tz = source.start.tzinfo if source else self.tz
        start = parse_time(row["start"].get(), self.day, tz)
        end_text = row["end"].get().strip()
        end = parse_time(end_text, self.day, tz) if end_text else None
        if source and row["notes"].get().strip() == join_notes(source.notes).strip():
            notes = list(source.notes)  # nezměněno — zachovat původní časy poznámek
        else:
            notes = [(start, text) for text in split_notes(row["notes"].get())]
        return EditedInterval(
            start=start,
            end=end,
            text=row["text"].get().strip(),
            notes=notes,
            original_start=source.original_start if source else None,
        )

    def _resize(self) -> None:
        self.window.update_idletasks()
        x, y = self.window.winfo_x(), self.window.winfo_y()
        self.window.geometry(f"+{x}+{y}")

    def _center(self) -> None:
        self.window.update_idletasks()
        width = self.window.winfo_reqwidth()
        x = (self.window.winfo_screenwidth() - width) // 2
        y = self.window.winfo_screenheight() // 6
        self.window.geometry(f"+{x}+{y}")
        self.window.lift()
        self.window.focus_force()
