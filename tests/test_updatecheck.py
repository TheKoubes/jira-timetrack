import json
import urllib.error
from datetime import datetime, timedelta, timezone

from timetrack import updatecheck

NOW = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class FakeOpener:
    """Vrací pevný payload; volitelně vyhodí chybu. Počítá volání."""

    def __init__(self, payload=None, error=None):
        self.payload = payload if payload is not None else {"tag_name": "v1.4", "html_url": "u"}
        self.error = error
        self.calls = 0

    def open(self, request, timeout=None):
        self.calls += 1
        if self.error:
            raise self.error
        return FakeResponse(self.payload)


class TestVersionCompare:
    def test_parses_and_strips_v_prefix(self):
        assert updatecheck.parse_version("v1.3") == (1, 3)
        assert updatecheck.parse_version("1.3.1") == (1, 3, 1)

    def test_newer_by_minor(self):
        assert updatecheck.is_newer("1.3", "1.2")
        assert not updatecheck.is_newer("1.2", "1.3")

    def test_numeric_not_lexical(self):
        assert updatecheck.is_newer("1.10", "1.9")  # 10 > 9, ne řetězcově

    def test_equal_is_not_newer(self):
        assert not updatecheck.is_newer("1.3", "1.3")
        assert not updatecheck.is_newer("v1.3", "1.3")

    def test_patch_beats_base(self):
        assert updatecheck.is_newer("1.3.1", "1.3")


def cfg(**over):
    base = {"update_check": True, "update_repo": "x/y"}
    base.update(over)
    return base


class TestCheck:
    def test_disabled_skips_network(self, tmp_path):
        opener = FakeOpener()
        result = updatecheck.check(
            cfg(update_check=False), "1.3", now=NOW, opener=opener, path=tmp_path / "s.json"
        )
        assert result is None
        assert opener.calls == 0

    def test_throttled_within_interval_skips_network(self, tmp_path):
        state = tmp_path / "s.json"
        recent = (NOW - timedelta(hours=1)).isoformat()
        state.write_text(json.dumps({"last_check": recent}), encoding="utf-8")
        opener = FakeOpener()

        result = updatecheck.check(cfg(), "1.3", now=NOW, opener=opener, path=state)

        assert result is None
        assert opener.calls == 0

    def test_due_and_newer_returns_info_and_writes_state(self, tmp_path):
        state = tmp_path / "s.json"
        opener = FakeOpener(payload={"tag_name": "v1.4", "html_url": "https://rel/1.4"})

        result = updatecheck.check(cfg(), "1.3", now=NOW, opener=opener, path=state)

        assert result == updatecheck.UpdateInfo("1.4", "https://rel/1.4")
        saved = json.loads(state.read_text(encoding="utf-8"))
        assert saved["last_check"] == NOW.isoformat()
        assert saved["latest_seen"] == "v1.4"

    def test_due_but_same_version_returns_none_but_records_check(self, tmp_path):
        state = tmp_path / "s.json"
        opener = FakeOpener(payload={"tag_name": "v1.3", "html_url": "u"})

        result = updatecheck.check(cfg(), "1.3", now=NOW, opener=opener, path=state)

        assert result is None
        assert json.loads(state.read_text(encoding="utf-8"))["last_check"] == NOW.isoformat()

    def test_offline_is_silent_and_leaves_state_untouched(self, tmp_path):
        state = tmp_path / "s.json"
        opener = FakeOpener(error=urllib.error.URLError("offline"))

        result = updatecheck.check(cfg(), "1.3", now=NOW, opener=opener, path=state)

        assert result is None
        assert not state.exists()  # neúspěch se nezapisuje → příště se zkusí znovu

    def test_missing_release_http_error_is_silent(self, tmp_path):
        err = urllib.error.HTTPError("u", 404, "Not Found", None, None)
        opener = FakeOpener(error=err)

        result = updatecheck.check(cfg(), "1.3", now=NOW, opener=opener, path=tmp_path / "s.json")

        assert result is None
