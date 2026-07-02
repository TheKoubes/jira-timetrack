from datetime import date, datetime, timedelta, timezone

import pytest

from timetrack import storage, summary
from timetrack.core import build_intervals

TZ = timezone(timedelta(hours=2))
DAY = date(2026, 6, 10)

PLAIN_CFG = {"rounding_minutes": 0, "rounding_mode": "nearest", "jira_base_url": ""}


def ts(hour, minute):
    return datetime(2026, 6, 10, hour, minute, tzinfo=TZ)


def start(hour, minute, text, ticket=None):
    event = {"ts": ts(hour, minute).isoformat(), "type": "start", "text": text}
    if ticket:
        event["ticket"] = ticket
    return event


def stop(hour, minute):
    return {"ts": ts(hour, minute).isoformat(), "type": "stop"}


class TestFormatDuration:
    def test_minutes_only(self):
        assert summary.format_duration(timedelta(minutes=25)) == "25 min"

    def test_hours_and_minutes(self):
        assert summary.format_duration(timedelta(hours=1, minutes=13)) == "1 h 13 min"

    def test_whole_hours_keep_zero_minutes(self):
        assert summary.format_duration(timedelta(hours=2)) == "2 h 0 min"

    def test_zero(self):
        assert summary.format_duration(timedelta(0)) == "0 min"

    def test_seconds_round_to_nearest_minute(self):
        assert summary.format_duration(timedelta(minutes=4, seconds=40)) == "5 min"


class TestRenderMarkdown:
    def test_contains_title_with_date(self):
        text = summary.render_markdown(DAY, [], now=ts(18, 0), cfg=PLAIN_CFG)

        assert "# Pracovní den 2026-06-10" in text

    def test_empty_day_has_no_records_message(self):
        text = summary.render_markdown(DAY, [], now=ts(18, 0), cfg=PLAIN_CFG)

        assert "Žádné záznamy" in text

    def test_timeline_lists_intervals_chronologically(self):
        intervals = build_intervals([
            start(8, 2, "PROJ-123 oprava loginu", ticket="PROJ-123"),
            start(9, 15, "standup"),
            stop(9, 40),
        ])

        text = summary.render_markdown(DAY, intervals, now=ts(18, 0), cfg=PLAIN_CFG)

        assert "08:02–09:15" in text
        assert "1 h 13 min" in text
        assert "PROJ-123 oprava loginu" in text
        assert "09:15–09:40" in text

    def test_aggregates_by_activity_and_ticket(self):
        intervals = build_intervals([
            start(9, 0, "PROJ-1 vyvoj", ticket="PROJ-1"),
            start(10, 0, "standup"),
            start(10, 15, "PROJ-1 vyvoj", ticket="PROJ-1"),
            stop(11, 0),
        ])

        text = summary.render_markdown(DAY, intervals, now=ts(18, 0), cfg=PLAIN_CFG)

        assert "| PROJ-1 vyvoj | PROJ-1 | 1 h 45 min |" in text
        assert "| standup |  | 15 min |" in text
        assert "| PROJ-1 | 1 h 45 min |" in text
        assert "Celkem odpracováno: 2 h 0 min" in text

    def test_running_activity_today_is_counted_to_now_and_marked(self):
        intervals = build_intervals([start(14, 0, "bezici prace")])

        text = summary.render_markdown(DAY, intervals, now=ts(14, 45), cfg=PLAIN_CFG)

        assert "(běží)" in text
        assert "Celkem odpracováno: 45 min" in text

    def test_unclosed_activity_on_past_day_is_excluded_and_flagged(self):
        intervals = build_intervals([
            start(9, 0, "rano"),
            stop(10, 0),
            start(16, 0, "zapomenuta"),
        ])
        next_day_evening = datetime(2026, 6, 11, 20, 0, tzinfo=TZ)

        text = summary.render_markdown(DAY, intervals, now=next_day_evening, cfg=PLAIN_CFG)

        assert "(neukončeno)" in text
        assert "Celkem odpracováno: 1 h 0 min" in text


