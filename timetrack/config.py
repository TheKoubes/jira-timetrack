"""Loading and creating the application config file."""

import json
from pathlib import Path


def default_config_path() -> Path:
    return Path.home() / ".timetrack" / "config.json"


def _defaults() -> dict:
    return {
        "data_dir": str(Path.home() / "Documents" / "TimeTrack"),
        "filename_format": "%Y-%m-%d.jsonl",
        "summary_filename_format": "%Y-%m-%d-summary.md",
        "week_summary_filename_format": "%G-W%V-summary.md",
        "hotkey": "ctrl+alt+t",
        "rounding_minutes": 15,
        "rounding_mode": "nearest",
        "round_times": False,
        "auto_stop_on_lock": False,
        "auto_stop_on_suspend": False,
        "auto_stop_on_logoff": False,
        # Jira: neutrální defaulty — URL doplní uživatel (instalátor/Nastavení),
        # prázdné account pole se hledá samo (jira.resolve_account_field).
        "jira_base_url": "",
        "jira_email": "",
        "jira_account_field": "",
        # Kontrola nových verzí na GitHubu (upozornění v liště). update_repo =
        # kde se release hledají; prázdné update_check vypne kontrolu.
        "update_check": True,
        "update_repo": "TheKoubes/jira-timetrack",
    }


def update_config(values: dict, config_path: Path | None = None) -> dict:
    """Merge *values* into the config file, preserving all other keys.

    Read-modify-write so the Settings UI can save a subset without dropping
    keys it doesn't know about (incl. future ones). Returns the merged config.
    """
    path = config_path or default_config_path()
    cfg = load_config(path)
    cfg.update(values)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def load_config(config_path: Path | None = None) -> dict:
    """Load config from *config_path*, creating it with defaults if missing.

    Keys missing in an existing file fall back to defaults and are written
    back, so the file always shows every available option.
    """
    path = config_path or default_config_path()
    cfg = _defaults()
    if path.exists():
        stored = json.loads(path.read_text(encoding="utf-8"))
        cfg.update(stored)
        if set(cfg) - set(stored):
            path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg
