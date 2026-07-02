import base64
import io
import json
import urllib.error
from datetime import date, datetime, timedelta, timezone

import pytest

from timetrack import jira, storage

TZ = timezone(timedelta(hours=2))
DAY = date(2026, 6, 10)


@pytest.fixture
def cfg(tmp_path):
    return {
        "data_dir": str(tmp_path / "data"),
        "filename_format": "%Y-%m-%d.jsonl",
        "rounding_minutes": 15,
        "rounding_mode": "nearest",
        "round_times": False,
        "jira_base_url": "https://firma.atlassian.net/browse/",
        "jira_email": "ja@firma.cz",
    }


@pytest.fixture
def token_file(tmp_path, monkeypatch):
    path = tmp_path / "jira_token"
    path.write_text("tajny-token\n", encoding="utf-8")
    monkeypatch.setattr(jira, "token_path", lambda: path)
    return path


def when(hour, minute):
    return datetime(2026, 6, 10, hour, minute, tzinfo=TZ)


def log_workday(cfg):
    """PROJ-1: 9:00-10:00, schuzka (bez ticketu): 10:00-10:30,
    PROJ-1: 10:30-11:00, PROJ-2: 11:00-12:00 -> tri bloky."""
    storage.append_start(cfg, "PROJ-1 oprava // zakladni pozn", ts=when(9, 0))
    storage.append_start(cfg, "schuzka", ts=when(10, 0))
    storage.append_start(cfg, "PROJ-1 review", ts=when(10, 30))
    storage.append_start(cfg, "PROJ-2 analyza", ts=when(11, 0))
    storage.append_stop(cfg, ts=when(12, 0))


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
    def __init__(self, payload=None, error=None):
        self.requests = []
        self.payload = payload or {"id": "10001"}
        self.error = error

    def open(self, request, timeout=None):
        self.requests.append(request)
        if self.error:
            raise self.error
        return FakeResponse(self.payload)


def http_error(code, body=b""):
    return urllib.error.HTTPError("http://x", code, "msg", None, io.BytesIO(body))


class RoutingOpener:
    """FakeOpener that picks the response payload by URL substring."""

    def __init__(self, routes):
        self.routes = routes  # list of (url_substring, payload)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        for substring, payload in self.routes:
            if substring in request.full_url:
                return FakeResponse(payload)
        raise AssertionError(f"nečekaný požadavek: {request.full_url}")

    def sent_to(self, substring):
        return [r for r in self.requests if substring in r.full_url]


TEMPO_ROUTES = [
    ("/rest/api/3/myself", {"accountId": "user-123"}),
    (
        "/rest/api/3/issue/PROJ-1",
        {"id": "10100", "fields": {"customfield_10100": {"id": 69, "value": "FAKTURACNI"}}},
    ),
    (
        "api.tempo.io/4/work-attributes",
        {"results": [{"key": "_Typčinnosti_", "name": "Typ činnosti", "type": "ACCOUNT"}]},
    ),
    ("api.tempo.io/4/accounts", {"results": [{"id": 69, "key": "FAKT", "name": "FAKTURACNI"}]}),
    ("api.tempo.io/4/worklogs", {"tempoWorklogId": 5555}),
]


@pytest.fixture
def tempo_token_file(tmp_path, monkeypatch):
    path = tmp_path / "tempo_token"
    path.write_text("tempo-tajny\n", encoding="utf-8")
    monkeypatch.setattr(jira, "tempo_token_path", lambda: path)
    return path


@pytest.fixture(autouse=True)
def isolated_api_log(tmp_path, monkeypatch):
    monkeypatch.setattr(jira, "api_log_path", lambda: tmp_path / "api_errors.log")


@pytest.fixture(autouse=True)
def no_tempo_token(tmp_path, monkeypatch):
    # Vychozi izolace: zadny Tempo token, at testy nezavisi na stavu stroje.
    # Testy s fixture `tempo_token_file` si cestu prepisuji na soubor s tokenem.
    monkeypatch.setattr(jira, "tempo_token_path", lambda: tmp_path / "zadny_tempo_token")


