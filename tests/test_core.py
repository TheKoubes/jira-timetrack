from datetime import datetime, timedelta, timezone

from timetrack import core

TZ = timezone(timedelta(hours=2))


def ts(hour, minute):
    return datetime(2026, 6, 10, hour, minute, tzinfo=TZ)


def start(hour, minute, text, ticket=None):
    event = {"ts": ts(hour, minute).isoformat(), "type": "start", "text": text}
    if ticket:
        event["ticket"] = ticket
    return event


def stop(hour, minute):
    return {"ts": ts(hour, minute).isoformat(), "type": "stop"}


def note(hour, minute, text):
    return {"ts": ts(hour, minute).isoformat(), "type": "note", "text": text}


class TestExtractTicket:
    def test_finds_ticket_at_start_of_text(self):
        assert core.extract_ticket("PROJ-123 oprava loginu") == "PROJ-123"

    def test_finds_ticket_inside_text(self):
        assert core.extract_ticket("oprava loginu ABC2-99") == "ABC2-99"

    def test_returns_none_without_ticket(self):
        assert core.extract_ticket("standup s tymem") is None

    def test_ignores_lowercase(self):
        assert core.extract_ticket("proj-123 neco") is None

    def test_returns_first_of_multiple(self):
        assert core.extract_ticket("ABC-1 souvisi s DEF-2") == "ABC-1"

    def test_finds_digit_leading_key(self):
        # některé instance mají klíče začínající číslicí (sebevzdělávací požadavek)
        assert core.extract_ticket("19ABC0100000007-24 sebevzdelavani") == "19ABC0100000007-24"

    def test_ignores_plain_number_range(self):
        assert core.extract_ticket("schuzka 123-45 minut") is None

    def test_requires_uppercase_letter_in_key(self):
        assert core.extract_ticket("9999-1 jen cisla") is None


class TestBuildIntervals:
    def test_empty_events_give_no_intervals(self):
        assert core.build_intervals([]) == []

    def test_start_is_closed_by_next_start(self):
        events = [
            start(9, 0, "PROJ-1 prvni", ticket="PROJ-1"),
            start(9, 30, "druha"),
            stop(10, 0),
        ]

        intervals = core.build_intervals(events)

        assert len(intervals) == 2
        assert intervals[0].text == "PROJ-1 prvni"
        assert intervals[0].ticket == "PROJ-1"
        assert intervals[0].start == ts(9, 0)
        assert intervals[0].end == ts(9, 30)
        assert intervals[1].text == "druha"
        assert intervals[1].ticket is None
        assert intervals[1].end == ts(10, 0)

    def test_last_start_without_stop_is_running(self):
        intervals = core.build_intervals([start(14, 0, "bezici")])

        assert len(intervals) == 1
        assert intervals[0].end is None
        assert intervals[0].is_running

    def test_stop_without_running_activity_is_ignored(self):
        assert core.build_intervals([stop(9, 0)]) == []

    def test_events_are_sorted_by_timestamp(self):
        events = [start(10, 0, "pozdejsi"), start(9, 0, "drivejsi")]

        intervals = core.build_intervals(events)

        assert [i.text for i in intervals] == ["drivejsi", "pozdejsi"]
        assert intervals[0].end == ts(10, 0)

    def test_duration_of_running_interval_counts_to_now(self):
        intervals = core.build_intervals([start(14, 0, "bezici")])

        assert intervals[0].duration(now=ts(14, 45)) == timedelta(minutes=45)

    def test_duration_of_closed_interval_ignores_now(self):
        events = [start(9, 0, "hotova"), stop(9, 30)]

        intervals = core.build_intervals(events)

        assert intervals[0].duration(now=ts(18, 0)) == timedelta(minutes=30)

    def test_ticket_event_attaches_to_running_interval(self):
        ticket_event = {"ts": ts(9, 30).isoformat(), "type": "ticket", "ticket": "DEMOERP-9"}
        events = [start(9, 0, "obnova databazi"), ticket_event, stop(10, 0)]

        intervals = core.build_intervals(events)

        assert len(intervals) == 1
        assert intervals[0].ticket == "DEMOERP-9"
        assert intervals[0].text == "DEMOERP-9 obnova databazi"
        assert intervals[0].end == ts(10, 0)

    def test_ticket_event_does_not_duplicate_key_in_text(self):
        ticket_event = {"ts": ts(9, 30).isoformat(), "type": "ticket", "ticket": "DEMOERP-9"}
        events = [start(9, 0, "DEMOERP-9 prace", ticket="DEMOERP-9"), ticket_event]

        intervals = core.build_intervals(events)

        assert intervals[0].text == "DEMOERP-9 prace"

    def test_ticket_event_before_any_start_is_ignored(self):
        ticket_event = {"ts": ts(8, 0).isoformat(), "type": "ticket", "ticket": "Z-1"}

        intervals = core.build_intervals([ticket_event, start(9, 0, "prace")])

        assert intervals[0].ticket is None

    def test_ticket_event_after_stop_attaches_to_last_interval(self):
        ticket_event = {"ts": ts(10, 5).isoformat(), "type": "ticket", "ticket": "Z-1"}
        events = [start(9, 0, "prace"), stop(10, 0), ticket_event]

        intervals = core.build_intervals(events)

        assert intervals[0].ticket == "Z-1"
        assert intervals[0].end == ts(10, 0)

    def test_unknown_event_type_does_not_close_running_interval(self):
        sync = {"ts": ts(9, 30).isoformat(), "type": "jira_sync", "ticket": "P-1", "seconds": 900}
        events = [start(9, 0, "prace"), sync]

        intervals = core.build_intervals(events)

        assert len(intervals) == 1
        assert intervals[0].is_running


