import sys

from timetrack import autostart


def test_shortcut_path_uses_startup_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "_startup_dir", lambda: tmp_path)

    assert autostart.shortcut_path() == tmp_path / "TimeTrack.lnk"


def test_launch_target_python_uses_module_run(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Py\python.exe")
    # pythonw vedle nemusi existovat -> fallback na python.exe, args zustanou
    target, args, workdir = autostart.launch_target()

    assert args == "-m timetrack"
    assert target.lower().endswith("python.exe") or target.lower().endswith("pythonw.exe")
    assert workdir  # neprazdny


def test_launch_target_frozen_points_at_exe(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\TimeTrack.exe")

    target, args, workdir = autostart.launch_target()

    assert target == r"C:\Apps\TimeTrack.exe"
    assert args == ""
    assert workdir == r"C:\Apps"


def test_is_enabled_and_disable(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "_startup_dir", lambda: tmp_path)
    assert autostart.is_enabled() is False

    (tmp_path / "TimeTrack.lnk").write_text("x", encoding="utf-8")
    assert autostart.is_enabled() is True

    autostart.disable()
    assert autostart.is_enabled() is False


def test_set_enabled_false_removes(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "_startup_dir", lambda: tmp_path)
    (tmp_path / "TimeTrack.lnk").write_text("x", encoding="utf-8")

    autostart.set_enabled(False)

    assert not (tmp_path / "TimeTrack.lnk").exists()