class TestPendingWorklogs:
    def test_one_block_per_contiguous_stretch_of_a_ticket(self, cfg):
        log_workday(cfg)

        items, collapsed = jira.pending_worklogs(cfg, DAY)

        assert collapsed == []
        assert [(i.ticket, i.seconds) for i in items] == [
            ("PROJ-1", 3600),
            ("PROJ-1", 1800),
            ("PROJ-2", 3600),
        ]
        assert items[0].started == when(9, 0)
        assert items[1].started == when(10, 30)
        assert items[0].block_id == when(9, 0).isoformat()

    def test_adjacent_intervals_of_same_ticket_merge(self, cfg):
        storage.append_start(cfg, "PROJ-1 oprava", ts=when(9, 0))
        storage.append_start(cfg, "PROJ-1 review", ts=when(10, 0))
        storage.append_stop(cfg, ts=when(11, 0))

        items, _ = jira.pending_worklogs(cfg, DAY)

        assert len(items) == 1
        assert items[0].seconds == 7200
        assert items[0].activities == ["PROJ-1 oprava", "PROJ-1 review"]
        assert items[0].block_id == when(9, 0).isoformat()

    def test_round_times_snaps_block_boundaries(self, cfg):
        cfg["round_times"] = True
        storage.append_start(cfg, "PROJ-1 prace", ts=when(9, 7))
        storage.append_stop(cfg, ts=when(9, 52))

        items, _ = jira.pending_worklogs(cfg, DAY)

        assert items[0].started == when(9, 0)
        assert items[0].seconds == 45 * 60
        assert items[0].block_id == when(9, 7).isoformat()  # identita zustava presna

    def test_round_times_off_keeps_exact_boundaries(self, cfg):
        storage.append_start(cfg, "PROJ-1 prace", ts=when(9, 7))
        storage.append_stop(cfg, ts=when(9, 52))

        items, _ = jira.pending_worklogs(cfg, DAY)

        assert items[0].started == when(9, 7)
        assert items[0].seconds == 45 * 60

    def test_collapsed_activity_is_reported_not_offered(self, cfg):
        cfg["round_times"] = True
        storage.append_start(cfg, "PROJ-9 kratka", ts=when(10, 2))
        storage.append_stop(cfg, ts=when(10, 7))

        items, collapsed = jira.pending_worklogs(cfg, DAY)

        assert items == []
        assert collapsed == ["PROJ-9 kratka"]

    def test_rounded_blocks_never_overlap(self, cfg):
        cfg["round_times"] = True
        storage.append_start(cfg, "PROJ-1 a", ts=when(9, 7))
        storage.append_start(cfg, "PROJ-2 b", ts=when(9, 22))
        storage.append_start(cfg, "PROJ-3 c", ts=when(9, 38))
        storage.append_stop(cfg, ts=when(9, 50))

        items, _ = jira.pending_worklogs(cfg, DAY)

        for earlier, later in zip(items, items[1:]):
            end = earlier.started + timedelta(seconds=earlier.seconds)
            assert later.started >= end

    def test_running_interval_is_not_counted(self, cfg):
        storage.append_start(cfg, "PROJ-1 prace", ts=when(9, 0))

        assert jira.pending_worklogs(cfg, DAY) == ([], [])

    def test_unticketed_activity_is_not_offered(self, cfg):
        storage.append_start(cfg, "schuzka", ts=when(9, 0))
        storage.append_stop(cfg, ts=when(10, 0))

        assert jira.pending_worklogs(cfg, DAY) == ([], [])

    def test_sent_blocks_are_filtered_out(self, cfg):
        log_workday(cfg)
        storage.append_jira_sync(cfg, DAY, "PROJ-1", 3600, "1", when(9, 0).isoformat())

        items, _ = jira.pending_worklogs(cfg, DAY)

        assert [(i.ticket, i.started) for i in items] == [
            ("PROJ-1", when(10, 30)),
            ("PROJ-2", when(11, 0)),
        ]

    def test_fully_sent_day_offers_nothing(self, cfg):
        log_workday(cfg)
        for start in (when(9, 0), when(10, 30), when(11, 0)):
            storage.append_jira_sync(cfg, DAY, "X", 1, "1", start.isoformat())

        assert jira.pending_worklogs(cfg, DAY) == ([], [])


class TestDayWorklogs:
    def test_sent_blocks_carry_worklog_id(self, cfg):
        log_workday(cfg)
        storage.append_jira_sync(cfg, DAY, "PROJ-1", 3600, "77", when(9, 0).isoformat())

        items, _ = jira.day_worklogs(cfg, DAY)

        assert [(i.ticket, i.is_sent, i.worklog_id) for i in items] == [
            ("PROJ-1", True, "77"),
            ("PROJ-1", False, ""),
            ("PROJ-2", False, ""),
        ]

    def test_unsync_marks_block_unsent_again(self, cfg):
        log_workday(cfg)
        storage.append_jira_sync(cfg, DAY, "PROJ-1", 3600, "77", when(9, 0).isoformat())
        storage.append_jira_unsync(cfg, DAY, "PROJ-1", "77", when(9, 0).isoformat())

        items, _ = jira.day_worklogs(cfg, DAY)

        assert all(not item.is_sent for item in items)
        pending, _ = jira.pending_worklogs(cfg, DAY)
        assert len(pending) == 3


class TestBlockNotes:
    def test_notes_of_merged_intervals_collect_on_block(self, cfg):
        storage.append_start(cfg, "PROJ-1 oprava // prvni pozn", ts=when(9, 0))
        storage.append_start(cfg, "PROJ-1 review", ts=when(10, 0))
        storage.append_note(cfg, "druha pozn", ts=when(10, 30))
        storage.append_stop(cfg, ts=when(11, 0))

        items, _ = jira.day_worklogs(cfg, DAY)

        assert items[0].notes == ["prvni pozn", "druha pozn"]
        assert items[0].default_comment == "prvni pozn; druha pozn"


class TestFetchAccount:
    def test_reads_account_value_from_issue_field(self, cfg):
        cfg["jira_account_field"] = "customfield_10100"
        opener = FakeOpener(
            payload={"fields": {"customfield_10100": {"id": 69, "value": "FAKTURACNI"}}}
        )

        account = jira.fetch_account(cfg, "PROJ-1", "ja@firma.cz", "token", opener=opener)

        assert account == "FAKTURACNI"
        request = opener.requests[0]
        assert request.full_url == (
            "https://firma.atlassian.net/rest/api/3/issue/PROJ-1?fields=summary,customfield_10100"
        )
        assert request.get_method() == "GET"

    def test_reads_issue_summary(self, cfg):
        cfg["jira_account_field"] = ""
        opener = FakeOpener(payload={"id": "100", "fields": {"summary": "Oprava přihlášení"}})

        info = jira.fetch_issue_info(cfg, "PROJ-1", "ja@firma.cz", "token", opener=opener)

        assert info.summary == "Oprava přihlášení"
        assert opener.requests[0].full_url.endswith("?fields=summary")

    def test_empty_field_value_gives_empty_string(self, cfg):
        cfg["jira_account_field"] = "customfield_10100"
        opener = FakeOpener(payload={"fields": {"customfield_10100": None}})

        assert jira.fetch_account(cfg, "PROJ-1", "e", "t", opener=opener) == ""

    def test_unconfigured_field_skips_api(self, cfg):
        opener = FakeOpener()

        assert jira.fetch_account(cfg, "PROJ-1", "e", "t", opener=opener) == ""
        assert opener.requests == []


# Podoba odpovedi GET /rest/api/3/field na Jira Cloudu — typy poli overeny
# 2026-07-02 na zive instanci (Tempo je tam Connect aplikace, typ se lisi
# od Server/DC pluginu); id poli jsou ilustracni.
FIELD_LIST = [
    {"id": "summary", "name": "Summary", "schema": {"type": "string", "system": "summary"}},
    {
        "id": "customfield_10041",
        "name": "Tempo Team",
        "schema": {
            "type": "option2",
            "custom": "com.atlassian.plugins.atlassian-connect-plugin:io.tempo.jira__team",
            "customId": 10041,
        },
    },
    {
        "id": "customfield_10100",
        "name": "Account",
        "schema": {
            "type": "option2",
            "custom": "com.atlassian.plugins.atlassian-connect-plugin:io.tempo.jira__account",
            "customId": 10100,
        },
    },
]


