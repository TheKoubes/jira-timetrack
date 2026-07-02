"""Manage the "run at login" shortcut in the Startup folder.

Lets the Settings UI toggle autostart without the external
``install_autostart.ps1``. The shortcut target adapts to how TimeTrack runs
now: a frozen ``.exe`` points at itself, a Python run at pythonw / the
renamed launcher with ``-m timetrack``.
"""

import os
import subprocess
import sys
from pathlib import Path

SHORTCUT_NAME = "TimeTrack.lnk"
_CREATE_NO_WINDOW = 0x08000000


def _startup_dir() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def shortcut_path() -> Path:
    return _startup_dir() / SHORTCUT_NAME


def launch_target() -> tuple[str, str, str]:
    """Return (target exe, arguments, working dir) for autostart on this runtime."""
    if getattr(sys, "frozen", False):  # PyInstaller .exe
        exe = Path(sys.executable)
        return str(exe), "", str(exe.parent)
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        pythonw = exe.with_name("pythonw.exe")  # bez konzole
        target = pythonw if pythonw.exists() else exe
    else:
        target = exe  # pythonw.exe nebo přejmenovaný launcher (TimeTrack.exe)
    workdir = Path(__file__).resolve().parent.parent  # složka s balíčkem (kvůli -m)
    return str(target), "-m timetrack", str(workdir)


def is_enabled() -> bool:
    return shortcut_path().exists()


def enable() -> None:
    """Create the Startup shortcut pointing at the current runtime."""
    target, args, workdir = launch_target()
    lnk = shortcut_path()
    lnk.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$s=New-Object -ComObject WScript.Shell;"
        "$sc=$s.CreateShortcut($env:TT_LNK);"
        "$sc.TargetPath=$env:TT_TARGET;"
        "$sc.Arguments=$env:TT_ARGS;"
        "$sc.WorkingDirectory=$env:TT_WORKDIR;"
        "$sc.Description='TimeTrack - evidence odpracovaneho casu';"
        "$sc.Save()"
    )
    env = dict(
        os.environ,
        TT_LNK=str(lnk),
        TT_TARGET=target,
        TT_ARGS=args,
        TT_WORKDIR=workdir,
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        env=env,
        creationflags=_CREATE_NO_WINDOW,
        check=True,
        capture_output=True,
    )


def disable() -> None:
    shortcut_path().unlink(missing_ok=True)


def set_enabled(enabled: bool) -> None:
    if enabled:
        enable()
    else:
        disable()
