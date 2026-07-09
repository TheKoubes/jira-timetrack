"""Tichá kontrola nové verze na GitHub Releases (jen upozornění).

Samotnou instalaci dělá ``update.ps1`` (krok D) — tenhle modul jen zjistí,
jestli vyšla novější verze, a to nanejvýš jednou za ``CHECK_INTERVAL``
(throttling přes stavový soubor v ``~/.timetrack``). Když je kontrola vypnutá,
počítač offline nebo API selže, vrací ``None`` a nic nehlásí.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

REPO = "TheKoubes/jira-timetrack"
API_TIMEOUT = 15
CHECK_INTERVAL = timedelta(hours=20)  # ~1× denně; restart téhož dne znovu nekontroluje


@dataclass
class UpdateInfo:
    """Dostupná novější verze — číslo a odkaz na stránku release."""

    version: str
    url: str


def state_path() -> Path:
    return Path.home() / ".timetrack" / "update_state.json"


def parse_version(text: str) -> tuple[int, ...]:
    """"v1.3" → (1, 3); nečíselné části se berou jako 0, ať porovnání nespadne."""
    parts = []
    for chunk in text.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(path: Path, state: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass


def _due(state: dict, now: datetime, interval: timedelta) -> bool:
    """True, když od poslední kontroly uplynul aspoň *interval* (nebo nikdy)."""
    last = state.get("last_check")
    if not last:
        return True
    try:
        return now - datetime.fromisoformat(last) >= interval
    except (ValueError, TypeError):
        return True


def fetch_latest(repo: str = REPO, opener=None, prerelease: bool = False) -> tuple[str, str]:
    """Vrať (tag, url) nejnovějšího release. GitHub vyžaduje User-Agent.

    ``prerelease=True`` (beta kanál) bere i pre-release verze — proto sahá na
    ``/releases`` (seznam), protože ``/releases/latest`` pre-release ignoruje;
    vezme první nekoncept (nejnovější publikovaný). Bez toho jen ``/latest``.
    """
    path = "/releases?per_page=10" if prerelease else "/releases/latest"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}{path}",
        headers={
            "User-Agent": "TimeTrack-updatecheck",
            "Accept": "application/vnd.github+json",
        },
    )
    opener = opener or urllib.request.build_opener()
    with opener.open(request, timeout=API_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if prerelease:
        for rel in payload if isinstance(payload, list) else []:
            if not rel.get("draft"):
                return str(rel.get("tag_name", "")), str(rel.get("html_url", ""))
        return "", ""
    return str(payload.get("tag_name", "")), str(payload.get("html_url", ""))


def check(cfg: dict, current: str, *, now: datetime | None = None, opener=None,
          path: Path | None = None) -> UpdateInfo | None:
    """Vrať :class:`UpdateInfo`, když je k dispozici novější verze, jinak None.

    Respektuje ``update_check`` (opt-out), throttluje přes stavový soubor a
    offline/chybu API spolkne (vrátí None). Stav (čas poslední kontroly) se
    zapíše jen po úspěšném dotazu, aby se offline start zkusil znovu příště.
    """
    if not cfg.get("update_check", True):
        return None
    now = now or datetime.now().astimezone()
    path = path or state_path()
    state = _load_state(path)
    if not _due(state, now, CHECK_INTERVAL):
        return None
    try:
        tag, html_url = fetch_latest(
            cfg.get("update_repo") or REPO,
            opener=opener,
            prerelease=bool(cfg.get("update_prerelease")),
        )
    except (urllib.error.URLError, OSError, ValueError):
        return None  # offline / API chyba → potichu, stav se nemění (zkusí se zas)
    state["last_check"] = now.isoformat()
    state["latest_seen"] = tag
    _save_state(path, state)
    if tag and is_newer(tag, current):
        return UpdateInfo(tag.lstrip("vV"), html_url)
    return None
