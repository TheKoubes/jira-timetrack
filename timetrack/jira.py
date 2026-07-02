"""Sending worklogs to Jira Cloud (REST API v3, standard library only).

One worklog = one contiguous block of work on one ticket (adjacent
intervals of the same ticket merge into one block). Blocks tile the day
without overlapping — also after ``round_times`` snaps their boundaries
to ``rounding_minutes`` — so they never overlap in Jira either.
Successful sends are recorded back into the day file as ``jira_sync``
events carrying the block identity, so repeated runs offer only what is
still unsent.
"""

import base64
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from timetrack import crypto, storage
from timetrack.core import build_intervals, round_intervals
from timetrack.summary import format_duration

API_TIMEOUT = 30

TOKEN_URL = "https://id.atlassian.com/manage-profile/security/api-tokens"

TEMPO_BASE = "https://api.tempo.io/4"

# Typy custom fieldu, kterým Tempo ukládá account na požadavek — Jira Cloud
# (Connect aplikace) a starší Server/DC plugin. Pole se hledá podle typu,
# protože jeho id (customfield_XXXXX) se liší instance od instance.
ACCOUNT_FIELD_TYPES = {
    "com.atlassian.plugins.atlassian-connect-plugin:io.tempo.jira__account",
    "com.tempoplugin.tempo-accounts:accounts.customfield",
}


class JiraError(Exception):
    """User-presentable failure: missing setup or a refused API call."""


@dataclass
class WorklogItem:
    """One worklog: a contiguous block of work on one ticket."""

    ticket: str
    seconds: int
    started: datetime
    activities: list[str]
    block_id: str  # exact start of the block's first interval — the sync identity
    worklog_id: str = ""  # non-empty = the block is in Jira under this id
    worklog_source: str = "jira"  # which API created it: "jira" | "tempo"
    comment: str | None = None  # None = use default_comment, "" = explicitly empty
    notes: list[str] = field(default_factory=list)

    @property
    def is_sent(self) -> bool:
        return bool(self.worklog_id)

    @property
    def default_comment(self) -> str:
        """Worklog comment when the user wrote nothing: the notes, or empty."""
        return "; ".join(self.notes)

    @property
    def effective_comment(self) -> str:
        """The comment actually sent: the typed one, else the notes."""
        return self.comment if self.comment is not None else self.default_comment

    @property
    def duration_label(self) -> str:
        return format_duration(timedelta(seconds=self.seconds))

    @property
    def range_label(self) -> str:
        end = self.started + timedelta(seconds=self.seconds)
        return f"{self.started:%H:%M}–{end:%H:%M}"


@dataclass
class IssueInfo:
    issue_id: str  # Jira numeric id (Tempo API works with ids, not keys)
    account_id: int | None
    account_name: str
    summary: str = ""  # the issue title, for display


def api_log_path() -> Path:
    return Path.home() / ".timetrack" / "api_errors.log"


def _log_api_error(context: str, error: urllib.error.HTTPError) -> str:
    """Append the failed call incl. the full response body to the error log.

    Returns the body so messages can quote it — ``error.read()`` works only
    once. The app runs window-less (pythonw), so this file is the only place
    where the server's answer survives.
    """
    try:
        detail = error.read().decode("utf-8", "replace")
    except (OSError, AttributeError, ValueError):
        detail = ""
    try:
        with api_log_path().open("a", encoding="utf-8") as f:
            stamp = datetime.now().astimezone().isoformat(timespec="seconds")
            f.write(f"{stamp}  {context}  HTTP {error.code}\n{detail}\n---\n")
    except OSError:
        pass
    return detail


def _http_failure(
    error: urllib.error.HTTPError, request: urllib.request.Request, ticket: str
) -> JiraError:
    detail = _log_api_error(f"{request.get_method()} {request.full_url}", error)
    return JiraError(_describe_http_error(error.code, detail, ticket))


def token_path() -> Path:
    return Path.home() / ".timetrack" / "jira_token"


def tempo_token_path() -> Path:
    return Path.home() / ".timetrack" / "tempo_token"