class TestRounding:
    CFG = {"rounding_minutes": 15, "rounding_mode": "nearest", "jira_base_url": ""}

    def test_table_totals_are_rounded(self):
        intervals = build_intervals([
            start(9, 0, "DEMOERP-1 vyvoj", ticket="DEMOERP-1"),
            start(9, 20, "porada"),  # vyvoj: 20 min -> 15 min
            stop(9, 45),  # porada: 25 min -> 30 min
        ])

        text = summary.render_markdown(DAY, intervals, now=ts(18, 0), cfg=self.CFG)

        assert "| DEMOERP-1 vyvoj | DEMOERP-1 | 15 min |" in text
        assert "| porada |  | 30 min |" in text
        assert "| DEMOERP-1 | 15 min |" in text

    def test_total_shows_exact_value_when_rounding_changes_it(self):
        intervals = build_intervals([start(9, 0, "prace"), stop(9, 38)])

        text = summary.render_markdown(DAY, intervals, now=ts(18, 0), cfg=self.CFG)

        assert "Celkem odpracováno: 45 min (přesně 38 min)" in text

    def test_total_without_parentheses_when_already_exact(self):
        intervals = build_intervals([start(9, 0, "prace"), stop(9, 45)])

        text = summary.render_markdown(DAY, intervals, now=ts(18, 0), cfg=self.CFG)

        assert "Celkem odpracováno: 45 min**" in text
        assert "přesně" not in text

    def test_no_parentheses_when_rounded_and_exact_display_the_same(self):
        # 14 min 31 s exactly; rounds to 15 min, but the exact value also
        # displays as "15 min" — the parenthesis would just repeat it.
        end = {"ts": "2026-06-10T09:14:31+02:00", "type": "stop"}
        intervals = build_intervals([start(9, 0, "prace"), end])

        text = summary.render_markdown(DAY, intervals, now=ts(18, 0), cfg=self.CFG)

        assert "Celkem odpracováno: 15 min**" in text
        assert "přesně" not in text

    def test_timeline_stays_exact(self):
        intervals = build_intervals([start(9, 0, "prace"), stop(9, 38)])

        text = summary.render_markdown(DAY, intervals, now=ts(18, 0), cfg=self.CFG)

        assert "- 09:00–09:38  (38 min)  prace" in text

    def test_mode_up_from_config(self):
        cfg = dict(self.CFG, rounding_mode="up")
        intervals = build_intervals([start(9, 0, "prace"), stop(9, 16)])

        text = summary.render_markdown(DAY, intervals, now=ts(18, 0), cfg=cfg)

        assert "Celkem odpracováno: 30 min (přesně 16 min)" in text


class TestRoundTimes:
    CFG = {
        "rounding_minutes": 15,
        "rounding_mode": "nearest",
        "round_times": True,
        "jira_base_url": "",
    }

    def test_timeline_boundaries_are_rounded(self):
        intervals = build_intervals([start(9, 7, "prace"), stop(9, 52)])

        text = summary.render_markdown(DAY, intervals, now=ts(18, 0), cfg=self.CFG)

        assert "- 09:00–09:45  (45 min)  prace" in text

    def test_contiguous_activities_stay_contiguous(self):
        intervals = build_intervals([
            start(9, 7, "prvni"),
            start(9, 22, "druha"),
            stop(9, 52),
        ])

        text = summary.render_markdown(DAY, intervals, now=ts(18, 0), cfg=self.CFG)

        assert "- 09:00–09:15  (15 min)  prvni" in text
        assert "- 09:15–09:45  (30 min)  druha" in text

    def test_totals_follow_rounded_timeline_with_exact_in_parens(self):
        intervals = build_intervals([start(9, 7, "prace"), stop(9, 38)])

        text = summary.render_markdown(DAY, intervals, now=ts(18, 0), cfg=self.CFG)

        # 9:07–9:38 -> 9:00–9:45; součty sedí na osu, závorka ukazuje realitu
        assert "| prace |  | 45 min |" in text
        assert "Celkem odpracováno: 45 min (přesně 31 min)" in text

    def test_short_activity_shows_as_zero_in_timeline(self):
        intervals = build_intervals([start(10, 2, "kratka"), stop(10, 7)])

        text = summary.render_markdown(DAY, intervals, now=ts(18, 0), cfg=self.CFG)

        assert "- 10:00–10:00  (0 min)  kratka" in text


