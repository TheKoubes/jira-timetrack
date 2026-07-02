"""Append-only JSONL event storage, one file per day."""

import json
import os
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from timetrack.core import extract_ticket, normalize_jira_urls, split_note


def day_file_path(cfg: dict, day: date) -> Path:
    return Path(cfg["data_dir"]) / day.strftime(cfg["filename_format"])


def append_start(cfg: dict, text: str, ts: datetime | None = None) -> dict:
    # Pasted Jira URLs collapse to the issue key — the key in the text IS the
    # ticket reference, no link note is kept (the URL derives from config).
    text, _links = normalize_jira_urls(text)
    activity, note = split_note(text)
    event = {"ts": _timestamp(ts), "type": "start", "text": activity}
    ticket = extract_ticket(activity)
    if ticket:
        event["ticket"] = ticket
    if note:
        event["note"] = note
    _append(cfg, event)
    return event


def append_note(cfg: dict, text: str, ts: datetime | None = None) -> dict:
    event = {"ts": _timestamp(ts), "type": "note", "text": text}
    _append(cfg, event)
    return event


def append_stop(cfg: dict, ts: datetime | None = None) -> dict:
    event = {"ts": _timestamp(ts), "type": "stop"}
    _append(cfg, event)
    return event


def append_ticket(cfg: dict, text: str, ts: datetime | None = None) -> dict:
    """Attach a later-discovered ticket (key or pasted URL) to the last activity."""
    text, _links = normalize_jira_urls(text)
    ticket = extract_ticket(text)
    if not ticket:
        raise ValueError(f"V zadání {text!r} není klíč ticketu ani odkaz na něj.")
    event = {"ts": _timestamp(ts), "type": "ticket", "ticket": ticket}
    _append(cfg, event)
    return event


def append_jira_sync(
    cfg: dict,
    day: date,
    ticket: str,
    seconds: int,
    worklog_id: str,
    start_ts: str,
    ts: datetime | None = None,
    source: str = "jira",
    comment: str = "",
) -> dict:
    """Record that a block of *ticket* was written to Jira as *worklog_id*.

    ``start_ts`` is the exact start of the block's first interval and serves
    as its identity for "already sent" checks; ``source`` says which API
    created the worklog ("jira" or "tempo") so deletion can use the same one;
    ``comment`` is remembered so it can be shown and re-offered after a delete.
    The event goes into *day*'s file — the day the time belongs to — even when
    the sync happens later, so the day file stays self-contained.
    """
    event = {
        "ts": _timestamp(ts),
        "type": "jira_sync",
        "ticket": ticket,
        "seconds": seconds,
        "worklog_id": worklog_id,
        "start_ts": start_ts,
        "worklog_source": source,
    }
    if comment:
        event["comment"] = comment
    _append_line(day_file_path(cfg, day), event)
    return event


def append_jira_unsync(
    cfg: dict, day: date, ticket: str, worklog_id: str, start_ts: str, ts: datetime | None = None
) -> dict:
    """Record that the worklog of block *start_ts* was deleted from Jira again."""
    event = {
        "ts": _timestamp(ts),
        "type": "jira_unsync",
        "ticket": ticket,
        "worklog_id": worklog_id,
        "start_ts": start_ts,
    }
    _append_line(day_file_path(cfg, day), event)
    return event


def rewrite_day(cfg: dict, day: date, events: list[dict]) -> Path:
    """Replace *day*'s file with *events* — the one exception to append-only.

    Used by the record editor. The previous content is kept as ``.bak`` and
    the new file is written to a temp path first, so a crash mid-write can
    never leave a half-written day behind.
    """
    path = day_file_path(cfg, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )
    os.replace(tmp, path)
    return path


def read_day_events(cfg: dict, day: date) -> list[dict]:
    path = day_file_path(cfg, day)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def recent_tickets(cfg: dict, days: int = 60, today: date | None = None) -> list[str]:
    """Distinct ticket keys used in the last *days* days, most-recent-first.

    Feeds the popup's ticket autocomplete; reads any event carrying a
    ``ticket`` (start, ticket, jira_sync …), so a key offered is one really
    worked on.
    """
    today = today or date.today()
    latest: dict[str, str] = {}
    for offset in range(days):
        for event in read_day_events(cfg, today - timedelta(days=offset)):
            ticket = event.get("ticket")
            if ticket:
                ts = event.get("ts", "")
                if ticket not in latest or ts > latest[ticket]:
                    latest[ticket] = ts
    return [t for t, _ in sorted(latest.items(), key=lambda kv: kv[1], reverse=True)]


def _timestamp(ts: datetime | None) -> str:
    when = ts or datetime.now().astimezone()
    return when.isoformat(timespec="seconds")


def _append(cfg: dict, event: dict) -> None:
    day = datetime.fromisoformat(event["ts"]).date()
    _append_line(day_file_path(cfg, day), event)


def _append_line(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as f:
        # A hand edit can leave the file without a trailing newline; appending
        # right after it would glue two records onto one unparseable line.
        f.seek(0, 2)
        if f.tell() > 0:
            f.seek(-1, 2)
            if f.read(1) != b"\n":
                f.write(b"\n")
        f.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
        f.flush()