def _read_token_file(path: Path, label: str) -> str:
    """Read a token file, translating decryption failures to JiraError.

    DPAPI je vázané na účet Windows — soubor přenesený z jiného účtu/PC nejde
    dešifrovat (OSError), poškozený obsah neprojde přes base64 (ValueError).
    Bez překladu na JiraError by výjimka tiše zabila pracovní vlákno odesílání.
    """
    try:
        return crypto.read_secret(path)
    except (OSError, ValueError) as error:
        raise JiraError(
            f"{label} v {path} se nepodařilo dešifrovat ({error}).\n"
            "Token je vázaný na účet Windows — ulož ho znovu v Nastavení → Integrace."
        ) from error


def load_tempo_token() -> str:
    """Tempo API token, or "" — without it worklogs go through plain Jira."""
    return _read_token_file(tempo_token_path(), "Tempo token")


def load_credentials(cfg: dict) -> tuple[str, str]:
    """Return (email, API token), or raise JiraError explaining the setup."""
    email = cfg.get("jira_email", "").strip()
    if not email:
        raise JiraError(
            'V configu chybí "jira_email" (e-mail tvého Atlassian účtu).\n'
            "Doplň ho do ~/.timetrack/config.json."
        )
    token = _read_token_file(token_path(), "Jira token")
    if not token:
        raise JiraError(
            f"Chybí API token v souboru {token_path()}.\n"
            f"Vygeneruj si ho na {TOKEN_URL} a ulož ho tam jako jediný řádek."
        )
    return email, token


def site_url(cfg: dict) -> str:
    """Derive the Jira site (scheme + host) from the configured browse URL."""
    parts = urllib.parse.urlsplit(cfg.get("jira_base_url", ""))
    if not parts.scheme or not parts.netloc:
        raise JiraError(
            'V configu chybí platná "jira_base_url" (např. https://firma.atlassian.net/browse/).'
        )
    return f"{parts.scheme}://{parts.netloc}"


def sent_worklogs(events: list[dict]) -> dict[str, tuple[str, str]]:
    """Map block identity → (worklog id, source) for blocks currently in Jira.

    ``jira_sync`` marks a block as sent, a later ``jira_unsync`` (deletion
    from Jira) takes the mark back again.
    """
    sent: dict[str, tuple[str, str]] = {}
    for event in events:
        if "start_ts" not in event:
            continue
        if event.get("type") == "jira_sync":
            sent[event["start_ts"]] = (
                str(event.get("worklog_id", "")),
                event.get("worklog_source", "jira"),
            )
        elif event.get("type") == "jira_unsync":
            sent.pop(event["start_ts"], None)
    return sent


def last_comments(events: list[dict]) -> dict[str, str]:
    """Per block, the most recent comment ever sent (survives a later delete).

    Lets the dialog show the comment on sent worklogs and pre-fill it again
    after a worklog is deleted from Jira, so it need not be retyped.
    """
    comments: dict[str, str] = {}
    for event in events:
        if event.get("type") == "jira_sync" and event.get("start_ts") and event.get("comment"):
            comments[event["start_ts"]] = event["comment"]
    return comments


def pending_worklogs(cfg: dict, day: date) -> tuple[list[WorklogItem], list[str]]:
    """Just the unsent part of :func:`day_worklogs`."""
    items, collapsed = day_worklogs(cfg, day)
    return [item for item in items if not item.is_sent], collapsed


