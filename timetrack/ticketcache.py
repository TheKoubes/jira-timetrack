"""Local cache of ticket → title (summary), so names show without refetching.

Stored next to the config; the Jira summary changes rarely, so the cache is
shown instantly and refreshed in the background when the dialog opens.
"""

import json
import os
import tempfile
from pathlib import Path

from timetrack import config


def _path() -> Path:
    return config.default_config_path().parent / "ticket_names.json"


def load_names() -> dict[str, str]:
    path = _path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def save_names(names: dict[str, str]) -> None:
    # Unikátní dočasný soubor + os.replace = atomická výměna celého obsahu.
    # Překrývající se load_meta workery (rychlé přepínání dnů) tak soubor
    # nemohou poškodit — poslední zapisující vyhrává, což cache nevadí.
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write(json.dumps(names, ensure_ascii=False, indent=2))
            os.replace(tmp, path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        pass
