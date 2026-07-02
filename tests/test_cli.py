import json
from datetime import date, datetime

import pytest

from timetrack import storage
from timetrack.__main__ import main


@pytest.fixture
def cfg(tmp_path):
    return {
        "data_dir": str(tmp_path / "data"),
        "filename_format": "%Y-%m-%d.jsonl",
        "summary_filename_format": "%Y-%m-%d-summary.md",
        "week_summary_filename_format": "%G-W%V-summary.md",
        "hotkey": "ctrl+alt+t",
    }


def today_events(cfg):
    return storage.read_day_events(cfg, date.today())


def test_log_starts_activity(cfg):
    exit_code = main(["log", "PROJ-7 oprava deploye"], cfg=cfg)

    assert exit_code == 0
    events = today_events(cfg)
    assert len(events) == 1
    assert events[0]["type"] == "start"
    assert events[0]["text"] == "PROJ-7 oprava deploye"
    assert events[0]["ticket"] == "PROJ-7"


def test_log_joins_unquoted_words(cfg):
    main(["log", "oprava", "deploye"], cfg=cfg)

    assert today_events(cfg)[0]["text"] == "oprava deploye"


def test_log_without_text_fails(cfg):
    exit_code = main(["log"], cfg=cfg)

    assert exit_code != 0
    assert today_events(cfg) == []


def test_stop_appends_stop_event(cfg):
    main(["log", "neco"], cfg=cfg)

    exit_code = main(["stop"], cfg=cfg)

    assert exit_code == 0
    assert [e["type"] for e in today_events(cfg)] == ["start", "stop"]


def test_note_appends_note_event(cfg):
    main(["log", "neco"], cfg=cfg)

    exit_code = main(["note", "cekam", "na", "review"], cfg=cfg)

    assert exit_code == 0
    events = today_events(cfg)
    assert events[-1]["type"] == "note"
    assert events[-1]["text"] == "cekam na review"


def test_note_without_text_fails(cfg):
    exit_code = main(["note"], cfg=cfg)

    assert exit_code != 0
    assert today_events(cfg) == []


def test_summary_writes_file_and_prints_path(cfg, capsys):
    main(["log", "PROJ-1 prace"], cfg=cfg)

    exit_code = main(["summary"], cfg=cfg)

    assert exit_code == 0
    expected = date.today().strftime("%Y-%m-%d-summary.md")
    out = capsys.readouterr().out
    assert expected in out
    assert "PROJ-1 prace" in out


def test_summary_accepts_explicit_date(cfg, tmp_path):
    day_file = storage.day_file_path(cfg, date(2026, 6, 1))
    day_file.parent.mkdir(parents=True)
    event = {"ts": "2026-06-01T09:00:00+02:00", "type": "start", "text": "stara prace"}
    stop = {"ts": "2026-06-01T10:00:00+02:00", "type": "stop"}
    day_file.write_text(json.dumps(event) + "\n" + json.dumps(stop) + "\n", encoding="utf-8")

    exit_code = main(["summary", "2026-06-01"], cfg=cfg)

    assert exit_code == 0
    summary_path = day_file.parent / "2026-06-01-summary.md"
    assert summary_path.exists()
    assert "stara prace" in summary_path.read_text(encoding="utf-8")


def test_week_writes_file_for_current_week(cfg, capsys):
    main(["log", "Z-1 prace"], cfg=cfg)

    exit_code = main(["week"], cfg=cfg)

    assert exit_code == 0
    iso = date.today().isocalendar()
    expected = f"{iso.year}-W{iso.week:02d}-summary.md"
    out = capsys.readouterr().out
    assert expected in out
    assert "Z-1 prace" in out


def test_week_accepts_explicit_date(cfg):
    day_file = storage.day_file_path(cfg, date(2026, 6, 9))
    day_file.parent.mkdir(parents=True)
    event = {"ts": "2026-06-09T09:00:00+02:00", "type": "start", "text": "uterni prace"}
    stop = {"ts": "2026-06-09T10:00:00+02:00", "type": "stop"}
    day_file.write_text(json.dumps(event) + "\n" + json.dumps(stop) + "\n", encoding="utf-8")

    exit_code = main(["week", "2026-06-12"], cfg=cfg)

    assert exit_code == 0
    week_path = day_file.parent / "2026-W24-summary.md"
    assert week_path.exists()
    assert "uterni prace" in week_path.read_text(encoding="utf-8")


def test_jira_command_without_setup_fails(cfg, capsys):
    exit_code = main(["jira"], cfg=cfg)

    assert exit_code == 1
    assert "jira_email" in capsys.readouterr().err


def test_quit_succeeds_when_app_runs(cfg, monkeypatch, capsys):
    monkeypatch.setattr("timetrack.tray.request_quit", lambda: True)

    assert main(["quit"], cfg=cfg) == 0
    assert "ukoncen" in capsys.readouterr().out


def test_quit_fails_when_app_does_not_run(cfg, monkeypatch, capsys):
    monkeypatch.setattr("timetrack.tray.request_quit", lambda: False)

    assert main(["quit"], cfg=cfg) == 1
    assert "nebezi" in capsys.readouterr().err


def test_unknown_command_fails(cfg):
    assert main(["vymysleny"], cfg=cfg) != 0


def test_run_reports_startup_failure_instead_of_crashing(monkeypatch, tmp_path):
    from timetrack import __main__ as entry

    monkeypatch.setattr(
        entry.config, "default_config_path", lambda: tmp_path / ".timetrack" / "config.json"
    )

    def boom():
        raise ValueError("rozbity config")

    monkeypatch.setattr(entry.config, "load_config", boom)
    shown = []
    monkeypatch.setattr(entry, "_show_native_error", lambda title, body: shown.append(body))

    exit_code = main(["run"])

    assert exit_code == 1
    assert shown and "rozbity config" in shown[0]
    log = tmp_path / ".timetrack" / "startup_error.log"
    assert log.exists()
    assert "rozbity config" in log.read_text(encoding="utf-8")


def test_run_reports_when_app_raises(monkeypatch, tmp_path, cfg):
    from timetrack import __main__ as entry

    monkeypatch.setattr(
        entry.config, "default_config_path", lambda: tmp_path / ".timetrack" / "config.json"
    )
    monkeypatch.setattr("timetrack.app.run_app", lambda c: (_ for _ in ()).throw(RuntimeError("Tk selhal")))
    shown = []
    monkeypatch.setattr(entry, "_show_native_error", lambda title, body: shown.append(body))

    exit_code = main(["run"], cfg=cfg)

    assert exit_code == 1
    assert shown and "Tk selhal" in shown[0]