class TestIsoWeekDays:
    def test_wednesday_gives_monday_to_sunday(self):
        from datetime import date

        days = core.iso_week_days(date(2026, 6, 10))  # streda, ISO tyden 24

        assert days[0] == date(2026, 6, 8)
        assert days[-1] == date(2026, 6, 14)
        assert len(days) == 7

    def test_monday_starts_its_own_week(self):
        from datetime import date

        days = core.iso_week_days(date(2026, 6, 8))

        assert days[0] == date(2026, 6, 8)

    def test_week_crossing_year_boundary(self):
        from datetime import date

        days = core.iso_week_days(date(2026, 1, 1))  # ctvrtek, ISO tyden 1

        assert days[0] == date(2025, 12, 29)
        assert days[-1] == date(2026, 1, 4)


class TestRoundDuration:
    def test_rounds_down_to_nearest(self):
        assert core.round_duration(timedelta(minutes=20), 15, "nearest") == timedelta(minutes=15)

    def test_rounds_up_to_nearest(self):
        assert core.round_duration(timedelta(minutes=25), 15, "nearest") == timedelta(minutes=30)

    def test_half_step_rounds_up(self):
        assert core.round_duration(
            timedelta(minutes=7, seconds=30), 15, "nearest"
        ) == timedelta(minutes=15)

    def test_mode_up_always_rounds_up(self):
        assert core.round_duration(timedelta(minutes=16), 15, "up") == timedelta(minutes=30)

    def test_mode_up_keeps_exact_multiple(self):
        assert core.round_duration(timedelta(minutes=30), 15, "up") == timedelta(minutes=30)

    def test_zero_minutes_disables_rounding(self):
        assert core.round_duration(timedelta(minutes=7), 0, "nearest") == timedelta(minutes=7)

    def test_zero_duration(self):
        assert core.round_duration(timedelta(0), 15, "up") == timedelta(0)


class TestRoundTime:
    def test_rounds_down_to_nearest_quarter(self):
        assert core.round_time(ts(9, 7), 15) == ts(9, 0)

    def test_rounds_up_to_nearest_quarter(self):
        assert core.round_time(ts(9, 8), 15) == ts(9, 15)

    def test_exact_multiple_stays(self):
        assert core.round_time(ts(9, 45), 15) == ts(9, 45)

    def test_zero_minutes_disables(self):
        assert core.round_time(ts(9, 7), 0) == ts(9, 7)


