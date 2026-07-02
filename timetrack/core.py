"""Pure logic: Jira ticket extraction and deriving intervals from events."""

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

# A Jira issue key: a project key + "-" + number. The key may start with a
# digit (some instances use keys like "19ABC0100000007-24"), but must hold at
# least one uppercase letter so plain numbers ("123-45") are not mistaken for
# tickets.
_KEY = r"[A-Z0-9]*[A-Z][A-Z0-9]*-\d+"
TICKET_RE = re.compile(rf"\b{_KEY}\b")

# The separator counts only when preceded by whitespace, so the "//" inside
# a pasted URL (https://...) never splits the text.
NOTE_SEPARATOR_RE = re.compile(r"\s//")

JIRA_URL_RE = re.compile(rf"(https?://[^\s/]+)/browse/({_KEY})\S*")


def extract_ticket(text: str) -> str | None:
    """Return the first Jira issue key in *text* (e.g. ``PROJ-123``), or None."""
    match = TICKET_RE.search(text)
    return match.group(0) if match else None


def split_note(text: str) -> tuple[str, str | None]:
    """Split ``"aktivita // poznámka"`` into activity text and note.

    Without the separator (or with an empty side) the text stays whole.
    """
    match = NOTE_SEPARATOR_RE.search(text)
    if match:
        activity = text[: match.start()].strip()
        note = text[match.end() :].strip()
        if activity and note:
            return activity, note
    return text, None


def normalize_jira_urls(text: str) -> tuple[str, list[str]]:
    """Replace Jira issue URLs in *text* with their issue keys.

    Returns the cleaned text and the canonical links (query strings and
    other trailing parts dropped), e.g.
    ``"https://x.net/browse/A-1?focus=2"`` → ``("A-1", ["https://x.net/browse/A-1"])``.
    """
    links: list[str] = []

    def replace(match: re.Match) -> str:
        links.append(f"{match.group(1)}/browse/{match.group(2)}")
        return match.group(2)

    return JIRA_URL_RE.sub(replace, text), links


def iso_week_days(day: date) -> list[date]:
    """Return the seven dates (Monday–Sunday) of the ISO week containing *day*."""
    monday = day - timedelta(days=day.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


def round_duration(td: timedelta, minutes: int, mode: str) -> timedelta:
    """Round *td* to a multiple of *minutes* ("nearest" half-up, or "up").

    ``minutes <= 0`` disables rounding.
    """
    if minutes <= 0:
        return td
    step = minutes * 60
    if mode == "up":
        steps = math.ceil(td.total_seconds() / step)
    else:
        steps = math.floor(td.total_seconds() / step + 0.5)
    return timedelta(seconds=steps * step)


def round_time(dt: datetime, minutes: int) -> datetime:
    """Round *dt* to the nearest multiple of *minutes* within its day (0 = no-op)."""
    if minutes <= 0:
        return dt
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight + round_duration(dt - midnight, minutes, "nearest")


@dataclass
class Interval:
    start: datetime
    end: datetime | None  # None = activity is still running
    text: str
    ticket: str | None
    notes: list[str] = field(default_factory=list)

    @property
    def is_running(self) -> bool:
        return self.end is None

    def duration(self, now: datetime) -> timedelta:
        return (self.end or now) - self.start


def aggregate(
    intervals: list[Interval], now: datetime
) -> tuple[dict[str, timedelta], dict[str, timedelta], timedelta]:
    """Sum durations by activity text and by ticket; return also the day total.

    Running intervals are counted up to *now*.
    """
    by_activity: dict[str, timedelta] = {}
    by_ticket: dict[str, timedelta] = {}
    total = timedelta(0)
    for interval in intervals:
        duration = interval.duration(now)
        by_activity[interval.text] = by_activity.get(interval.text, timedelta(0)) + duration
        if interval.ticket:
            by_ticket[interval.ticket] = by_ticket.get(interval.ticket, timedelta(0)) + duration
        total += duration
    return by_activity, by_ticket, total


def round_intervals(intervals: list[Interval], minutes: int) -> list[Interval]:
    """Copies of *intervals* with boundaries rounded to multiples of *minutes*.

    Equal timestamps round equally, so a contiguous timeline stays contiguous
    and neighbours never overlap. An activity shorter than half a step can
    collapse to zero length; callers decide what to do with those.
    """
    if minutes <= 0:
        return intervals
    return [
        Interval(
            start=round_time(interval.start, minutes),
            end=None if interval.end is None else round_time(interval.end, minutes),
            text=interval.text,
            ticket=interval.ticket,
            notes=list(interval.notes),
        )
        for interval in intervals
    ]


def build_intervals(events: list[dict]) -> list[Interval]:
    """Derive activity intervals from an event log.

    Each ``start`` event runs until the next ``start`` or ``stop`` closes it;
    a trailing ``start`` without a following event is still running.
    ``note`` events attach to the latest interval without closing anything;
    ``ticket`` events attach a later-discovered ticket to it (the key also
    becomes part of the activity text). Events of any other type (e.g.
    ``jira_sync``) do not affect the timeline.
    """
    ordered = sorted(events, key=lambda e: e["ts"])
    intervals: list[Interval] = []
    for event in ordered:
        if event["type"] == "note":
            if intervals:
                intervals[-1].notes.append(event["text"])
            continue
        if event["type"] == "ticket":
            if intervals:
                interval = intervals[-1]
                interval.ticket = event["ticket"]
                if event["ticket"] not in interval.text:
                    interval.text = f"{event['ticket']} {interval.text}"
            continue
        if event["type"] not in ("start", "stop"):
            continue
        ts = datetime.fromisoformat(event["ts"])
        if intervals and intervals[-1].end is None:
            intervals[-1].end = ts
        if event["type"] == "start":
            notes = [event["note"]] if event.get("note") else []
            intervals.append(
                Interval(
                    start=ts,
                    end=None,
                    text=event["text"],
                    ticket=event.get("ticket"),
                    notes=notes,
                )
            )
    return intervals