class TestAccountFieldDiscovery:
    def test_discovers_cloud_connect_field_type(self, cfg):
        opener = FakeOpener(payload=FIELD_LIST)

        field_id = jira.discover_account_field(cfg, "ja@firma.cz", "token", opener=opener)

        assert field_id == "customfield_10100"
        request = opener.requests[0]
        assert request.full_url == "https://firma.atlassian.net/rest/api/3/field"
        assert request.get_method() == "GET"

    def test_discovers_server_plugin_field_type(self, cfg):
        opener = FakeOpener(
            payload=[
                {
                    "id": "customfield_11500",
                    "name": "Account",
                    "schema": {
                        "type": "any",
                        "custom": "com.tempoplugin.tempo-accounts:accounts.customfield",
                        "customId": 11500,
                    },
                }
            ]
        )

        assert jira.discover_account_field(cfg, "e", "t", opener=opener) == "customfield_11500"

    def test_instance_without_tempo_accounts_gives_empty(self, cfg):
        opener = FakeOpener(
            payload=[{"id": "summary", "schema": {"type": "string", "system": "summary"}}]
        )

        assert jira.discover_account_field(cfg, "e", "t", opener=opener) == ""

    def test_explicit_config_value_skips_discovery(self, cfg):
        cfg["jira_account_field"] = "customfield_99999"
        opener = FakeOpener()

        field_id = jira.resolve_account_field(cfg, "e", "t", opener=opener)

        assert field_id == "customfield_99999"
        assert opener.requests == []

    def test_resolve_discovers_when_config_empty(self, cfg):
        opener = FakeOpener(payload=FIELD_LIST)

        assert jira.resolve_account_field(cfg, "e", "t", opener=opener) == "customfield_10100"

    def test_resolve_caches_discovery_result(self, cfg):
        opener = FakeOpener(payload=FIELD_LIST)
        cache: dict = {}

        first = jira.resolve_account_field(cfg, "e", "t", opener=opener, cache=cache)
        second = jira.resolve_account_field(cfg, "e", "t", opener=opener, cache=cache)

        assert first == second == "customfield_10100"
        assert len(opener.requests) == 1


class TestSubmitWorklog:
    def item(self, **kwargs):
        defaults = dict(
            ticket="PROJ-1",
            seconds=900,
            started=when(21, 30),
            activities=["PROJ-1 x"],
            block_id="id1",
            notes=["testovací poznámka"],
        )
        defaults.update(kwargs)
        return jira.WorklogItem(**defaults)

    def test_without_tempo_token_uses_jira_api(self, cfg, no_tempo_token):
        opener = FakeOpener(payload={"id": "42"})

        worklog_id, source = jira.submit_worklog(
            cfg, self.item(), "ja@firma.cz", "token", opener=opener
        )

        assert (worklog_id, source) == ("42", "jira")
        assert "/rest/api/3/issue/PROJ-1/worklog" in opener.requests[0].full_url

    def test_with_tempo_token_sends_account_attribute(self, cfg, tempo_token_file):
        cfg["jira_account_field"] = "customfield_10100"
        opener = RoutingOpener(TEMPO_ROUTES)

        worklog_id, source = jira.submit_worklog(
            cfg, self.item(), "ja@firma.cz", "token", opener=opener
        )

        assert (worklog_id, source) == ("5555", "tempo")
        post = opener.sent_to("api.tempo.io/4/worklogs")[0]
        assert post.get_header("Authorization") == "Bearer tempo-tajny"
        body = json.loads(post.data.decode("utf-8"))
        assert body["issueId"] == 10100
        assert body["timeSpentSeconds"] == 900
        assert body["startDate"] == "2026-06-10"
        assert body["startTime"] == "21:30:00"
        assert body["authorAccountId"] == "user-123"
        assert body["description"] == "testovací poznámka"
        assert body["attributes"] == [{"key": "_Typčinnosti_", "value": "FAKT"}]

    def test_issue_without_account_sends_without_attribute(self, cfg, tempo_token_file):
        cfg["jira_account_field"] = "customfield_10100"
        routes = [
            ("/rest/api/3/myself", {"accountId": "user-123"}),
            ("/rest/api/3/issue/PROJ-1", {"id": "10100", "fields": {"customfield_10100": None}}),
            ("api.tempo.io/4/worklogs", {"tempoWorklogId": 5555}),
        ]
        opener = RoutingOpener(routes)

        _worklog_id, source = jira.submit_worklog(
            cfg, self.item(), "ja@firma.cz", "token", opener=opener
        )

        assert source == "tempo"
        body = json.loads(opener.sent_to("api.tempo.io/4/worklogs")[0].data.decode("utf-8"))
        assert "attributes" not in body
        assert opener.sent_to("api.tempo.io/4/accounts") == []

    def test_unset_account_field_is_discovered(self, cfg, tempo_token_file):
        # Generický default: prazdne jira_account_field -> pole se najde
        # pres /rest/api/3/field a atribut se posle stejne jako s configem.
        opener = RoutingOpener([("/rest/api/3/field", FIELD_LIST)] + TEMPO_ROUTES)

        _worklog_id, source = jira.submit_worklog(
            cfg, self.item(), "ja@firma.cz", "token", opener=opener
        )

        assert source == "tempo"
        body = json.loads(opener.sent_to("api.tempo.io/4/worklogs")[0].data.decode("utf-8"))
        assert body["attributes"] == [{"key": "_Typčinnosti_", "value": "FAKT"}]
        assert len(opener.sent_to("/rest/api/3/field")) == 1

    def test_cache_avoids_repeated_lookups(self, cfg, tempo_token_file):
        cfg["jira_account_field"] = "customfield_10100"
        opener = RoutingOpener(TEMPO_ROUTES)
        cache: dict = {}

        jira.submit_worklog(cfg, self.item(), "ja@firma.cz", "t", opener=opener, cache=cache)
        jira.submit_worklog(cfg, self.item(seconds=1800), "ja@firma.cz", "t", opener=opener, cache=cache)

        assert len(opener.sent_to("/rest/api/3/myself")) == 1
        assert len(opener.sent_to("/rest/api/3/issue/PROJ-1")) == 1
        assert len(opener.sent_to("api.tempo.io/4/work-attributes")) == 1
        assert len(opener.sent_to("api.tempo.io/4/accounts")) == 1
        assert len(opener.sent_to("api.tempo.io/4/worklogs")) == 2


