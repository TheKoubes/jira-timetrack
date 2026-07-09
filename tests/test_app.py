from datetime import date, datetime, timedelta, timezone

import pytest

from timetrack import storage
from timetrack.app import jira_day, parse_command, stop_running_activity

TZ = timezone(timedelta(hours=2))


@pytest.fixture
def cfg(tmp_path):
    return {
        "data_dir": str(tmp_path / "data"),
        "filename_format": "%Y-%m-%d.jsonl",
        "hotkey": "ctrl+alt+t",
    }


class TestStopRunningActivity:
    def test_stops_when_activity_running(self, cfg):
        storage.append_start(cfg, "PROJ-1 prace")

        assert stop_running_activity(cfg) is True
        events = storage.read_day_events(cfg, date.today())
        assert events[-1]["type"] == "stop"

    def test_noop_when_nothing_running(self, cfg):
        storage.append_start(cfg, "PROJ-1 prace")
        storage.append_stop(cfg)
        before = storage.read_day_events(cfg, date.today())

        assert stop_running_activity(cfg) is False
        assert storage.read_day_events(cfg, date.today()) == before

    def test_noop_on_empty_day(self, cfg):
        assert stop_running_activity(cfg) is False
        assert storage.read_day_events(cfg, date.today()) == []


def test_plain_text_starts_activity():
    assert parse_command("DEMOERP-1 oprava loginu") == ("start", "DEMOERP-1 oprava loginu")


def test_stop_words():
    assert parse_command("stop") == ("stop", "")
    assert parse_command("pauza") == ("stop", "")
    assert parse_command("Stop") == ("stop", "")


def test_quit_words():
    assert parse_command("quit") == ("quit", "")
    assert parse_command("konec") == ("quit", "")


def test_summary_words():
    assert parse_command("?") == ("summary", "")
    assert parse_command("den") == ("summary", "")


def test_week_words():
    assert parse_command("týden") == ("week", "")
    assert parse_command("tyden") == ("week", "")
    assert parse_command("week") == ("week", "")
    assert parse_command("Týden") == ("week", "")


def test_jira_word():
    assert parse_command("jira") == ("jira", "")
    assert parse_command("Jira") == ("jira", "")


def test_jira_word_with_date_payload():
    assert parse_command("jira 2026-06-09") == ("jira", "2026-06-09")
    assert parse_command("Jira vcera") == ("jira", "vcera")


def test_word_starting_with_jira_is_activity():
    assert parse_command("jiranek volal") == ("start", "jiranek volal")


def test_jira_day_empty_is_today():
    assert jira_day("") == date.today()


def test_jira_day_vcera():
    assert jira_day("vcera") == date.today() - timedelta(days=1)
    assert jira_day("Včera") == date.today() - timedelta(days=1)


def test_jira_day_iso_date():
    assert jira_day("2026-06-09") == date(2026, 6, 9)


def test_jira_day_invalid_raises():
    with pytest.raises(ValueError):
        jira_day("pozitri")


def test_edit_words():
    assert parse_command("uprav") == ("edit", "")
    assert parse_command("upravit") == ("edit", "")
    assert parse_command("edit") == ("edit", "")


def test_edit_word_with_date_payload():
    assert parse_command("uprav 2026-06-09") == ("edit", "2026-06-09")
    assert parse_command("edit vcera") == ("edit", "vcera")


def test_word_starting_with_uprav_is_activity():
    assert parse_command("upravy designu") == ("start", "upravy designu")


def test_settings_words():
    assert parse_command("nastaveni") == ("settings", "")
    assert parse_command("nastavení") == ("settings", "")
    assert parse_command("settings") == ("settings", "")


def test_restart_words():
    assert parse_command("restart") == ("restart", "")
    assert parse_command("restartovat") == ("restart", "")
    assert parse_command("Restart") == ("restart", "")


def test_pozn_prefix_adds_note():
    assert parse_command("pozn cekam na build") == ("note", "cekam na build")


def test_pozn_prefix_is_case_insensitive():
    assert parse_command("POZN neco") == ("note", "neco")


def test_bare_pozn_gives_empty_note():
    assert parse_command("pozn") == ("note", "")


def test_word_starting_with_pozn_is_activity():
    assert parse_command("poznamky k poradě") == ("start", "poznamky k poradě")


def test_ticket_prefix_attaches_ticket():
    assert parse_command("ticket DEMOERP-9") == ("ticket", "DEMOERP-9")
    assert parse_command("Ticket https://x.net/browse/Z-1") == (
        "ticket",
        "https://x.net/browse/Z-1",
    )


def test_bare_ticket_gives_empty_payload():
    assert parse_command("ticket") == ("ticket", "")


def test_word_starting_with_ticket_is_activity():
    assert parse_command("tickety zakaznika") == ("start", "tickety zakaznika")
