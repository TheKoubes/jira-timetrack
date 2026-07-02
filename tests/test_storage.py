import json
from datetime import date, datetime, timedelta, timezone

import pytest

from timetrack import storage

TZ = timezone(timedelta(hours=2))


@pytest.fixture
def cfg(tmp_path):
    return {
        "data_dir": str(tmp_path / "data"),
        "filename_format": "%Y-%m-%d.jsonl",
        "summary_filename_format": "%Y-%m-%d-summary.md",
        "hotkey": "ctrl+alt+t",
    }


def test_day_file_path_uses_data_dir_and_filename_format(cfg):
    cfg["filename_format"] = "den-%d-%m-%Y.jsonl"

    path = storage.day_file_path(cfg, date(2026, 6, 10))

    assert path.name == "den-10-06-2026.jsonl"
    assert str(path.parent) == cfg["data_dir"]


def test_append_start_writes_one_json_line_with_ticket(cfg):
    when = datetime(2026, 6, 10, 14, 32, 5, tzinfo=TZ)

    storage.append_start(cfg, "PROJ-123 oprava loginu", ts=when)

    lines = storage.day_file_path(cfg, when.date()).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event == {
        "ts": "2026-06-10T14:32:05+02:00",
        "type": "start",
        "text": "PROJ-123 oprava loginu",
        "ticket": "PROJ-123",
    }


def test_append_start_omits_ticket_when_not_found(cfg):
    when = datetime(2026, 6, 10, 9, 0, tzinfo=TZ)

    storage.append_start(cfg, "standup", ts=when)

    event = json.loads(storage.day_file_path(cfg, when.date()).read_text(encoding="utf-8"))
    assert "ticket" not in event


def test_append_is_append_only(cfg):
    when = datetime(2026, 6, 10, 9, 0, tzinfo=TZ)

    storage.append_start(cfg, "prvni", ts=when)
    storage.append_start(cfg, "druha", ts=when + timedelta(minutes=30))
    storage.append_stop(cfg, ts=when + timedelta(hours=1))

    lines = storage.day_file_path(cfg, when.date()).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["text"] == "prvni"
    assert json.loads(lines[2]) == {"ts": "2026-06-10T10:00:00+02:00", "type": "stop"}


def test_append_start_splits_note_from_text(cfg):
    when = datetime(2026, 6, 10, 9, 0, tzinfo=TZ)

    storage.append_start(cfg, "DEMOERP-1 oprava // cekal jsem na build", ts=when)

    event = json.loads(storage.day_file_path(cfg, when.date()).read_text(encoding="utf-8"))
    assert event["text"] == "DEMOERP-1 oprava"
    assert event["note"] == "cekal jsem na build"
    assert event["ticket"] == "DEMOERP-1"


def test_append_start_without_note_has_no_note_key(cfg):
    when = datetime(2026, 6, 10, 9, 0, tzinfo=TZ)

    storage.append_start(cfg, "bez poznamky", ts=when)

    event = json.loads(storage.day_file_path(cfg, when.date()).read_text(encoding="utf-8"))
    assert "note" not in event


def test_ticket_in_note_part_is_ignored(cfg):
    when = datetime(2026, 6, 10, 9, 0, tzinfo=TZ)

    storage.append_start(cfg, "oprava buildu // souvisi se DEMOERP-9", ts=when)

    event = json.loads(storage.day_file_path(cfg, when.date()).read_text(encoding="utf-8"))
    assert "ticket" not in event


def test_append_start_with_jira_url_uses_key_without_link_note(cfg):
    when = datetime(2026, 6, 10, 9, 0, tzinfo=TZ)
    url = "https://firma.atlassian.net/browse/VEGAERP-861?actionerId=712020&sourceType=assign"

    storage.append_start(cfg, url, ts=when)

    events = storage.read_day_events(cfg, when.date())
    assert len(events) == 1
    assert events[0]["type"] == "start"
    assert events[0]["text"] == "VEGAERP-861"
    assert events[0]["ticket"] == "VEGAERP-861"
    assert "note" not in events[0]


def test_append_start_with_jira_url_and_explicit_note_keeps_note(cfg):
    when = datetime(2026, 6, 10, 9, 0, tzinfo=TZ)

    storage.append_start(
        cfg, "https://firma.atlassian.net/browse/DEMOERP-1185 // cekal jsem", ts=when
    )

    events = storage.read_day_events(cfg, when.date())
    assert len(events) == 1
    assert events[0]["text"] == "DEMOERP-1185"
    assert events[0]["note"] == "cekal jsem"


def test_append_ticket_from_key(cfg):
    when = datetime(2026, 6, 10, 9, 30, tzinfo=TZ)

    event = storage.append_ticket(cfg, "DEMOERP-9", ts=when)

    assert event == {"ts": "2026-06-10T09:30:00+02:00", "type": "ticket", "ticket": "DEMOERP-9"}
    stored = json.loads(storage.day_file_path(cfg, when.date()).read_text(encoding="utf-8"))
    assert stored == event


def test_append_ticket_from_url(cfg):
    when = datetime(2026, 6, 10, 9, 30, tzinfo=TZ)

    event = storage.append_ticket(
        cfg, "https://firma.atlassian.net/browse/DEMOERP-9?focus=1", ts=when
    )

    assert event["ticket"] == "DEMOERP-9"


def test_append_ticket_without_key_raises(cfg):
    with pytest.raises(ValueError):
        storage.append_ticket(cfg, "tady nic neni")
    assert storage.read_day_events(cfg, date.today()) == []


