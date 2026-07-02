import json
from datetime import date, datetime, timedelta, timezone

import pytest

from timetrack import editing, jira, storage
from timetrack.editing import EditedInterval, EditError

TZ = timezone(timedelta(hours=2))
DAY = date(2026, 6, 10)


@pytest.fixture
def cfg(tmp_path):
    return {
        "data_dir": str(tmp_path / "data"),
        "filename_format": "%Y-%m-%d.jsonl",
        "rounding_minutes": 15,
        "rounding_mode": "nearest",
        "round_times": False,
        "jira_base_url": "https://firma.atlassian.net/browse/",
        "jira_email": "ja@firma.cz",
    }


def when(hour, minute, second=0):
    return datetime(2026, 6, 10, hour, minute, second, tzinfo=TZ)


def raw_events(cfg):
    path = storage.day_file_path(cfg, DAY)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class TestLoadDay:
    def test_builds_intervals_with_notes_and_passthrough(self, cfg):
        storage.append_start(cfg, "PROJ-1 oprava // inline pozn", ts=when(9, 0))
        storage.append_note(cfg, "dalsi poznamka", ts=when(9, 30))
        storage.append_stop(cfg, ts=when(10, 0))
        storage.append_jira_sync(cfg, DAY, "PROJ-1", 3600, "77", when(9, 0).isoformat())

        intervals, passthrough = editing.load_day(cfg, DAY)

        assert len(intervals) == 1
        assert intervals[0].start == when(9, 0)
        assert intervals[0].end == when(10, 0)
        assert intervals[0].text == "PROJ-1 oprava"
        assert [text for _ts, text in intervals[0].notes] == ["inline pozn", "dalsi poznamka"]
        assert intervals[0].original_start == when(9, 0)
        assert [e["type"] for e in passthrough] == ["jira_sync"]

    def test_orphan_note_before_first_start_passes_through(self, cfg):
        storage.append_note(cfg, "do prazdna", ts=when(8, 0))
        storage.append_start(cfg, "prace", ts=when(9, 0))

        intervals, passthrough = editing.load_day(cfg, DAY)

        assert intervals[0].notes == []
        assert passthrough == [
            {"ts": when(8, 0).isoformat(), "type": "note", "text": "do prazdna"}
        ]

    def test_ticket_event_merges_into_activity_text(self, cfg):
        storage.append_start(cfg, "obnova databazi", ts=when(9, 0))
        storage.append_ticket(cfg, "DEMOERP-9", ts=when(9, 30))
        storage.append_stop(cfg, ts=when(10, 0))

        intervals, passthrough = editing.load_day(cfg, DAY)

        assert intervals[0].text == "DEMOERP-9 obnova databazi"
        assert passthrough == []

        editing.save_day(cfg, DAY, intervals, passthrough)

        events = raw_events(cfg)
        assert [e["type"] for e in events] == ["start", "stop"]
        assert events[0]["ticket"] == "DEMOERP-9"

    def test_empty_day(self, cfg):
        assert editing.load_day(cfg, DAY) == ([], [])