class TestRemoveWorklog:
    def test_tempo_worklog_deletes_via_tempo(self, cfg, tempo_token_file):
        item = jira.WorklogItem(
            "PROJ-1", 900, when(9, 0), ["x"], "id1", worklog_id="5555", worklog_source="tempo"
        )
        opener = RoutingOpener([("api.tempo.io/4/worklogs/5555", {})])

        jira.remove_worklog(cfg, item, "ja@firma.cz", "token", opener=opener)

        request = opener.requests[0]
        assert request.get_method() == "DELETE"
        assert request.get_header("Authorization") == "Bearer tempo-tajny"

    def test_tempo_worklog_without_token_fails_clearly(self, cfg, no_tempo_token):
        item = jira.WorklogItem(
            "PROJ-1", 900, when(9, 0), ["x"], "id1", worklog_id="5555", worklog_source="tempo"
        )

        with pytest.raises(jira.JiraError, match="Tempo"):
            jira.remove_worklog(cfg, item, "ja@firma.cz", "token", opener=FakeOpener())

    def test_jira_worklog_deletes_via_jira(self, cfg, no_tempo_token):
        item = jira.WorklogItem(
            "PROJ-1", 900, when(9, 0), ["x"], "id1", worklog_id="77", worklog_source="jira"
        )
        opener = FakeOpener()

        jira.remove_worklog(cfg, item, "ja@firma.cz", "token", opener=opener)

        assert opener.requests[0].full_url.endswith("/issue/PROJ-1/worklog/77")


class TestComments:
    def test_sent_comment_is_persisted_and_shown(self, cfg):
        log_workday(cfg)
        storage.append_jira_sync(
            cfg, DAY, "PROJ-1", 3600, "77", when(9, 0).isoformat(), comment="Angličtina"
        )

        items, _ = jira.day_worklogs(cfg, DAY)
        first = next(i for i in items if i.block_id == when(9, 0).isoformat())
        assert first.comment == "Angličtina"

    def test_comment_survives_delete_for_next_send(self, cfg):
        log_workday(cfg)
        block = when(9, 0).isoformat()
        storage.append_jira_sync(cfg, DAY, "PROJ-1", 3600, "77", block, comment="Angličtina")
        storage.append_jira_unsync(cfg, DAY, "PROJ-1", "77", block)

        items, _ = jira.day_worklogs(cfg, DAY)
        first = next(i for i in items if i.block_id == block)
        assert not first.is_sent  # zase neodesláno
        assert first.comment == "Angličtina"  # ale komentář zůstal pro příště

    def test_never_sent_block_has_no_forced_comment(self, cfg):
        log_workday(cfg)

        items, _ = jira.day_worklogs(cfg, DAY)
        proj2 = next(i for i in items if i.ticket == "PROJ-2")
        assert proj2.comment is None  # spadne na default (poznámky)

    def test_effective_comment_prefers_typed_over_notes(self):
        item = jira.WorklogItem("P-1", 900, when(9, 0), ["x"], "id", comment="moje", notes=["pozn"])
        assert item.effective_comment == "moje"

    def test_effective_comment_falls_back_to_notes(self):
        item = jira.WorklogItem("P-1", 900, when(9, 0), ["x"], "id", notes=["pozn1", "pozn2"])
        assert item.effective_comment == "pozn1; pozn2"