def day_worklogs(cfg: dict, day: date) -> tuple[list[WorklogItem], list[str]]:
    """All worklog blocks of *day* (sent and unsent), plus collapsed activities.

    Adjacent intervals of the same ticket merge into one block. With
    ``round_times`` enabled the block boundaries snap to ``rounding_minutes``;
    activities shorter than half a step collapse to zero and are reported in
    the second return value instead of being offered. Running intervals and
    activities without a ticket are left out. Blocks recorded as sent carry
    their Jira ``worklog_id``.
    """
    events = storage.read_day_events(cfg, day)
    closed = [i for i in build_intervals(events) if not i.is_running and i.ticket]
    minutes = cfg.get("rounding_minutes", 0) if cfg.get("round_times") else 0
    rounded = round_intervals(closed, minutes)

    blocks: list[dict] = []
    collapsed: list[str] = []
    for source, interval in zip(closed, rounded):
        if interval.end <= interval.start:
            collapsed.append(source.text)
            continue
        last = blocks[-1] if blocks else None
        if last and last["ticket"] == interval.ticket and last["end"] == interval.start:
            last["end"] = interval.end
            last["texts"].append(interval.text)
            last["notes"].extend(interval.notes)
        else:
            blocks.append(
                {
                    "id": source.start.isoformat(),
                    "ticket": interval.ticket,
                    "start": interval.start,
                    "end": interval.end,
                    "texts": [interval.text],
                    "notes": list(interval.notes),
                }
            )

    sent = sent_worklogs(events)
    comments = last_comments(events)
    items = []
    for block in blocks:
        worklog_id, source = sent.get(block["id"], ("", "jira"))
        items.append(
            WorklogItem(
                ticket=block["ticket"],
                seconds=int((block["end"] - block["start"]).total_seconds()),
                started=block["start"],
                activities=list(dict.fromkeys(block["texts"])),
                block_id=block["id"],
                worklog_id=worklog_id,
                worklog_source=source,
                comment=comments.get(block["id"]),  # dříve odeslaný komentář, jinak None
                notes=list(dict.fromkeys(block["notes"])),
            )
        )
    return items, list(dict.fromkeys(collapsed))