class TestSaveDay:
    def test_unchanged_roundtrip_keeps_semantics_and_makes_backup(self, cfg):
        storage.append_start(cfg, "PROJ-1 oprava", ts=when(9, 0))
        storage.append_note(cfg, "poznamka", ts=when(9, 30))
        storage.append_start(cfg, "schuzka", ts=when(10, 0))
        storage.append_stop(cfg, ts=when(11, 0))
        original = storage.day_file_path(cfg, DAY).read_text(encoding="utf-8")
        intervals, passthrough = editing.load_day(cfg, DAY)

        editing.save_day(cfg, DAY, intervals, passthrough)

        reloaded, _ = editing.load_day(cfg, DAY)
        assert [(i.start, i.end, i.text) for i in reloaded] == [
            (when(9, 0), when(10, 0), "PROJ-1 oprava"),
            (when(10, 0), when(11, 0), "schuzka"),
        ]
        assert [text for _ts, text in reloaded[0].notes] == ["poznamka"]
        backup = storage.day_file_path(cfg, DAY).with_suffix(".jsonl.bak")
        assert backup.read_text(encoding="utf-8") == original

    def test_adjacent_intervals_share_boundary_without_stop(self, cfg):
        storage.append_start(cfg, "prvni", ts=when(9, 0))
        storage.append_start(cfg, "druha", ts=when(10, 0))
        storage.append_stop(cfg, ts=when(11, 0))
        intervals, passthrough = editing.load_day(cfg, DAY)

        editing.save_day(cfg, DAY, intervals, passthrough)

        assert [e["type"] for e in raw_events(cfg)] == ["start", "start", "stop"]

    def test_gap_between_intervals_gets_explicit_stop(self, cfg):
        storage.append_start(cfg, "prvni", ts=when(9, 0))
        storage.append_start(cfg, "druha", ts=when(10, 0))
        storage.append_stop(cfg, ts=when(11, 0))
        intervals, passthrough = editing.load_day(cfg, DAY)
        intervals[0].end = when(9, 45)  # konec posunut, vznikla mezera

        editing.save_day(cfg, DAY, intervals, passthrough)

        events = raw_events(cfg)
        assert [e["type"] for e in events] == ["start", "stop", "start", "stop"]
        assert events[1]["ts"] == when(9, 45).isoformat()

    def test_ticket_is_rederived_from_edited_text(self, cfg):
        storage.append_start(cfg, "PROJ-1 oprava", ts=when(9, 0))
        storage.append_stop(cfg, ts=when(10, 0))
        intervals, passthrough = editing.load_day(cfg, DAY)
        intervals[0].text = "JINY-9 neco uplne jineho"

        editing.save_day(cfg, DAY, intervals, passthrough)

        assert raw_events(cfg)[0]["ticket"] == "JINY-9"

    def test_deleting_row_by_omitting_it(self, cfg):
        storage.append_start(cfg, "prvni", ts=when(9, 0))
        storage.append_start(cfg, "druha", ts=when(10, 0))
        storage.append_stop(cfg, ts=when(11, 0))
        intervals, passthrough = editing.load_day(cfg, DAY)

        editing.save_day(cfg, DAY, [intervals[0]], passthrough)

        reloaded, _ = editing.load_day(cfg, DAY)
        assert [(i.start, i.end, i.text) for i in reloaded] == [
            (when(9, 0), when(10, 0), "prvni")
        ]

    def test_moved_start_remaps_jira_sync_identity(self, cfg):
        storage.append_start(cfg, "PROJ-1 oprava", ts=when(9, 7))
        storage.append_stop(cfg, ts=when(10, 0))
        storage.append_jira_sync(cfg, DAY, "PROJ-1", 3180, "77", when(9, 7).isoformat())
        intervals, passthrough = editing.load_day(cfg, DAY)
        intervals[0].start = when(9, 0)

        editing.save_day(cfg, DAY, intervals, passthrough)

        items, _ = jira.pending_worklogs(cfg, DAY)
        assert items == []  # odeslany blok zustava odeslany i po posunu zacatku

    def test_note_timestamp_outside_interval_anchors_to_start(self, cfg):
        storage.append_start(cfg, "prace", ts=when(9, 0))
        storage.append_note(cfg, "pozdni poznamka", ts=when(9, 50))
        storage.append_stop(cfg, ts=when(10, 0))
        intervals, passthrough = editing.load_day(cfg, DAY)
        intervals[0].start = when(9, 55)  # poznamka by zustala pred zacatkem
        intervals[0].end = when(10, 0)

        editing.save_day(cfg, DAY, intervals, passthrough)

        reloaded, _ = editing.load_day(cfg, DAY)
        assert [text for _ts, text in reloaded[0].notes] == ["pozdni poznamka"]


class TestOutOfOrderRows:
    def test_rows_in_any_order_are_sorted_on_save(self, cfg):
        # "přidaný řádek na spodku" s ranním časem — pořadí v seznamu opačné
        rows = [
            EditedInterval(start=when(10, 0), end=when(11, 0), text="druha"),
            EditedInterval(start=when(9, 0), end=when(10, 0), text="prvni"),
        ]

        editing.save_day(cfg, DAY, rows, [])

        reloaded, _ = editing.load_day(cfg, DAY)
        assert [(i.start, i.text) for i in reloaded] == [
            (when(9, 0), "prvni"),
            (when(10, 0), "druha"),
        ]

    def test_gap_filling_row_added_out_of_order(self, cfg):
        storage.append_start(cfg, "rano", ts=when(9, 0))
        storage.append_stop(cfg, ts=when(9, 30))
        storage.append_start(cfg, "vecer", ts=when(11, 0))
        storage.append_stop(cfg, ts=when(12, 0))
        intervals, passthrough = editing.load_day(cfg, DAY)
        # vyplneni diry 9:30-11:00 novym radkem pridanym az nakonec
        intervals.append(EditedInterval(start=when(9, 30), end=when(11, 0), text="ZAP-1 dira"))

        editing.save_day(cfg, DAY, intervals, passthrough)

        reloaded, _ = editing.load_day(cfg, DAY)
        assert [i.text for i in reloaded] == ["rano", "ZAP-1 dira", "vecer"]
        assert reloaded[1].start == when(9, 30)
        assert reloaded[1].end == when(11, 0)

    def test_overlap_detected_regardless_of_row_order(self, cfg):
        rows = [
            EditedInterval(start=when(10, 0), end=when(11, 0), text="pozdejsi"),
            EditedInterval(start=when(9, 0), end=when(10, 30), text="drivejsi"),  # přesah do 10:30
        ]

        with pytest.raises(EditError, match="překrývá"):
            editing.save_day(cfg, DAY, rows, [])


class TestValidation:
    def base(self):
        return [
            EditedInterval(start=when(9, 0), end=when(10, 0), text="prvni"),
            EditedInterval(start=when(10, 0), end=when(11, 0), text="druha"),
        ]

    def test_overlap_is_rejected(self, cfg):
        rows = self.base()
        rows[1].start = when(9, 30)

        with pytest.raises(EditError, match="překrývá"):
            editing.save_day(cfg, DAY, rows, [])

    def test_end_before_start_is_rejected(self, cfg):
        rows = self.base()
        rows[0].end = when(8, 0)

        with pytest.raises(EditError, match="konec"):
            editing.save_day(cfg, DAY, rows, [])

    def test_empty_text_is_rejected(self, cfg):
        rows = self.base()
        rows[0].text = "  "

        with pytest.raises(EditError, match="prázdný"):
            editing.save_day(cfg, DAY, rows, [])

    def test_running_interval_only_last(self, cfg):
        rows = self.base()
        rows[0].end = None

        with pytest.raises(EditError, match="poslední"):
            editing.save_day(cfg, DAY, rows, [])

    def test_running_last_is_allowed(self, cfg):
        rows = self.base()
        rows[1].end = None

        editing.save_day(cfg, DAY, rows, [])

        reloaded, _ = editing.load_day(cfg, DAY)
        assert reloaded[1].end is None

    def test_time_on_other_day_is_rejected(self, cfg):
        rows = self.base()
        rows[0].start = rows[0].start - timedelta(days=1)

        with pytest.raises(EditError, match="v rámci dne"):
            editing.save_day(cfg, DAY, rows, [])


class TestHelpers:
    def test_parse_time_hmm(self):
        assert editing.parse_time("9:15", DAY, TZ) == when(9, 15)

    def test_parse_time_with_seconds(self):
        assert editing.parse_time("09:15:30", DAY, TZ) == when(9, 15, 30)

    def test_parse_time_invalid(self):
        with pytest.raises(EditError):
            editing.parse_time("devet", DAY, TZ)
        with pytest.raises(EditError):
            editing.parse_time("25:00", DAY, TZ)

    def test_format_time_drops_zero_seconds(self):
        assert editing.format_time(when(9, 5)) == "09:05"
        assert editing.format_time(when(9, 5, 30)) == "09:05:30"

    def test_notes_roundtrip(self):
        notes = [(when(9, 0), "prvni pozn"), (when(9, 30), "druha // neni oddelovac?")]

        joined = editing.join_notes(notes)

        assert editing.split_notes(joined) == ["prvni pozn", "druha", "neni oddelovac?"]

    def test_split_notes_ignores_empty_edges(self):
        assert editing.split_notes(" // jen jedna ") == ["jen jedna"]
        assert editing.split_notes("jen jedna // ") == ["jen jedna"]
        assert editing.split_notes("   ") == []

    def test_split_notes_keeps_urls_whole(self):
        assert editing.split_notes("https://x.net/browse/A-1 // pozn") == [
            "https://x.net/browse/A-1",
            "pozn",
        ]