class TestJiraLinks:
    CFG = {
        "rounding_minutes": 0,
        "rounding_mode": "nearest",
        "jira_base_url": "https://firma.atlassian.net/browse/",
    }

    def test_tickets_become_links_in_both_tables(self):
        intervals = build_intervals([
            start(9, 0, "DEMOERP-1215 oprava", ticket="DEMOERP-1215"),
            stop(10, 0),
        ])

        text = summary.render_markdown(DAY, intervals, now=ts(18, 0), cfg=self.CFG)

        link = "[DEMOERP-1215](https://firma.atlassian.net/browse/DEMOERP-1215)"
        assert f"| DEMOERP-1215 oprava | {link} | 1 h 0 min |" in text
        assert f"| {link} | 1 h 0 min |" in text

    def test_base_url_without_trailing_slash(self):
        cfg = dict(self.CFG, jira_base_url="https://firma.atlassian.net/browse")
        intervals = build_intervals([start(9, 0, "DEMOERP-9 x", ticket="DEMOERP-9"), stop(10, 0)])

        text = summary.render_markdown(DAY, intervals, now=ts(18, 0), cfg=cfg)

        assert "[DEMOERP-9](https://firma.atlassian.net/browse/DEMOERP-9)" in text

    def test_empty_base_url_keeps_plain_ticket(self):
        cfg = dict(self.CFG, jira_base_url="")
        intervals = build_intervals([start(9, 0, "DEMOERP-9 x", ticket="DEMOERP-9"), stop(10, 0)])

        text = summary.render_markdown(DAY, intervals, now=ts(18, 0), cfg=cfg)

        assert "[DEMOERP-9]" not in text
        assert "| DEMOERP-9 x | DEMOERP-9 |" in text


class TestNotesRendering:
    def test_notes_appear_as_nested_bullets_under_timeline_line(self):
        event = start(9, 0, "DEMOERP-1 oprava", ticket="DEMOERP-1")
        event["note"] = "cekal jsem na build"
        note_event = {"ts": ts(9, 30).isoformat(), "type": "note", "text": "pak jeste review"}
        intervals = build_intervals([event, note_event, stop(10, 0)])

        text = summary.render_markdown(DAY, intervals, now=ts(18, 0), cfg=PLAIN_CFG)

        lines = text.splitlines()
        timeline_idx = lines.index("- 09:00–10:00  (1 h 0 min)  DEMOERP-1 oprava")
        assert lines[timeline_idx + 1] == "  - pozn.: cekal jsem na build"
        assert lines[timeline_idx + 2] == "  - pozn.: pak jeste review"


def day_ts(day, hour, minute):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


def day_start(day, hour, minute, text, ticket=None):
    event = {"ts": day_ts(day, hour, minute).isoformat(), "type": "start", "text": text}
    if ticket:
        event["ticket"] = ticket
    return event


def day_stop(day, hour, minute):
    return {"ts": day_ts(day, hour, minute).isoformat(), "type": "stop"}