class TestRoundIntervals:
    def test_boundaries_round_and_stay_contiguous(self):
        events = [start(9, 7, "prvni"), start(9, 52, "druha"), stop(10, 16)]
        intervals = core.build_intervals(events)

        rounded = core.round_intervals(intervals, 15)

        assert rounded[0].start == ts(9, 0)
        assert rounded[0].end == ts(9, 45)
        assert rounded[1].start == ts(9, 45)  # sdílená hranice zůstává sdílená
        assert rounded[1].end == ts(10, 15)

    def test_short_interval_can_collapse_to_zero(self):
        intervals = core.build_intervals([start(10, 2, "kratka"), stop(10, 7)])

        rounded = core.round_intervals(intervals, 15)

        assert rounded[0].start == rounded[0].end == ts(10, 0)

    def test_running_interval_keeps_open_end(self):
        rounded = core.round_intervals(core.build_intervals([start(9, 7, "bezici")]), 15)

        assert rounded[0].start == ts(9, 0)
        assert rounded[0].is_running

    def test_zero_minutes_returns_originals(self):
        intervals = core.build_intervals([start(9, 7, "prace"), stop(9, 52)])

        assert core.round_intervals(intervals, 0) is intervals

    def test_originals_are_not_mutated(self):
        intervals = core.build_intervals([start(9, 7, "prace"), stop(9, 52)])

        core.round_intervals(intervals, 15)

        assert intervals[0].start == ts(9, 7)
        assert intervals[0].end == ts(9, 52)


class TestSplitNote:
    def test_splits_on_separator(self):
        assert core.split_note("DEMOERP-1 oprava // cekal jsem na build") == (
            "DEMOERP-1 oprava",
            "cekal jsem na build",
        )

    def test_no_separator_gives_no_note(self):
        assert core.split_note("jen aktivita") == ("jen aktivita", None)

    def test_empty_note_side_is_ignored(self):
        assert core.split_note("aktivita //") == ("aktivita //", None)

    def test_empty_activity_side_is_not_split(self):
        assert core.split_note("// jen poznamka") == ("// jen poznamka", None)

    def test_splits_on_first_separator_only(self):
        assert core.split_note("a // b // c") == ("a", "b // c")

    def test_url_double_slash_is_not_a_separator(self):
        text = "kontrola https://github.com/foo/bar"

        assert core.split_note(text) == (text, None)

    def test_note_after_url_still_splits(self):
        assert core.split_note("kontrola https://github.com/foo // moje poznamka") == (
            "kontrola https://github.com/foo",
            "moje poznamka",
        )


class TestNormalizeJiraUrls:
    def test_url_with_query_becomes_key_and_clean_link(self):
        url = (
            "https://firma.atlassian.net/browse/VEGAERP-861"
            "?actionerId=712020%3A5ac58504&sourceType=assign"
        )

        text, links = core.normalize_jira_urls(url)

        assert text == "VEGAERP-861"
        assert links == ["https://firma.atlassian.net/browse/VEGAERP-861"]

    def test_digit_leading_key_url(self):
        text, links = core.normalize_jira_urls(
            "https://firma.atlassian.net/browse/19ABC0100000007-24?focus=1"
        )

        assert text == "19ABC0100000007-24"
        assert links == ["https://firma.atlassian.net/browse/19ABC0100000007-24"]

    def test_clean_url_becomes_key_and_same_link(self):
        text, links = core.normalize_jira_urls(
            "https://firma.atlassian.net/browse/DEMOERP-1185"
        )

        assert text == "DEMOERP-1185"
        assert links == ["https://firma.atlassian.net/browse/DEMOERP-1185"]

    def test_url_with_extra_text_keeps_text(self):
        text, links = core.normalize_jira_urls(
            "https://firma.atlassian.net/browse/DEMOERP-1185 oprava prihlaseni"
        )

        assert text == "DEMOERP-1185 oprava prihlaseni"
        assert links == ["https://firma.atlassian.net/browse/DEMOERP-1185"]

    def test_text_without_url_is_unchanged(self):
        text, links = core.normalize_jira_urls("DEMOERP-1 obycejna aktivita")

        assert text == "DEMOERP-1 obycejna aktivita"
        assert links == []

    def test_non_jira_url_is_left_alone(self):
        original = "kontrola https://github.com/foo/bar"

        text, links = core.normalize_jira_urls(original)

        assert text == original
        assert links == []

    def test_two_urls_give_two_keys_and_links(self):
        text, links = core.normalize_jira_urls(
            "https://x.atlassian.net/browse/AB-1?q=1 a https://x.atlassian.net/browse/CD-2"
        )

        assert text == "AB-1 a CD-2"
        assert links == [
            "https://x.atlassian.net/browse/AB-1",
            "https://x.atlassian.net/browse/CD-2",
        ]


