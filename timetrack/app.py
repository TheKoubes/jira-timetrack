"""Wires the tray (hotkey + icon + menu), popup and storage together."""

import os
import queue
import threading
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import messagebox

from timetrack import (
    __version__,
    autostart,
    config,
    crypto,
    editing,
    jira,
    storage,
    summary,
    ticketcache,
)
from timetrack.core import build_intervals
from timetrack.edit_dialog import EditDialog
from timetrack.hotkey import parse_hotkey
from timetrack.jira_dialog import JiraDialog
from timetrack.popup import Popup
from timetrack.settings_dialog import SettingsDialog
from timetrack.summary import format_duration
from timetrack.tray import AutoStopFlags, TrayThread

STOP_WORDS = {"stop", "pauza"}
QUIT_WORDS = {"quit", "exit", "konec"}
SUMMARY_WORDS = {"?", "den"}
WEEK_WORDS = {"týden", "tyden", "week"}
JIRA_WORDS = {"jira"}
EDIT_WORDS = {"uprav", "upravit", "edit"}
SETTINGS_WORDS = {"nastaveni", "nastavení", "settings"}
NOTE_PREFIX = "pozn"
TICKET_PREFIX = "ticket"

SETTINGS_KEYS = [
    "hotkey", "rounding_minutes", "rounding_mode", "round_times",
    "auto_stop_on_lock", "auto_stop_on_suspend", "auto_stop_on_logoff",
    "jira_base_url", "jira_email", "jira_account_field", "data_dir",
]


def _flags_from(cfg: dict) -> AutoStopFlags:
    return AutoStopFlags(
        lock=cfg.get("auto_stop_on_lock", False),
        suspend=cfg.get("auto_stop_on_suspend", False),
        logoff=cfg.get("auto_stop_on_logoff", False),
    )

POLL_MS = 100


def parse_command(text: str) -> tuple[str, str]:
    """Map popup input to an (action, payload) pair."""
    word = text.lower()
    if word in QUIT_WORDS:
        return "quit", ""
    if word in STOP_WORDS:
        return "stop", ""
    if word in SUMMARY_WORDS:
        return "summary", ""
    if word in WEEK_WORDS:
        return "week", ""
    if word in JIRA_WORDS:
        return "jira", ""
    if word.startswith("jira "):
        return "jira", text[len("jira") :].strip()
    if word in EDIT_WORDS:
        return "edit", ""
    if word.startswith("uprav ") or word.startswith("edit "):
        return "edit", text.split(None, 1)[1].strip()
    if word in SETTINGS_WORDS:
        return "settings", ""
    if word == NOTE_PREFIX:
        return "note", ""
    if word.startswith(NOTE_PREFIX + " "):
        return "note", text[len(NOTE_PREFIX) :].strip()
    if word == TICKET_PREFIX:
        return "ticket", ""
    if word.startswith(TICKET_PREFIX + " "):
        return "ticket", text[len(TICKET_PREFIX) :].strip()
    return "start", text


def jira_day(payload: str) -> date:
    """Resolve the day argument of the ``jira`` command ('' = today)."""
    word = payload.strip().lower()
    if not word:
        return date.today()
    if word in ("vcera", "včera"):
        return date.today() - timedelta(days=1)
    return date.fromisoformat(word)


def stop_running_activity(cfg: dict) -> bool:
    """Append a ``stop`` only when an activity is currently running.

    Used by auto-stop (lock/suspend/logoff) — writing an unconditional stop
    would litter the day with spurious events. Returns whether it stopped.
    """
    intervals = build_intervals(storage.read_day_events(cfg, date.today()))
    if intervals and intervals[-1].is_running:
        storage.append_stop(cfg)
        return True
    return False