class TestRenderWeekMarkdown:
    # ISO tyden 24/2026: Po 8. 6. az Ne 14. 6.
    WEEK = [date(2026, 6, 8 + i) for i in range(7)]
    NOW = datetime(2026, 6, 14, 20, 0, tzinfo=TZ)

    def render(self, intervals_by_day, cfg=PLAIN_CFG, now=None):
        return summary.render_week_markdown(
            self.WEEK, intervals_by_day, now=now or self.NOW, cfg=cfg
        )

    def day_intervals(self, day, *events):
        return build_intervals(list(events))

    def test_title_with_week_number_and_date_range(self):
        text = self.render({})

        assert "# Týden 2026-W24 (8. 6. – 14. 6. 2026)" in text

    def test_empty_week_has_no_records_message(self):
        assert "Žádné záznamy" in self.render({})

    def test_per_day_table_lists_only_days_with_records(self):
        monday, wednesday = self.WEEK[0], self.WEEK[2]
        intervals_by_day = {
            monday: build_intervals(
                [day_start(monday, 9, 0, "prace"), day_stop(monday, 10, 0)]
            ),
            wednesday: build_intervals(
                [day_start(wednesday, 9, 0, "prace"), day_stop(wednesday, 11, 30)]
            ),
        }

        text = self.render(intervals_by_day)

        assert "| Po | 2026-06-08 | 1 h 0 min |" in text
        assert "| St | 2026-06-10 | 2 h 30 min |" in text
        assert "| Út |" not in text

    def test_aggregates_same_activity_across_days(self):
        monday, tuesday = self.WEEK[0], self.WEEK[1]
        intervals_by_day = {
            monday: build_intervals(
                [day_start(monday, 9, 0, "Z-1 vyvoj", ticket="Z-1"), day_stop(monday, 10, 0)]
            ),
            tuesday: build_intervals(
                [day_start(tuesday, 13, 0, "Z-1 vyvoj", ticket="Z-1"), day_stop(tuesday, 15, 0)]
            ),
        }

        text = self.render(intervals_by_day)

        assert "| Z-1 vyvoj | Z-1 | 3 h 0 min |" in text
        assert "| Z-1 | 3 h 0 min |" in text
        assert "**Celkem za týden: 3 h 0 min**" in text

    def test_rounding_from_config_with_exact_total(self):
        cfg = {"rounding_minutes": 15, "rounding_mode": "nearest", "jira_base_url": ""}
        monday = self.WEEK[0]
        intervals_by_day = {
            monday: build_intervals([day_start(monday, 9, 0, "prace"), day_stop(monday, 9, 38)])
        }

        text = self.render(intervals_by_day, cfg=cfg)

        assert "| Po | 2026-06-08 | 45 min |" in text
        assert "**Celkem za týden: 45 min (přesně 38 min)**" in text

    def test_ticket_links_from_config(self):
        cfg = dict(PLAIN_CFG, jira_base_url="https://firma.atlassian.net/browse/")
        monday = self.WEEK[0]
        intervals_by_day = {
            monday: build_intervals(
                [day_start(monday, 9, 0, "Z-9 x", ticket="Z-9"), day_stop(monday, 10, 0)]
            )
        }

        text = self.render(intervals_by_day, cfg=cfg)

        assert "[Z-9](https://firma.atlassian.net/browse/Z-9)" in text

    def test_unclosed_activity_on_past_day_warns_and_is_excluded(self):
        monday = self.WEEK[0]
        intervals_by_day = {
            monday: build_intervals([
                day_start(monday, 9, 0, "rano"),
                day_stop(monday, 10, 0),
                day_start(monday, 16, 0, "zapomenuta"),
            ])
        }

        text = self.render(intervals_by_day)

        assert "2026-06-08: neukončená aktivita" in text
        assert "**Celkem za týden: 1 h 0 min**" in text

    def test_running_activity_today_counts_to_now(self):
        sunday = self.WEEK[6]
        intervals_by_day = {
            sunday: build_intervals([day_start(sunday, 19, 0, "vecerni prace")])
        }

        text = self.render(intervals_by_day, now=day_ts(sunday, 19, 30))

        assert "**Celkem za týden: 30 min**" in text


def test_write_week_summary_collects_whole_week(tmp_path):
    cfg = {
        "data_dir": str(tmp_path),
        "filename_format": "%Y-%m-%d.jsonl",
        "summary_filename_format": "%Y-%m-%d-summary.md",
        "week_summary_filename_format": "%G-W%V-summary.md",
        "rounding_minutes": 0,
        "rounding_mode": "nearest",
        "jira_base_url": "",
    }
    monday, friday = date(2026, 6, 8), date(2026, 6, 12)
    storage.append_start(cfg, "Z-1 pondelni", ts=day_ts(monday, 9, 0))
    storage.append_stop(cfg, ts=day_ts(monday, 10, 0))
    storage.append_start(cfg, "patecni", ts=day_ts(friday, 14, 0))
    storage.append_stop(cfg, ts=day_ts(friday, 15, 0))

    path = summary.write_week_summary(cfg, date(2026, 6, 10), now=day_ts(friday, 18, 0))

    assert path.name == "2026-W24-summary.md"
    content = path.read_text(encoding="utf-8")
    assert "Z-1 pondelni" in content
    assert "patecni" in content
    assert "Celkem za týden: 2 h 0 min" in content


def test_write_summary_creates_markdown_file(tmp_path):
    cfg = {
        "data_dir": str(tmp_path),
        "filename_format": "%Y-%m-%d.jsonl",
        "summary_filename_format": "%Y-%m-%d-summary.md",
        "hotkey": "ctrl+alt+t",
    }
    storage.append_start(cfg, "PROJ-9 analyza", ts=ts(9, 0))
    storage.append_stop(cfg, ts=ts(10, 30))

    path = summary.write_summary(cfg, DAY, now=ts(18, 0))

    assert path.name == "2026-06-10-summary.md"
    content = path.read_text(encoding="utf-8")
    assert "PROJ-9 analyza" in content
    assert "1 h 30 min" in content