class TestSentSource:
    def test_sync_source_propagates_to_items(self, cfg):
        log_workday(cfg)
        storage.append_jira_sync(
            cfg, DAY, "PROJ-1", 3600, "5555", when(9, 0).isoformat(), source="tempo"
        )

        items, _ = jira.day_worklogs(cfg, DAY)

        assert items[0].worklog_source == "tempo"
        assert items[1].worklog_source == "jira"  # neodeslany ma vychozi


class TestDeleteWorklog:
    def test_deletes_via_api(self, cfg):
        opener = FakeOpener()

        jira.delete_worklog(cfg, "PROJ-1", "77", "ja@firma.cz", "token", opener=opener)

        request = opener.requests[0]
        assert request.full_url == "https://firma.atlassian.net/rest/api/3/issue/PROJ-1/worklog/77"
        assert request.get_method() == "DELETE"
        assert request.get_header("Authorization", "").startswith("Basic ")

    def test_delete_error_raises_jira_error(self, cfg):
        opener = FakeOpener(error=http_error(403))

        with pytest.raises(jira.JiraError, match="403"):
            jira.delete_worklog(cfg, "PROJ-1", "77", "ja@firma.cz", "token", opener=opener)


class TestFormatStarted:
    def test_milliseconds_and_colonless_offset(self):
        dt = datetime(2026, 6, 10, 9, 0, 5, 123000, tzinfo=TZ)

        assert jira.format_started(dt) == "2026-06-10T09:00:05.123+0200"


class TestParseSelection:
    def test_numbers(self):
        assert jira.parse_selection("1,3", 3) == [0, 2]

    def test_numbers_with_spaces(self):
        assert jira.parse_selection("2 3", 3) == [1, 2]

    def test_duplicates_collapse(self):
        assert jira.parse_selection("1,1", 3) == [0]

    def test_vse_selects_everything(self):
        assert jira.parse_selection("vse", 3) == [0, 1, 2]
        assert jira.parse_selection("vše", 2) == [0, 1]

    def test_empty_and_nic_select_nothing(self):
        assert jira.parse_selection("", 3) == []
        assert jira.parse_selection("nic", 3) == []

    def test_out_of_range_is_invalid(self):
        assert jira.parse_selection("4", 3) is None
        assert jira.parse_selection("0", 3) is None

    def test_garbage_is_invalid(self):
        assert jira.parse_selection("prvni", 3) is None


class TestCredentialsAndSite:
    def test_site_url_from_browse_url(self, cfg):
        assert jira.site_url(cfg) == "https://firma.atlassian.net"

    def test_invalid_base_url_raises(self, cfg):
        cfg["jira_base_url"] = ""

        with pytest.raises(jira.JiraError):
            jira.site_url(cfg)

    def test_missing_email_raises(self, cfg, token_file):
        cfg["jira_email"] = ""

        with pytest.raises(jira.JiraError, match="jira_email"):
            jira.load_credentials(cfg)

    def test_missing_token_file_raises(self, cfg, tmp_path, monkeypatch):
        monkeypatch.setattr(jira, "token_path", lambda: tmp_path / "neexistuje")

        with pytest.raises(jira.JiraError, match="token"):
            jira.load_credentials(cfg)

    def test_loads_email_and_stripped_token(self, cfg, token_file):
        assert jira.load_credentials(cfg) == ("ja@firma.cz", "tajny-token")


class TestSendWorklog:
    def test_posts_worklog_and_returns_id(self, cfg):
        item = jira.WorklogItem(
            ticket="PROJ-1",
            seconds=5400,
            started=when(9, 0),
            activities=["PROJ-1 oprava", "PROJ-1 review"],
            block_id=when(9, 0).isoformat(),
        )
        opener = FakeOpener(payload={"id": "42"})

        worklog_id = jira.send_worklog(cfg, item, "ja@firma.cz", "token", opener=opener)

        assert worklog_id == "42"
        request = opener.requests[0]
        assert request.full_url == "https://firma.atlassian.net/rest/api/3/issue/PROJ-1/worklog"
        expected_auth = base64.b64encode(b"ja@firma.cz:token").decode("ascii")
        assert request.get_header("Authorization") == f"Basic {expected_auth}"
        body = json.loads(request.data.decode("utf-8"))
        assert body["timeSpentSeconds"] == 5400
        assert body["started"] == "2026-06-10T09:00:00.000+0200"
        assert "comment" not in body  # bez poznamek zustava komentar prazdny

    def test_notes_become_default_comment(self, cfg):
        item = jira.WorklogItem(
            "PROJ-1", 900, when(9, 0), ["PROJ-1 x"], "id1", notes=["cekal jsem", "pak review"]
        )
        opener = FakeOpener()

        jira.send_worklog(cfg, item, "ja@firma.cz", "token", opener=opener)

        body = json.loads(opener.requests[0].data.decode("utf-8"))
        assert body["comment"]["content"][0]["content"][0]["text"] == "cekal jsem; pak review"

    def test_explicit_empty_comment_stays_empty(self, cfg):
        item = jira.WorklogItem(
            "PROJ-1", 900, when(9, 0), ["PROJ-1 x"], "id1", comment="", notes=["pozn"]
        )
        opener = FakeOpener()

        jira.send_worklog(cfg, item, "ja@firma.cz", "token", opener=opener)

        body = json.loads(opener.requests[0].data.decode("utf-8"))
        assert "comment" not in body

    def test_comment_override_replaces_activity_texts(self, cfg):
        item = jira.WorklogItem(
            "PROJ-1", 900, when(9, 0), ["PROJ-1 x"], "id1", comment="vlastní text"
        )
        opener = FakeOpener()

        jira.send_worklog(cfg, item, "ja@firma.cz", "token", opener=opener)

        body = json.loads(opener.requests[0].data.decode("utf-8"))
        assert body["comment"]["content"][0]["content"][0]["text"] == "vlastní text"

    def test_401_gives_credentials_hint(self, cfg):
        item = jira.WorklogItem("PROJ-1", 900, when(9, 0), ["PROJ-1 x"], "id1")
        opener = FakeOpener(error=http_error(401))

        with pytest.raises(jira.JiraError, match="401"):
            jira.send_worklog(cfg, item, "ja@firma.cz", "spatny", opener=opener)

    def test_other_http_error_includes_body(self, cfg):
        item = jira.WorklogItem("PROJ-1", 900, when(9, 0), ["PROJ-1 x"], "id1")
        opener = FakeOpener(error=http_error(400, b'{"errors":{"started":"spatny format"}}'))

        with pytest.raises(jira.JiraError, match="400"):
            jira.send_worklog(cfg, item, "ja@firma.cz", "token", opener=opener)


class TestRunSendCommand:
    def test_sends_selected_and_records_sync(self, cfg, token_file, capsys):
        log_workday(cfg)
        opener = FakeOpener(payload={"id": "77"})

        exit_code = jira.run_send_command(cfg, DAY, ask=lambda _p: "1", opener=opener)

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "OK PROJ-1" in out
        assert len(opener.requests) == 1
        events = storage.read_day_events(cfg, DAY)
        syncs = [e for e in events if e["type"] == "jira_sync"]
        assert syncs == [
            {
                "ts": syncs[0]["ts"],
                "type": "jira_sync",
                "ticket": "PROJ-1",
                "seconds": 3600,
                "worklog_id": "77",
                "start_ts": when(9, 0).isoformat(),
                "worklog_source": "jira",
                "comment": "zakladni pozn",
            }
        ]

    def test_second_run_offers_only_remaining_blocks(self, cfg, token_file, capsys):
        log_workday(cfg)
        jira.run_send_command(cfg, DAY, ask=lambda _p: "1", opener=FakeOpener())
        capsys.readouterr()

        jira.run_send_command(cfg, DAY, ask=lambda _p: "nic", opener=FakeOpener())

        out = capsys.readouterr().out
        assert "Uz v Jire: PROJ-1  09:00–10:00" in out
        assert "1. PROJ-1  09:00" not in out  # odeslany blok uz neni v nabidce
        assert "10:30–11:00" in out
        assert "PROJ-2" in out

    def test_nothing_selected_sends_nothing(self, cfg, token_file, capsys):
        log_workday(cfg)
        opener = FakeOpener()

        exit_code = jira.run_send_command(cfg, DAY, ask=lambda _p: "nic", opener=opener)

        assert exit_code == 0
        assert opener.requests == []
        assert "Nic neodeslano" in capsys.readouterr().out

    def test_invalid_selection_fails(self, cfg, token_file):
        log_workday(cfg)

        exit_code = jira.run_send_command(cfg, DAY, ask=lambda _p: "blabla", opener=FakeOpener())

        assert exit_code == 2

    def test_missing_credentials_fail_before_asking(self, cfg, tmp_path, monkeypatch):
        monkeypatch.setattr(jira, "token_path", lambda: tmp_path / "neexistuje")
        log_workday(cfg)

        def must_not_ask(_prompt):
            raise AssertionError("picker se nema ptat bez prihlaseni")

        assert jira.run_send_command(cfg, DAY, ask=must_not_ask) == 1

    def test_failed_send_keeps_block_pending(self, cfg, token_file, capsys):
        log_workday(cfg)
        opener = FakeOpener(error=http_error(403))

        exit_code = jira.run_send_command(cfg, DAY, ask=lambda _p: "1", opener=opener)

        assert exit_code == 1
        events = storage.read_day_events(cfg, DAY)
        assert [e for e in events if e["type"] == "jira_sync"] == []
        items, _ = jira.pending_worklogs(cfg, DAY)
        assert [i.ticket for i in items] == ["PROJ-1", "PROJ-1", "PROJ-2"]

    def test_empty_comment_is_rejected_locally(self, cfg, token_file, capsys):
        storage.append_start(cfg, "PROJ-9 bez poznamky", ts=when(9, 0))
        storage.append_stop(cfg, ts=when(10, 0))
        opener = FakeOpener()

        exit_code = jira.run_send_command(cfg, DAY, ask=lambda _p: "1", opener=opener)

        assert exit_code == 1
        assert opener.requests == []
        assert "prazdny komentar" in capsys.readouterr().err

    def test_no_pending_worklogs_reports_and_succeeds(self, cfg, token_file, capsys):
        exit_code = jira.run_send_command(cfg, DAY, ask=lambda _p: "vse")

        assert exit_code == 0
        assert "Zadne neodeslane worklogy" in capsys.readouterr().out

    def test_collapsed_activities_are_mentioned(self, cfg, token_file, capsys):
        cfg["round_times"] = True
        storage.append_start(cfg, "PROJ-9 kratka", ts=when(10, 2))
        storage.append_stop(cfg, ts=when(10, 7))

        jira.run_send_command(cfg, DAY, ask=lambda _p: "nic")

        out = capsys.readouterr().out
        assert "spadly na 0" in out
        assert "PROJ-9 kratka" in out

    def test_sent_blocks_listed_as_info(self, cfg, token_file, capsys):
        log_workday(cfg)
        storage.append_jira_sync(cfg, DAY, "PROJ-1", 3600, "77", when(9, 0).isoformat())

        jira.run_send_command(cfg, DAY, ask=lambda _p: "nic")

        out = capsys.readouterr().out
        assert "Uz v Jire: PROJ-1" in out
        assert "worklog 77" in out

    def test_warns_about_running_and_unticketed(self, cfg, token_file, capsys):
        storage.append_start(cfg, "schuzka", ts=when(9, 0))
        storage.append_start(cfg, "PROJ-1 prace", ts=when(10, 0))

        jira.run_send_command(cfg, DAY, ask=lambda _p: "nic")

        out = capsys.readouterr().out
        assert "neukoncena aktivita" in out
        assert "schuzka" in out


class TestTokenDecryptFailure:
    """Regrese nalezu #1: nedesifovatelny token = JiraError, ne ticha smrt vlakna."""

    def test_undecryptable_jira_token_raises_jiraerror(self, cfg, tmp_path, monkeypatch):
        # Platny base64, ale blob nepochazi z DPAPI tohoto uctu -> OSError.
        blob = base64.b64encode(b"tohle-dpapi-nerozsifruje").decode("ascii")
        path = tmp_path / "jira_token"
        path.write_text(f"DPAPI:{blob}", encoding="utf-8")
        monkeypatch.setattr(jira, "token_path", lambda: path)

        with pytest.raises(jira.JiraError, match="Nastavení"):
            jira.load_credentials(cfg)

    def test_corrupted_tempo_token_raises_jiraerror(self, tmp_path, monkeypatch):
        # Neplatny base64 za prefixem -> ValueError z b64decode.
        path = tmp_path / "tempo_token"
        path.write_text("DPAPI:%%%toto-neni-base64", encoding="utf-8")
        monkeypatch.setattr(jira, "tempo_token_path", lambda: path)

        with pytest.raises(jira.JiraError, match="dešifrovat"):
            jira.load_tempo_token()

    def test_plaintext_tempo_token_still_loads(self, tmp_path, monkeypatch):
        path = tmp_path / "tempo_token"
        path.write_text("obycejny-token\n", encoding="utf-8")
        monkeypatch.setattr(jira, "tempo_token_path", lambda: path)

        assert jira.load_tempo_token() == "obycejny-token"