class TestIntervalNotes:
    def test_note_field_on_start_event_becomes_note(self):
        event = start(9, 0, "aktivita")
        event["note"] = "poznamka ze startu"

        intervals = core.build_intervals([event])

        assert intervals[0].notes == ["poznamka ze startu"]

    def test_note_event_attaches_to_running_interval(self):
        events = [start(9, 0, "prace"), note(9, 30, "cekam na build")]

        intervals = core.build_intervals(events)

        assert intervals[0].notes == ["cekam na build"]

    def test_note_event_does_not_close_running_interval(self):
        events = [start(9, 0, "prace"), note(9, 30, "pozn"), stop(10, 0)]

        intervals = core.build_intervals(events)

        assert len(intervals) == 1
        assert intervals[0].end == ts(10, 0)

    def test_note_after_stop_attaches_to_last_interval(self):
        events = [start(9, 0, "prace"), stop(10, 0), note(10, 5, "dodatek")]

        intervals = core.build_intervals(events)

        assert intervals[0].notes == ["dodatek"]

    def test_note_before_any_start_is_dropped(self):
        events = [note(8, 0, "do prazdna"), start(9, 0, "prace")]

        intervals = core.build_intervals(events)

        assert intervals[0].notes == []

    def test_notes_accumulate_in_order(self):
        event = start(9, 0, "prace")
        event["note"] = "prvni"
        events = [event, note(9, 15, "druha"), note(9, 30, "treti")]

        intervals = core.build_intervals(events)

        assert intervals[0].notes == ["prvni", "druha", "treti"]


class TestAggregate:
    def test_sums_same_text_across_interruptions(self):
        events = [
            start(9, 0, "PROJ-1 vyvoj", ticket="PROJ-1"),
            start(10, 0, "standup"),
            start(10, 15, "PROJ-1 vyvoj", ticket="PROJ-1"),
            stop(11, 0),
        ]
        intervals = core.build_intervals(events)

        by_activity, by_ticket, total = core.aggregate(intervals, now=ts(12, 0))

        assert by_activity["PROJ-1 vyvoj"] == timedelta(hours=1, minutes=45)
        assert by_activity["standup"] == timedelta(minutes=15)
        assert by_ticket == {"PROJ-1": timedelta(hours=1, minutes=45)}
        assert total == timedelta(hours=2)

    def test_running_interval_counts_to_now(self):
        intervals = core.build_intervals([start(14, 0, "bezici")])

        by_activity, _, total = core.aggregate(intervals, now=ts(14, 30))

        assert by_activity["bezici"] == timedelta(minutes=30)
        assert total == timedelta(minutes=30)

    def test_empty_intervals(self):
        by_activity, by_ticket, total = core.aggregate([], now=ts(12, 0))

        assert by_activity == {}
        assert by_ticket == {}
        assert total == timedelta(0)
