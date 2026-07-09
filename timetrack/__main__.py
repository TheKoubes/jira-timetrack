"""Entry point and CLI: run (default) | log "text" | stop | summary [date]."""

import os
import sys
from datetime import date, datetime

from timetrack import config, jira, storage, summary

USAGE = """\
Pouziti:
  python -m timetrack                  spusti aplikaci na pozadi (globalni zkratka)
  python -m timetrack log <text>       zacne novou aktivitu (predchozi ukonci)
  python -m timetrack note <text>      prida poznamku k posledni aktivite
  python -m timetrack stop             ukonci bezici aktivitu
  python -m timetrack summary [datum]  vytvori denni sumar (datum = YYYY-MM-DD, vychozi dnes)
  python -m timetrack week [datum]     vytvori tydenni prehled (tyden obsahujici datum)
  python -m timetrack jira [datum]     odesle worklogy dne do Jiry (interaktivni vyber)
  python -m timetrack restart          restartuje bezici aplikaci (nacte novou verzi kodu)
  python -m timetrack quit             ukonci bezici aplikaci na pozadi
"""


def _relaunch_argv() -> list[str]:
    """Prikaz pro spusteni nove instance GUI (dev pythonw i frozen .exe)."""
    if getattr(sys, "frozen", False):
        return [sys.executable]  # TimeTrack.exe -> run_timetrack -> GUI
    exe = sys.executable
    # CLI `restart` bezi pod konzolovym python.exe -> pro novou instanci radeji
    # pythonw.exe (bez okna); GUI uz bezi pod pythonw/TimeTrack.exe -> nechat.
    if os.path.basename(exe).lower() == "python.exe":
        windowless = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(windowless):
            exe = windowless
    return [exe, "-m", "timetrack"]


def spawn_instance() -> None:
    """Spusti novou, odpojenou instanci aplikace (prezije ukonceni te soucasne)."""
    import subprocess
    from pathlib import Path

    if getattr(sys, "frozen", False):
        cwd = Path(sys.executable).resolve().parent
    else:
        cwd = Path(__file__).resolve().parent.parent  # obsahuje balik timetrack/
    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP — nezavisla na rodici.
    flags = 0x00000008 | 0x00000200
    subprocess.Popen(_relaunch_argv(), cwd=str(cwd), creationflags=flags, close_fds=True)


def main(argv: list[str] | None = None, cfg: dict | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    command = argv[0] if argv else "run"

    # The GUI launch typically runs under pythonw, which has no console — an
    # unhandled error there (broken config, Tk init failure) would kill the
    # process invisibly. Guard it and surface the cause; CLI commands keep
    # their console, so they fall through and print tracebacks normally.
    if command == "run":
        return _run_gui(cfg)

    cfg = cfg or config.load_config()

    if command == "log":
        text = " ".join(argv[1:]).strip()
        if not text:
            print(USAGE, file=sys.stderr)
            return 2
        event = storage.append_start(cfg, text)
        print(f"Zaznamenano: {event['text']} ({event['ts']})")
        return 0

    if command == "note":
        text = " ".join(argv[1:]).strip()
        if not text:
            print(USAGE, file=sys.stderr)
            return 2
        event = storage.append_note(cfg, text)
        print(f"Poznamka pridana: {event['text']} ({event['ts']})")
        return 0

    if command == "stop":
        event = storage.append_stop(cfg)
        print(f"Aktivita ukoncena ({event['ts']})")
        return 0

    if command == "summary":
        day = date.fromisoformat(argv[1]) if len(argv) > 1 else date.today()
        path = summary.write_summary(cfg, day)
        print(path)
        print(path.read_text(encoding="utf-8"))
        return 0

    if command == "week":
        day = date.fromisoformat(argv[1]) if len(argv) > 1 else date.today()
        path = summary.write_week_summary(cfg, day)
        print(path)
        print(path.read_text(encoding="utf-8"))
        return 0

    if command == "jira":
        day = date.fromisoformat(argv[1]) if len(argv) > 1 else date.today()
        return jira.run_send_command(cfg, day)

    if command == "restart":
        import time

        from timetrack import tray  # lazy: Win32 vrstva jen kdyz je potreba

        running = tray.request_quit()
        if running:
            for _ in range(30):  # ~6 s: pockej, az stara instance uvolni zkratku
                if not tray.is_running():
                    break
                time.sleep(0.2)
        spawn_instance()
        print("TimeTrack restartovan." if running else "TimeTrack nebezel — spusten.")
        return 0

    if command == "quit":
        from timetrack import tray  # lazy: Win32 vrstva jen kdyz je potreba

        if tray.request_quit():
            print("TimeTrack ukoncen.")
            return 0
        print("TimeTrack nebezi.", file=sys.stderr)
        return 1

    print(USAGE, file=sys.stderr)
    return 2


def _run_gui(cfg: dict | None) -> int:
    try:
        cfg = cfg or config.load_config()
        from timetrack.app import run_app  # lazy: GUI imports only when needed

        run_app(cfg)
        return 0
    except Exception as error:  # noqa: BLE001 — pythonw nema kam vypsat traceback
        _report_startup_failure(error)
        return 1


def startup_log_path():
    return config.default_config_path().parent / "startup_error.log"


def _report_startup_failure(error: Exception) -> None:
    import traceback

    log = startup_log_path()
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            stamp = datetime.now().astimezone().isoformat(timespec="seconds")
            f.write(f"{stamp}\n{traceback.format_exc()}\n---\n")
    except OSError:
        pass
    try:
        _show_native_error(
            "TimeTrack se nepodařilo spustit",
            f"{type(error).__name__}: {error}\n\nDetail: {log}",
        )
    except Exception:  # noqa: BLE001 — hlaseni chyby nesmi spadnout samo
        pass


def _show_native_error(title: str, body: str) -> None:
    # Nativni MessageBox (nezavisly na tkinteru, ktery muze byt prave ten,
    # co selhal) — funguje i bez konzole pod pythonw.
    import ctypes

    ctypes.windll.user32.MessageBoxW(0, body, title, 0x10)  # MB_ICONERROR


if __name__ == "__main__":
    sys.exit(main())