def test_append_start_with_non_jira_url_keeps_whole_text(cfg):
    when = datetime(2026, 6, 10, 9, 0, tzinfo=TZ)

    storage.append_start(cfg, "kontrola https://github.com/foo/bar", ts=when)

    events = storage.read_day_events(cfg, when.date())
    assert len(events) == 1
    assert events[0]["text"] == "kontrola https://github.com/foo/bar"
    assert "note" not in events[0]


def test_append_note_writes_note_event(cfg):
    when = datetime(2026, 6, 10, 9, 30, tzinfo=TZ)

    storage.append_note(cfg, "cekam na review", ts=when)

    event = json.loads(storage.day_file_path(cfg, when.date()).read_text(encoding="utf-8"))
    assert event == {
        "ts": "2026-06-10T09:30:00+02:00",
        "type": "note",
        "text": "cekam na review",
    }


def test_append_heals_missing_trailing_newline_after_hand_edit(cfg):
    when = datetime(2026, 6, 10, 9, 0, tzinfo=TZ)
    storage.append_start(cfg, "prvni", ts=when)
    path = storage.day_file_path(cfg, when.date())
    path.write_bytes(path.read_bytes().rstrip(b"\n"))  # simulace rucni editace

    storage.append_stop(cfg, ts=when + timedelta(hours=1))

    events = storage.read_day_events(cfg, when.date())
    assert [e["type"] for e in events] == ["start", "stop"]


def test_append_jira_sync_goes_to_target_days_file(cfg):
    target_day = date(2026, 6, 1)
    start_ts = "2026-06-01T09:00:00+02:00"

    event = storage.append_jira_sync(cfg, target_day, "PROJ-9", 3600, "123", start_ts)

    lines = storage.day_file_path(cfg, target_day).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    stored = json.loads(lines[0])
    assert stored == event
    assert stored["type"] == "jira_sync"
    assert stored["ticket"] == "PROJ-9"
    assert stored["seconds"] == 3600
    assert stored["worklog_id"] == "123"
    assert stored["start_ts"] == start_ts


def test_append_jira_unsync_records_deletion(cfg):
    target_day = date(2026, 6, 1)

    event = storage.append_jira_unsync(cfg, target_day, "PROJ-9", "123", "2026-06-01T09:00:00+02:00")

    stored = json.loads(
        storage.day_file_path(cfg, target_day).read_text(encoding="utf-8")
    )
    assert stored == event
    assert stored["type"] == "jira_unsync"
    assert stored["worklog_id"] == "123"
    assert stored["start_ts"] == "2026-06-01T09:00:00+02:00"


def test_read_day_events_round_trips(cfg):
    when = datetime(2026, 6, 10, 9, 0, tzinfo=TZ)
    storage.append_start(cfg, "PROJ-1 prace", ts=when)
    storage.append_stop(cfg, ts=when + timedelta(minutes=15))

    events = storage.read_day_events(cfg, date(2026, 6, 10))

    assert [e["type"] for e in events] == ["start", "stop"]
    assert events[0]["text"] == "PROJ-1 prace"


def test_read_day_events_returns_empty_list_for_missing_file(cfg):
    assert storage.read_day_events(cfg, date(2026, 1, 1)) == []


class TestRecentTickets:
    def test_distinct_most_recent_first(self, cfg):
        storage.append_start(cfg, "AAA-1 stara", ts=datetime(2026, 6, 8, 9, 0, tzinfo=TZ))
        storage.append_start(cfg, "BBB-2 novejsi", ts=datetime(2026, 6, 9, 9, 0, tzinfo=TZ))
        storage.append_start(cfg, "AAA-1 zase", ts=datetime(2026, 6, 10, 9, 0, tzinfo=TZ))

        tickets = storage.recent_tickets(cfg, days=10, today=date(2026, 6, 10))

        assert tickets == ["AAA-1", "BBB-2"]  # AAA-1 naposledy 10., BBB-2 9.

    def test_ignores_activities_without_ticket(self, cfg):
        storage.append_start(cfg, "porada bez ticketu", ts=datetime(2026, 6, 10, 9, 0, tzinfo=TZ))

        assert storage.recent_tickets(cfg, days=5, today=date(2026, 6, 10)) == []

    def test_respects_day_window(self, cfg):
        storage.append_start(cfg, "OLD-1 prace", ts=datetime(2026, 6, 1, 9, 0, tzinfo=TZ))

        assert storage.recent_tickets(cfg, days=3, today=date(2026, 6, 10)) == []

    def test_ticket_event_counts_too(self, cfg):
        storage.append_start(cfg, "neco bez klice", ts=datetime(2026, 6, 10, 9, 0, tzinfo=TZ))
        storage.append_ticket(cfg, "DEMOERP-9", ts=datetime(2026, 6, 10, 9, 30, tzinfo=TZ))

        assert storage.recent_tickets(cfg, days=5, today=date(2026, 6, 10)) == ["DEMOERP-9"]


def test_event_goes_to_file_of_its_local_date(cfg):
    late_evening = datetime(2026, 6, 10, 23, 55, tzinfo=TZ)

    storage.append_start(cfg, "nocni prace", ts=late_evening)

    assert storage.day_file_path(cfg, date(2026, 6, 10)).exists()
    assert not storage.day_file_path(cfg, date(2026, 6, 11)).exists()
