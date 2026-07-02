"""Rendering the daily and weekly summaries as Markdown."""

from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

from timetrack import storage
from timetrack.core import (
    Interval,
    aggregate,
    build_intervals,
    iso_week_days,
    round_duration,
    round_intervals,
)

DAY_NAMES = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]


def format_duration(td: timedelta) -> str:
    minutes = round(td.total_seconds() / 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min"


def render_markdown(day: date, intervals: list[Interval], now: datetime, cfg: dict) -> str:
    lines = [f"# Pracovní den {day.isoformat()}", ""]
    if not intervals:
        lines.append("Žádné záznamy.")
        return "\n".join(lines) + "\n"

    is_today = day == now.astimezone().date()
    display = _display_intervals(intervals, cfg)
    # An unclosed activity from a past day has no known end; counting it to
    # "now" would inflate the totals, so it is flagged and left out of them.
    countable = [i for i in display if not i.is_running or is_today]
    exact_countable = [i for i in intervals if not i.is_running or is_today]
    rounded = _rounded_formatter(cfg)

    lines.append("## Časová osa")
    for interval in display:
        lines.append(_timeline_line(interval, now, is_today))
        lines.extend(f"  - pozn.: {note}" for note in interval.notes)
    lines.append("")

    by_activity, by_ticket, total = aggregate(countable, now)
    _, _, exact_total = aggregate(exact_countable, now)
    lines.extend(_aggregate_tables(by_activity, by_ticket, display, rounded, cfg))
    lines.append(_total_line("Celkem odpracováno", total, exact_total, cfg))
    return "\n".join(lines) + "\n"


def render_week_markdown(
    days: list[date],
    intervals_by_day: dict[date, list[Interval]],
    now: datetime,
    cfg: dict,
) -> str:
    monday, sunday = days[0], days[-1]
    iso = monday.isocalendar()
    lines = [f"# Týden {iso.year}-W{iso.week:02d} ({_format_range(monday, sunday)})", ""]

    all_intervals = [i for d in days for i in intervals_by_day.get(d, [])]
    if not all_intervals:
        lines.append("Žádné záznamy.")
        return "\n".join(lines) + "\n"

    today = now.astimezone().date()
    rounded = _rounded_formatter(cfg)

    warnings = []
    countable_by_day: dict[date, list[Interval]] = {}
    exact_countable_by_day: dict[date, list[Interval]] = {}
    for d in days:
        intervals = intervals_by_day.get(d, [])
        display = _display_intervals(intervals, cfg)
        countable_by_day[d] = [i for i in display if not i.is_running or d == today]
        exact_countable_by_day[d] = [i for i in intervals if not i.is_running or d == today]
        if len(countable_by_day[d]) < len(display):
            warnings.append(f"⚠ {d.isoformat()}: neukončená aktivita — zkontroluj denní sumář.")

    lines.append("## Podle dnů")
    lines.append("| Den | Datum | Celkem |")
    lines.append("| --- | --- | --- |")
    for d in days:
        if not intervals_by_day.get(d):
            continue
        _, _, day_total = aggregate(countable_by_day[d], now)
        lines.append(f"| {DAY_NAMES[d.weekday()]} | {d.isoformat()} | {rounded(day_total)} |")
    lines.append("")

    if warnings:
        lines.extend(warnings)
        lines.append("")

    week_countable = [i for d in days for i in countable_by_day[d]]
    by_activity, by_ticket, total = aggregate(week_countable, now)
    _, _, exact_total = aggregate([i for d in days for i in exact_countable_by_day[d]], now)
    lines.extend(_aggregate_tables(by_activity, by_ticket, all_intervals, rounded, cfg))
    lines.append(_total_line("Celkem za týden", total, exact_total, cfg))
    return "\n".join(lines) + "\n"


def write_summary(cfg: dict, day: date, now: datetime | None = None) -> Path:
    """Build the summary for *day* from stored events and write it as Markdown."""
    now = now or datetime.now().astimezone()
    intervals = build_intervals(storage.read_day_events(cfg, day))
    text = render_markdown(day, intervals, now, cfg)
    return _write(cfg, day, cfg["summary_filename_format"], text)


def write_week_summary(cfg: dict, day: date, now: datetime | None = None) -> Path:
    """Build the summary for the ISO week containing *day* and write it as Markdown."""
    now = now or datetime.now().astimezone()
    days = iso_week_days(day)
    intervals_by_day = {d: build_intervals(storage.read_day_events(cfg, d)) for d in days}
    text = render_week_markdown(days, intervals_by_day, now, cfg)
    return _write(cfg, days[0], cfg["week_summary_filename_format"], text)


def _write(cfg: dict, day: date, filename_format: str, text: str) -> Path:
    path = Path(cfg["data_dir"]) / day.strftime(filename_format)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _rounded_formatter(cfg: dict) -> Callable[[timedelta], str]:
    minutes = cfg.get("rounding_minutes", 0)
    mode = cfg.get("rounding_mode", "nearest")
    return lambda td: format_duration(round_duration(td, minutes, mode))


def _display_intervals(intervals: list[Interval], cfg: dict) -> list[Interval]:
    """The intervals as the summary shows them: boundaries rounded if enabled."""
    if cfg.get("round_times"):
        return round_intervals(intervals, cfg.get("rounding_minutes", 0))
    return intervals


def _ticket_label(cfg: dict, ticket: str | None) -> str:
    if not ticket:
        return ""
    base_url = cfg.get("jira_base_url", "")
    if base_url:
        return f"[{ticket}]({base_url.rstrip('/')}/{ticket})"
    return ticket


def _aggregate_tables(
    by_activity: dict[str, timedelta],
    by_ticket: dict[str, timedelta],
    intervals: list[Interval],
    rounded: Callable[[timedelta], str],
    cfg: dict,
) -> list[str]:
    ticket_of = {i.text: i.ticket for i in intervals}
    lines = ["## Podle aktivit", "| Aktivita | Ticket | Celkem |", "| --- | --- | --- |"]
    for text, duration in by_activity.items():
        lines.append(f"| {text} | {_ticket_label(cfg, ticket_of[text])} | {rounded(duration)} |")
    lines.append("")
    if by_ticket:
        lines.append("## Podle ticketů (pro zápis do Jiry)")
        lines.append("| Ticket | Celkem |")
        lines.append("| --- | --- |")
        for ticket, duration in by_ticket.items():
            lines.append(f"| {_ticket_label(cfg, ticket)} | {rounded(duration)} |")
        lines.append("")
    return lines


def _total_line(label: str, total: timedelta, exact_total: timedelta, cfg: dict) -> str:
    rounded = _rounded_formatter(cfg)(total)
    exact = format_duration(exact_total)
    if rounded != exact:
        return f"**{label}: {rounded} (přesně {exact})**"
    return f"**{label}: {rounded}**"


def _format_range(first: date, last: date) -> str:
    if first.year == last.year:
        return f"{first.day}. {first.month}. – {last.day}. {last.month}. {last.year}"
    return f"{first.day}. {first.month}. {first.year} – {last.day}. {last.month}. {last.year}"


def _timeline_line(interval: Interval, now: datetime, is_today: bool) -> str:
    start = interval.start.strftime("%H:%M")
    if not interval.is_running:
        end = interval.end.strftime("%H:%M")
        duration = format_duration(interval.duration(now))
        return f"- {start}–{end}  ({duration})  {interval.text}"
    if is_today:
        duration = format_duration(interval.duration(now))
        return f"- {start}–teď  ({duration})  {interval.text} (běží)"
    return f"- {start}–??  {interval.text} (neukončeno)"