def send_worklog(cfg: dict, item: WorklogItem, email: str, token: str, opener=None) -> str:
    """POST *item* as a worklog to Jira; return the created worklog id."""
    url = f"{site_url(cfg)}/rest/api/3/issue/{item.ticket}/worklog"
    auth = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
    body = {
        "started": format_started(item.started),
        "timeSpentSeconds": item.seconds,
    }
    # Comment: what the user wrote; without input the notes; otherwise none at
    # all (the ticket key belongs to the issue, not into the comment).
    if item.effective_comment:
        body["comment"] = _adf_paragraph(item.effective_comment)
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    opener = opener or urllib.request.build_opener()
    try:
        with opener.open(request, timeout=API_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise _http_failure(error, request, item.ticket) from error
    except urllib.error.URLError as error:
        raise JiraError(f"Jira není dostupná: {error.reason}") from error
    return str(payload.get("id", ""))


def fetch_account(cfg: dict, ticket: str, email: str, token: str, opener=None) -> str:
    """The ticket's account name for display — "" when not configured."""
    if not cfg.get("jira_account_field", ""):
        return ""
    return fetch_issue_info(cfg, ticket, email, token, opener=opener).account_name


def discover_account_field(cfg: dict, email: str, token: str, opener=None) -> str:
    """Find the Tempo account field's id by listing fields (GET /rest/api/3/field).

    Returns e.g. ``"customfield_10100"``, or "" when the instance has no
    Tempo account field at all.
    """
    url = f"{site_url(cfg)}/rest/api/3/field"
    auth = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url, headers={"Authorization": f"Basic {auth}", "Accept": "application/json"}
    )
    opener = opener or urllib.request.build_opener()
    try:
        with opener.open(request, timeout=API_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise _http_failure(error, request, "seznam polí") from error
    except urllib.error.URLError as error:
        raise JiraError(f"Jira není dostupná: {error.reason}") from error
    for field_info in payload if isinstance(payload, list) else []:
        if (field_info.get("schema") or {}).get("custom") in ACCOUNT_FIELD_TYPES:
            return str(field_info.get("id", ""))
    return ""


def resolve_account_field(
    cfg: dict, email: str, token: str, opener=None, cache: dict | None = None
) -> str:
    """Effective account field id: the config value, else auto-discovery.

    Prázdné ``jira_account_field`` znamená „najdi si pole sám podle typu";
    vyplněné id má přednost (přebití pro nestandardní instance). Výsledek
    discovery se ukládá do *cache* pod klíč ``"account_field"``, ať se seznam
    polí nestahuje pro každý ticket znovu.
    """
    explicit = cfg.get("jira_account_field", "")
    if explicit:
        return explicit
    if cache is not None and "account_field" in cache:
        return cache["account_field"]
    field_id = discover_account_field(cfg, email, token, opener=opener)
    if cache is not None:
        cache["account_field"] = field_id
    return field_id


def fetch_issue_info(
    cfg: dict, ticket: str, email: str, token: str, opener=None, field_id: str | None = None
) -> IssueInfo:
    """Read the issue's id, title (summary) and account field.

    ``field_id=None`` bere pole přímo z configu (bez auto-discovery) — kdo
    chce discovery, vyřeší si id předem přes :func:`resolve_account_field`.
    """
    if field_id is None:
        field_id = cfg.get("jira_account_field", "")
    fields = "summary" + (f",{field_id}" if field_id else "")
    url = f"{site_url(cfg)}/rest/api/3/issue/{ticket}?fields={fields}"
    auth = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url, headers={"Authorization": f"Basic {auth}", "Accept": "application/json"}
    )
    opener = opener or urllib.request.build_opener()
    try:
        with opener.open(request, timeout=API_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise _http_failure(error, request, ticket) from error
    except urllib.error.URLError as error:
        raise JiraError(f"Jira není dostupná: {error.reason}") from error
    issue_id = str(payload.get("id", ""))
    fields_data = payload.get("fields") or {}
    summary = str(fields_data.get("summary") or "")
    value = fields_data.get(field_id) if field_id else None
    if isinstance(value, dict):
        name = str(value.get("value") or value.get("name") or "")
        return IssueInfo(issue_id, value.get("id"), name, summary)
    return IssueInfo(issue_id, None, str(value) if value else "", summary)


def fetch_myself(cfg: dict, email: str, token: str, opener=None) -> str:
    """The Atlassian accountId of the API user (Tempo needs it as author)."""
    url = f"{site_url(cfg)}/rest/api/3/myself"
    auth = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url, headers={"Authorization": f"Basic {auth}", "Accept": "application/json"}
    )
    opener = opener or urllib.request.build_opener()
    try:
        with opener.open(request, timeout=API_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise _http_failure(error, request, "myself") from error
    except urllib.error.URLError as error:
        raise JiraError(f"Jira není dostupná: {error.reason}") from error
    return str(payload.get("accountId", ""))


def submit_worklog(
    cfg: dict, item: WorklogItem, email: str, token: str, opener=None, cache: dict | None = None
) -> tuple[str, str]:
    """Send *item* the best available way; return (worklog id, source).

    With a Tempo token the worklog goes through the Tempo API and carries
    the ``_Account_`` attribute (the "Typ činnosti" field) resolved from the
    issue's account; without one it falls back to the plain Jira API, where
    the attribute cannot be set. The account field id comes from the config
    or auto-discovery (:func:`resolve_account_field`). *cache* spares
    repeated lookups (author, issues, account keys) when sending several
    items in one run.
    """
    cache = cache if cache is not None else {}
    if "tempo_token" not in cache:
        cache["tempo_token"] = load_tempo_token()
    tempo_token = cache["tempo_token"]
    if not tempo_token:
        return send_worklog(cfg, item, email, token, opener=opener), "jira"

    if "author" not in cache:
        cache["author"] = fetch_myself(cfg, email, token, opener=opener)
    field_id = resolve_account_field(cfg, email, token, opener=opener, cache=cache)
    issue_key = ("issue", item.ticket)
    if issue_key not in cache:
        cache[issue_key] = fetch_issue_info(
            cfg, item.ticket, email, token, opener=opener, field_id=field_id
        )
    info: IssueInfo = cache[issue_key]
    attribute_key = ""
    account_key = ""
    if info.account_id is not None:
        if "account_attribute" not in cache:
            cache["account_attribute"] = fetch_tempo_account_attribute(tempo_token, opener=opener)
        attribute_key = cache["account_attribute"]
        if attribute_key:
            key_key = ("account_key", info.account_id)
            if key_key not in cache:
                cache[key_key] = fetch_tempo_account_key(
                    info.account_id, tempo_token, opener=opener
                )
            account_key = cache[key_key]
    worklog_id = send_worklog_tempo(
        item, info.issue_id, attribute_key, account_key, cache["author"], tempo_token,
        opener=opener,
    )
    return worklog_id, "tempo"


def send_worklog_tempo(
    item: WorklogItem,
    issue_id: str,
    account_attribute: str,
    account_key: str,
    author_account_id: str,
    tempo_token: str,
    opener=None,
) -> str:
    """POST the worklog to the Tempo API; return the Tempo worklog id."""
    body = {
        "issueId": int(issue_id),
        "timeSpentSeconds": item.seconds,
        "startDate": item.started.strftime("%Y-%m-%d"),
        "startTime": item.started.strftime("%H:%M:%S"),
        "authorAccountId": author_account_id,
    }
    if item.effective_comment:
        body["description"] = item.effective_comment
    if account_attribute and account_key:
        body["attributes"] = [{"key": account_attribute, "value": account_key}]
    payload = _tempo_request("POST", "/worklogs", tempo_token, body, opener=opener)
    return str(payload.get("tempoWorklogId", ""))


def fetch_tempo_account_attribute(tempo_token: str, opener=None) -> str:
    """Key of the instance's ACCOUNT-type work attribute ("" when none exists).

    The key is admin-defined (here e.g. ``_Typčinnosti_``), so it cannot be
    hardcoded — it is discovered from the work-attributes list.
    """
    payload = _tempo_request("GET", "/work-attributes", tempo_token, opener=opener)
    for attribute in payload.get("results", []):
        if attribute.get("type") == "ACCOUNT":
            return str(attribute.get("key", ""))
    return ""


def fetch_tempo_account_key(account_id: int, tempo_token: str, opener=None) -> str:
    """Map a Tempo account id (from the issue field) to its account key."""
    offset, limit = 0, 200
    while True:
        payload = _tempo_request(
            "GET", f"/accounts?limit={limit}&offset={offset}", tempo_token, opener=opener
        )
        results = payload.get("results", [])
        for account in results:
            if account.get("id") == account_id:
                return str(account.get("key", ""))
        if len(results) < limit:
            return ""
        offset += limit


def remove_worklog(cfg: dict, item: WorklogItem, email: str, token: str, opener=None) -> None:
    """Delete the worklog from Jira/Tempo, whichever created it."""
    if item.worklog_source == "tempo":
        tempo_token = load_tempo_token()
        if not tempo_token:
            raise JiraError(
                f"Worklog byl založen přes Tempo — pro smazání chybí token v {tempo_token_path()}."
            )
        _tempo_request("DELETE", f"/worklogs/{item.worklog_id}", tempo_token, opener=opener)
        return
    delete_worklog(cfg, item.ticket, item.worklog_id, email, token, opener=opener)


def _tempo_request(method: str, path: str, tempo_token: str, body=None, opener=None) -> dict:
    headers = {"Authorization": f"Bearer {tempo_token}", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        TEMPO_BASE + path,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers=headers,
        method=method,
    )
    opener = opener or urllib.request.build_opener()
    try:
        with opener.open(request, timeout=API_TIMEOUT) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = _log_api_error(f"{method} {TEMPO_BASE + path}", error)
        raise JiraError(_describe_tempo_error(error.code, detail)) from error
    except urllib.error.URLError as error:
        raise JiraError(f"Tempo není dostupné: {error.reason}") from error
    return json.loads(raw.decode("utf-8")) if raw else {}


def _describe_tempo_error(code: int, detail: str) -> str:
    if code == 401:
        return f"Tempo odmítlo token (401) — zkontroluj {tempo_token_path()}."
    if code == 403:
        return "Tempo: chybí oprávnění (403) — token potřebuje scopes worklogs:write a accounts:read."
    return f"Tempo vrátilo HTTP {code}. {detail[:300]}".rstrip()


def delete_worklog(
    cfg: dict, ticket: str, worklog_id: str, email: str, token: str, opener=None
) -> None:
    """DELETE the worklog from Jira (idempotent from the caller's view)."""
    url = f"{site_url(cfg)}/rest/api/3/issue/{ticket}/worklog/{worklog_id}"
    auth = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url, headers={"Authorization": f"Basic {auth}"}, method="DELETE"
    )
    opener = opener or urllib.request.build_opener()
    try:
        with opener.open(request, timeout=API_TIMEOUT):
            pass
    except urllib.error.HTTPError as error:
        raise _http_failure(error, request, ticket) from error
    except urllib.error.URLError as error:
        raise JiraError(f"Jira není dostupná: {error.reason}") from error