def run_app(cfg: dict) -> None:
    root = tk.Tk()
    root.withdraw()

    events: queue.Queue[tuple[str, str]] = queue.Queue()
    tray = TrayThread(
        cfg["hotkey"],
        on_action=lambda action: events.put((action, "")),
        on_error=lambda message: events.put(("error", message)),
        on_autostop=lambda: stop_running_activity(cfg),
        flags=AutoStopFlags(
            lock=cfg.get("auto_stop_on_lock", False),
            suspend=cfg.get("auto_stop_on_suspend", False),
            logoff=cfg.get("auto_stop_on_logoff", False),
        ),
    )

    def show_message(kind: str, text: str) -> None:
        # A modal box parented to the withdrawn root can open behind other
        # windows with no taskbar entry, looking like a frozen app. A
        # temporary topmost parent keeps it in front of everything.
        helper = tk.Toplevel(root)
        helper.withdraw()
        helper.attributes("-topmost", True)
        show = {"error": messagebox.showerror, "warn": messagebox.showwarning}.get(
            kind, messagebox.showinfo
        )
        try:
            show("TimeTrack", text, parent=helper)
        finally:
            helper.destroy()

    def execute(action: str, payload: str = "") -> None:
        if action == "quit":
            tray.stop()
            root.destroy()
        elif action == "stop":
            storage.append_stop(cfg)
        elif action == "note":
            if payload:
                storage.append_note(cfg, payload)
        elif action == "ticket":
            if payload:
                try:
                    storage.append_ticket(cfg, payload)
                except ValueError as error:
                    show_message("warn", str(error))
        elif action == "summary":
            os.startfile(summary.write_summary(cfg, date.today()))
        elif action == "week":
            os.startfile(summary.write_week_summary(cfg, date.today()))
        elif action == "jira":
            open_jira_dialog(payload)
        elif action == "edit":
            open_edit_dialog(payload)
        elif action == "settings":
            open_settings_dialog()
        elif action == "notify":
            show_message("info", payload)
        elif action == "warn":
            show_message("warn", payload)
        elif action == "call":
            payload()  # callable from a worker thread, run on the Tk thread
        elif action == "show":
            popup.show()
        elif action == "error":
            show_message("error", payload)
            root.destroy()
        else:  # "start"
            storage.append_start(cfg, payload)

    def open_settings_dialog() -> None:
        values = {key: cfg.get(key) for key in SETTINGS_KEYS}
        def token_present(path) -> bool:
            try:
                return bool(crypto.read_secret(path))
            except (OSError, ValueError):
                # Nedešifrovatelný token (přenos z jiného účtu) nesmí zablokovat
                # otevření Nastavení — právě tam se dá token uložit znovu.
                return True

        tokens_present = {
            "jira": token_present(jira.token_path()),
            "tempo": token_present(jira.tempo_token_path()),
        }

        def on_save(new_values: dict, tokens: dict, autostart_on: bool) -> str | None:
            try:
                parse_hotkey(new_values["hotkey"])
            except ValueError as error:
                return f"Neplatná zkratka: {error}"
            try:
                new_values["rounding_minutes"] = max(0, int(new_values["rounding_minutes"]))
            except (TypeError, ValueError):
                return "Zaokrouhlení musí být celé číslo (minuty)."
            config.update_config(new_values)
            cfg.update(new_values)
            for name, path in (("jira", jira.token_path()), ("tempo", jira.tempo_token_path())):
                if tokens.get(name) is not None:  # None = ponechat stávající
                    crypto.write_secret(path, tokens[name])
            try:
                autostart.set_enabled(autostart_on)
            except Exception as error:  # noqa: BLE001
                return f"Automatický start se nepodařilo nastavit: {error}"
            tray.apply_settings(cfg["hotkey"], _flags_from(cfg))
            return None

        def on_test(new_values: dict, tokens: dict) -> None:
            def worker() -> None:
                test_cfg = dict(cfg, **new_values)
                email = new_values.get("jira_email", "")
                jira_tok = tokens["jira"] if tokens.get("jira") else crypto.read_secret(jira.token_path())
                tempo_tok = tokens["tempo"] if tokens.get("tempo") else crypto.read_secret(jira.tempo_token_path())
                try:
                    if not email or not jira_tok:
                        raise jira.JiraError("Vyplň e-mail i Jira token.")
                    account_id = jira.fetch_myself(test_cfg, email, jira_tok)
                    detail = f"Jira OK ({account_id[:10]}…)"
                    if tempo_tok:
                        jira._tempo_request("GET", "/accounts?limit=1", tempo_tok)
                        detail += " · Tempo OK"
                    ok, message = True, detail
                except jira.JiraError as error:
                    ok, message = False, str(error)

                def finish() -> None:
                    if dialog.window.winfo_exists():
                        dialog.test_result(ok, message)

                events.put(("call", finish))

            threading.Thread(target=worker, daemon=True).start()

        def on_open_log(kind: str) -> None:
            if kind == "data":
                folder = cfg.get("data_dir", "")
                os.makedirs(folder, exist_ok=True)
                os.startfile(folder)
                return
            from timetrack.__main__ import startup_log_path

            path = jira.api_log_path() if kind == "api" else startup_log_path()
            if path.exists():
                os.startfile(path)
            else:
                show_message("info", f"Log zatím neexistuje:\n{path}")

        dialog = SettingsDialog(
            root, values, tokens_present, autostart.is_enabled(), __version__,
            on_save=on_save, on_test=on_test, on_open_log=on_open_log,
        )

    def open_edit_dialog(payload: str = "") -> None:
        try:
            requested = jira_day(payload)  # '', 'vcera' nebo YYYY-MM-DD
        except ValueError:
            show_message("warn", f"Neplatné datum {payload!r} — čekám YYYY-MM-DD nebo „vcera“.")
            return

        def fetch(day: date) -> list[editing.EditedInterval]:
            intervals, _passthrough = editing.load_day(cfg, day)
            return intervals

        def day_choices() -> list[tuple[date, str]]:
            days = [date.today() - timedelta(days=offset) for offset in range(14)]
            if requested not in days:
                days.append(requested)
            days.sort(reverse=True)
            choices = []
            for day in days:
                intervals, _ = editing.load_day(cfg, day)
                status = f"{len(intervals)} záznamů" if intervals else "bez záznamů"
                choices.append((day, f"{day.isoformat()} {summary.DAY_NAMES[day.weekday()]} — {status}"))
            return choices

        def save(day: date, rows: list[editing.EditedInterval]) -> str | None:
            try:
                _, passthrough = editing.load_day(cfg, day)
                editing.save_day(cfg, day, rows, passthrough)
            except editing.EditError as error:
                return str(error)
            return None

        EditDialog(root, requested, fetch, day_choices, on_save=save)

    def open_jira_dialog(payload: str = "") -> None:
        try:
            requested = jira_day(payload)
        except ValueError:
            show_message("warn", f"Neplatné datum {payload!r} — čekám YYYY-MM-DD nebo „vcera“.")
            return
        try:
            email, token = jira.load_credentials(cfg)
            jira.site_url(cfg)
        except jira.JiraError as error:
            show_message("warn", str(error))
            return

        def fetch(day: date) -> tuple[list[jira.WorklogItem], list[str]]:
            return jira.day_worklogs(cfg, day)

        def day_choices() -> list[tuple[date, str]]:
            days = [date.today() - timedelta(days=offset) for offset in range(14)]
            if requested not in days:
                days.append(requested)
            days.sort(reverse=True)
            choices = []
            for day in days:
                items, _ = jira.day_worklogs(cfg, day)
                if not items:
                    status = "bez záznamů"
                else:
                    unsent = sum(item.seconds for item in items if not item.is_sent)
                    if unsent:
                        status = f"neodesláno {format_duration(timedelta(seconds=unsent))}"
                    else:
                        status = "vše odesláno ✓"
                label = f"{day.isoformat()} {summary.DAY_NAMES[day.weekday()]} — {status}"
                choices.append((day, label))
            return choices

        def send(day: date, edited: list[jira.WorklogItem]) -> None:
            # Network calls run off the Tk thread; the result comes back
            # through the queue as a messagebox.
            def worker() -> None:
                lines = []
                failed = False
                cache: dict = {}
                for item in edited:
                    try:
                        worklog_id, source = jira.submit_worklog(
                            cfg, item, email, token, cache=cache
                        )
                        storage.append_jira_sync(
                            cfg, day, item.ticket, item.seconds, worklog_id, item.block_id,
                            source=source, comment=item.effective_comment,
                        )
                        lines.append(f"✓ {item.ticket}: {item.range_label} ({item.duration_label})")
                    except jira.JiraError as error:
                        failed = True
                        lines.append(f"✗ {error}")
                    except Exception as error:  # noqa: BLE001 — vlákno nesmí umřít tiše
                        failed = True
                        lines.append(f"✗ {item.ticket}: {type(error).__name__}: {error}")
                if cache.get("tempo_token") == "" and cfg.get("jira_account_field"):
                    lines.append("Pozn.: bez Tempo tokenu zůstává Typ činnosti prázdný (viz README).")
                events.put(("warn" if failed else "notify", "\n".join(lines)))

            threading.Thread(target=worker, daemon=True).start()

        account_cache: dict[str, str] = {}
        name_cache = ticketcache.load_names()  # ticket → název, přetrvává mezi spuštěními
        field_cache: dict = {}  # auto-discovery account pole 1× za otevřený dialog

        def load_meta(tickets: list[str]) -> None:
            wanted = list(dict.fromkeys(tickets))

            def worker() -> None:
                meta = {}
                changed = False
                for ticket in wanted:
                    if ticket not in account_cache:
                        try:
                            field_id = jira.resolve_account_field(
                                cfg, email, token, cache=field_cache
                            )
                            info = jira.fetch_issue_info(
                                cfg, ticket, email, token, field_id=field_id
                            )
                            account_cache[ticket] = info.account_name
                            if info.summary and name_cache.get(ticket) != info.summary:
                                name_cache[ticket] = info.summary
                                changed = True
                        except Exception:  # noqa: BLE001 — „?“ místo věčného „…“ v tabulce
                            account_cache[ticket] = "?"
                    meta[ticket] = {
                        "account": account_cache[ticket],
                        "name": name_cache.get(ticket, ""),
                    }
                if changed:
                    ticketcache.save_names(name_cache)

                def finish() -> None:
                    if dialog.window.winfo_exists():
                        dialog.show_meta(meta)

                events.put(("call", finish))

            threading.Thread(target=worker, daemon=True).start()

        def delete(day: date, item: jira.WorklogItem) -> None:
            def worker() -> None:
                try:
                    jira.remove_worklog(cfg, item, email, token)
                    storage.append_jira_unsync(cfg, day, item.ticket, item.worklog_id, item.block_id)
                    error = None
                except jira.JiraError as failure:
                    error = str(failure)
                except Exception as failure:  # noqa: BLE001 — vlákno nesmí umřít tiše
                    error = f"{type(failure).__name__}: {failure}"

                def finish() -> None:
                    if not dialog.window.winfo_exists():
                        if error:
                            show_message("warn", error)
                        return
                    if error:
                        dialog.delete_failed(error)
                    else:
                        dialog.refresh()

                events.put(("call", finish))

            threading.Thread(target=worker, daemon=True).start()

        dialog = JiraDialog(
            root,
            requested,
            fetch,
            day_choices,
            on_send=send,
            on_delete=delete,
            on_meta=load_meta,
            ticket_names=name_cache,
        )

    def handle_submit(text: str) -> None:
        action, payload = parse_command(text)
        try:
            execute(action, payload)
        except Exception as error:  # noqa: BLE001 — pythonw has no stderr to die into
            show_message("warn", f"Akce se nezdařila.\n{type(error).__name__}: {error}")

    popup = Popup(
        root,
        on_submit=handle_submit,
        get_status=lambda: current_status(cfg),
        get_tickets=lambda: storage.recent_tickets(cfg),
    )
    tray.start()

    def poll() -> None:
        try:
            while True:
                action, payload = events.get_nowait()
                if action in ("quit", "error"):
                    execute(action, payload)
                    return
                try:
                    execute(action, payload)
                except Exception as error:  # noqa: BLE001
                    # One failing action must not kill the queue — without
                    # this the app would silently stop reacting to the hotkey
                    # and the tray for good.
                    show_message("warn", f"Akce se nezdařila.\n{type(error).__name__}: {error}")
        except queue.Empty:
            pass
        root.after(POLL_MS, poll)

    root.after(POLL_MS, poll)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        # Foreground běh (py -m timetrack) ukončený Ctrl+C: ukliď tray ikonu
        # a okno místo vyhození tracebacku. Běžně se pouští bez konzole
        # (pythonw/TimeTrack.exe), kde Ctrl+C nepřijde — konec je přes menu
        # nebo `py -m timetrack quit`.
        print("\nTimeTrack ukončen.")
        tray.stop()
        try:
            root.destroy()
        except tk.TclError:
            pass


def current_status(cfg: dict) -> str:
    """Describe the currently running activity, read fresh from today's file."""
    now = datetime.now().astimezone()
    intervals = build_intervals(storage.read_day_events(cfg, date.today()))
    if not intervals or not intervals[-1].is_running:
        return "⏸ Nic neběží"
    running = intervals[-1]
    since = running.start.strftime("%H:%M")
    return f"▶ {running.text} — od {since} ({format_duration(running.duration(now))})"
