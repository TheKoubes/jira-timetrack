"""Editing a day's records: load, validate and rewrite the event file.

The editor works on whole intervals (start, end, text, notes) and the day
file is regenerated from them on save — adjacent intervals share their
boundary timestamp, a gap gets an explicit ``stop``. ``jira_sync`` and any
unknown events pass through untouched; when an interval's start moves, the
``start_ts`` references in ``jira_sync`` events move with it, so already
sent blocks are not offered again.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo

from timetrack import storage
from timetrack.core import extract_ticket

NOTES_SEPARATOR = " // "
_NOTES_SPLIT_RE = re.compile(r"\s//\s*")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


class EditError(Exception):
    """User-presentable problem with an edit."""


@dataclass
class EditedInterval:
    start: datetime
    end: datetime | None  # None = activity is still running
    text: str
    notes: list[tuple[datetime, str]] = field(default_factory=list)
    original_start: datetime | None = None  # identity before the edit


def load_day(cfg: dict, day: date) -> tuple[list[EditedInterval], list[dict]]:
    """Read *day* as editable intervals plus events to pass through unchanged."""
    ordered = sorted(storage.read_day_events(cfg, day), key=lambda e: e["ts"])
    intervals: list[EditedInterval] = []
    passthrough: list[dict] = []
    for event in ordered:
        etype = event["type"]
        if etype == "note":
            if intervals:
                intervals[-1].notes.append((datetime.fromisoformat(event["ts"]), event["text"]))
            else:
                passthrough.append(event)
            continue
        if etype == "ticket":
            # The key joins the activity text; serialization re-derives the
            # ticket from it, so the event itself is normalized away.
            if intervals:
                if event["ticket"] not in intervals[-1].text:
                    intervals[-1].text = f"{event['ticket']} {intervals[-1].text}"
            else:
                passthrough.append(event)
            continue
        if etype not in ("start", "stop"):
            passthrough.append(event)
            continue
        ts = datetime.fromisoformat(event["ts"])
        if intervals and intervals[-1].end is None:
            intervals[-1].end = ts
        if etype == "start":
            interval = EditedInterval(start=ts, end=None, text=event["text"], original_start=ts)
            if event.get("note"):
                interval.notes.append((ts, event["note"]))
            intervals.append(interval)
    return intervals, passthrough


def save_day(cfg: dict, day: date, intervals: list[EditedInterval], passthrough: list[dict]):
    """Validate *intervals* and rewrite *day*'s file (previous content → .bak).

    Rows may arrive in any order (the editor lets you add a row at the bottom
    with an earlier time); they are sorted by start before validation and
    serialization so the timeline and overlap checks are correct.
    """
    intervals = sorted(intervals, key=lambda i: i.start)
    _validate(day, intervals)
    events = _serialize(intervals)
    remap = {
        interval.original_start.isoformat(): interval.start.isoformat()
        for interval in intervals
        if interval.original_start and interval.original_start != interval.start
    }
    for event in passthrough:
        if event.get("type") == "jira_sync" and event.get("start_ts") in remap:
            event = {**event, "start_ts": remap[event["start_ts"]]}
        events.append(event)
    events.sort(key=lambda e: e["ts"])
    return storage.rewrite_day(cfg, day, events)


def parse_time(text: str, day: date, tz: tzinfo | None) -> datetime:
    """Parse ``H:MM`` or ``H:MM:SS`` into a datetime on *day* in *tz*."""
    match = _TIME_RE.match(text.strip())
    if not match:
        raise EditError(f"Neplatný čas {text.strip()!r} — čekám H:MM nebo H:MM:SS.")
    hour, minute, second = int(match[1]), int(match[2]), int(match[3] or 0)
    if hour > 23 or minute > 59 or second > 59:
        raise EditError(f"Neplatný čas {text.strip()!r}.")
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=tz)


def format_time(dt: datetime) -> str:
    return dt.strftime("%H:%M:%S") if dt.second else dt.strftime("%H:%M")


def join_notes(notes: list[tuple[datetime, str]]) -> str:
    return NOTES_SEPARATOR.join(text for _ts, text in notes)


def split_notes(text: str) -> list[str]:
    return [part.strip() for part in _NOTES_SPLIT_RE.split(text) if part.strip()]


def _validate(day: date, intervals: list[EditedInterval]) -> None:
    """Validate *intervals* (must be sorted by start). Errors name the activity.

    Row numbers would be misleading once rows are sorted, so messages refer to
    the activity text and time instead.
    """
    previous = None
    for interval in intervals:
        label = interval.text.strip()
        if not label:
            raise EditError(f"Aktivita v {format_time(interval.start)} má prázdný název.")
        if interval.start.date() != day:
            raise EditError(f"„{label}“: čas musí zůstat v rámci dne {day.isoformat()}.")
        if interval.end is None:
            if interval is not intervals[-1]:
                raise EditError(f"„{label}“: bez konce smí být jen poslední aktivita dne.")
        else:
            if interval.end.date() != day:
                raise EditError(f"„{label}“: čas musí zůstat v rámci dne {day.isoformat()}.")
            if interval.end <= interval.start:
                raise EditError(f"„{label}“: konec musí být po začátku.")
        if previous is not None and previous.end is not None and interval.start < previous.end:
            raise EditError(
                f"„{label}“ ({format_time(interval.start)}) se překrývá s „{previous.text.strip()}“"
                f" (do {format_time(previous.end)})."
            )
        previous = interval
    return None


def _serialize(intervals: list[EditedInterval]) -> list[dict]:
    events: list[dict] = []
    for index, interval in enumerate(intervals):
        next_start = intervals[index + 1].start if index + 1 < len(intervals) else None
        event = {"ts": _iso(interval.start), "type": "start", "text": interval.text}
        ticket = extract_ticket(interval.text)
        if ticket:
            event["ticket"] = ticket
        events.append(event)
        for note_ts, note_text in interval.notes:
            # A note belongs to the interval it is listed under; if its
            # original timestamp no longer falls inside, anchor it to the start.
            if note_ts < interval.start or (next_start and note_ts >= next_start):
                note_ts = interval.start
            events.append({"ts": _iso(note_ts), "type": "note", "text": note_text})
        if interval.end is not None and interval.end != next_start:
            events.append({"ts": _iso(interval.end), "type": "stop"})
    return events


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")