def format_started(dt: datetime) -> str:
    """Jira's required timestamp: milliseconds and a colon-less UTC offset."""
    if dt.tzinfo is None:
        dt = dt.astimezone()
    millis = f"{dt.microsecond // 1000:03d}"
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + millis + dt.strftime("%z")


def parse_selection(text: str, count: int) -> list[int] | None:
    """Map picker input to 0-based indexes.

    ``"1,3"`` → ``[0, 2]``; ``"vse"`` → everything; empty or ``"nic"`` → ``[]``;
    anything unparseable or out of range → None.
    """
    text = text.strip().lower()
    if text in ("", "nic", "n"):
        return []
    if text in ("vse", "vše", "všechno", "vsechno", "all", "a", "v"):
        return list(range(count))
    indexes: list[int] = []
    for part in re.split(r"[,\s]+", text):
        if not part.isdigit() or not 1 <= int(part) <= count:
            return None
        index = int(part) - 1
        if index not in indexes:
            indexes.append(index)
    return indexes


def run_send_command(cfg: dict, day: date, ask=input, opener=None) -> int:
    """CLI picker: list pending worklogs of *day*, let the user choose, send."""
    try:
        email, token = load_credentials(cfg)
        site_url(cfg)
    except JiraError as error:
        print(error, file=sys.stderr)
        return 1

    intervals = build_intervals(storage.read_day_events(cfg, day))
    for interval in intervals:
        if interval.is_running:
            print(f"POZOR: neukoncena aktivita se neposila: {interval.text}")
    unticketed = list(dict.fromkeys(i.text for i in intervals if not i.is_running and not i.ticket))
    if unticketed:
        print(f"Bez ticketu (nelze odeslat): {', '.join(unticketed)}")

    all_items, collapsed = day_worklogs(cfg, day)
    for item in all_items:
        if item.is_sent:
            print(
                f"Uz v Jire: {item.ticket}  {item.range_label}  {item.duration_label}"
                f" (worklog {item.worklog_id})"
            )
    if collapsed:
        print(f"Po zaokrouhleni spadly na 0 a neposilaji se: {', '.join(collapsed)}")
    items = [item for item in all_items if not item.is_sent]
    if not items:
        print(f"Zadne neodeslane worklogy za {day.isoformat()}.")
        return 0

    print(f"Worklogy k odeslani za {day.isoformat()}:")
    for n, item in enumerate(items, start=1):
        print(
            f"  {n}. {item.ticket}  {item.range_label}  {item.duration_label}"
            f"  — {'; '.join(item.activities)}"
        )
    answer = ask("Odeslat (cisla / vse / nic): ")
    indexes = parse_selection(answer, len(items))
    if indexes is None:
        print("Neplatny vyber.", file=sys.stderr)
        return 2
    if not indexes:
        print("Nic neodeslano.")
        return 0

    failures = 0
    cache: dict = {}
    for index in indexes:
        item = items[index]
        if not (item.comment or item.default_comment):
            failures += 1
            print(
                f"CHYBA {item.ticket}: prazdny komentar — pridej behem dne poznamku"
                " (pozn ...) nebo posli pres dialog.",
                file=sys.stderr,
            )
            continue
        try:
            worklog_id, source = submit_worklog(cfg, item, email, token, opener=opener, cache=cache)
            storage.append_jira_sync(
                cfg, day, item.ticket, item.seconds, worklog_id, item.block_id,
                source=source, comment=item.effective_comment,
            )
            print(
                f"OK {item.ticket}: {item.range_label} ({item.duration_label})"
                f" zapsano (worklog {worklog_id})"
            )
        except JiraError as error:
            failures += 1
            print(f"CHYBA {error}", file=sys.stderr)
    if cache.get("tempo_token") == "" and cfg.get("jira_account_field"):
        print("POZOR: bez Tempo tokenu zustava Typ cinnosti (account) prazdny — viz README.")
    return 1 if failures else 0


def _adf_paragraph(text: str) -> dict:
    # API v3 bere komentar worklogu jen jako Atlassian Document Format
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _describe_http_error(code: int, detail: str, ticket: str) -> str:
    if code == 401:
        return "Jira odmítla přihlášení (401) — zkontroluj jira_email a API token."
    if code == 403:
        return f"{ticket}: chybí oprávnění zapisovat čas (403) — chce to právo „Work on issues“."
    if code == 404:
        return f"{ticket}: ticket v Jiře neexistuje nebo na něj nevidíš (404)."
    return f"{ticket}: Jira vrátila HTTP {code}. {detail[:300]}".rstrip()
