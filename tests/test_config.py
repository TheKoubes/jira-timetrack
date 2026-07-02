import json

from timetrack import config


def test_creates_config_file_with_defaults_when_missing(tmp_path):
    config_path = tmp_path / ".timetrack" / "config.json"

    cfg = config.load_config(config_path)

    assert config_path.exists()
    assert cfg["filename_format"] == "%Y-%m-%d.jsonl"
    assert cfg["summary_filename_format"] == "%Y-%m-%d-summary.md"
    assert cfg["hotkey"] == "ctrl+alt+t"
    assert cfg["data_dir"].endswith("TimeTrack")


def test_loads_custom_values(tmp_path):
    config_path = tmp_path / "config.json"
    custom = {
        "data_dir": "D:\\evidence",
        "filename_format": "den-%d-%m-%Y.jsonl",
        "summary_filename_format": "sumar-%Y-%m-%d.md",
        "hotkey": "ctrl+shift+x",
    }
    config_path.write_text(json.dumps(custom), encoding="utf-8")

    cfg = config.load_config(config_path)

    assert custom.items() <= cfg.items()


def test_missing_keys_fall_back_to_defaults(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"hotkey": "win+j"}), encoding="utf-8")

    cfg = config.load_config(config_path)

    assert cfg["hotkey"] == "win+j"
    assert cfg["filename_format"] == "%Y-%m-%d.jsonl"


def test_defaults_include_rounding_and_jira_url(tmp_path):
    cfg = config.load_config(tmp_path / "config.json")

    assert cfg["rounding_minutes"] == 15
    assert cfg["rounding_mode"] == "nearest"
    # Generická verze: zadna firemni URL, prazdne account pole = auto-discovery.
    assert cfg["jira_base_url"] == ""
    assert cfg["jira_account_field"] == ""


def test_defaults_include_week_summary_filename_format(tmp_path):
    cfg = config.load_config(tmp_path / "config.json")

    assert cfg["week_summary_filename_format"] == "%G-W%V-summary.md"


def test_auto_stop_defaults_are_off(tmp_path):
    cfg = config.load_config(tmp_path / "config.json")

    assert cfg["auto_stop_on_lock"] is False
    assert cfg["auto_stop_on_suspend"] is False
    assert cfg["auto_stop_on_logoff"] is False


def test_missing_keys_are_written_back_to_existing_file(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"hotkey": "win+j"}), encoding="utf-8")

    config.load_config(config_path)

    on_disk = json.loads(config_path.read_text(encoding="utf-8"))
    assert on_disk["hotkey"] == "win+j"
    assert on_disk["rounding_minutes"] == 15
    assert "jira_base_url" in on_disk  # i prazdny default se do souboru dopise


def test_stored_jira_values_win_over_defaults(tmp_path):
    # Pojistka pro generalizaci (ROADMAP krok B): jira hodnoty, ktere si
    # instalace jednou zapsala do souboru, musi prezit i zmenu defaultu
    # v kodu — jinak by generic verze rozbila odesilani u stavajicich uzivatelu.
    config_path = tmp_path / "config.json"
    stored = {
        "jira_base_url": "https://firma.atlassian.net/browse/",
        "jira_account_field": "customfield_99999",
    }
    config_path.write_text(json.dumps(stored), encoding="utf-8")

    cfg = config.load_config(config_path)

    assert cfg["jira_base_url"] == "https://firma.atlassian.net/browse/"
    assert cfg["jira_account_field"] == "customfield_99999"
    on_disk = json.loads(config_path.read_text(encoding="utf-8"))
    assert on_disk["jira_base_url"] == "https://firma.atlassian.net/browse/"
    assert on_disk["jira_account_field"] == "customfield_99999"


def test_update_config_changes_keys_and_preserves_rest(tmp_path):
    config_path = tmp_path / "config.json"
    config.load_config(config_path)

    merged = config.update_config({"hotkey": "win+j", "rounding_minutes": 30}, config_path)

    assert merged["hotkey"] == "win+j"
    assert merged["rounding_minutes"] == 30
    on_disk = json.loads(config_path.read_text(encoding="utf-8"))
    assert on_disk["hotkey"] == "win+j"
    assert on_disk["rounding_minutes"] == 30
    assert on_disk["jira_base_url"] == ""  # nedotcene klice zustavaji


def test_update_config_keeps_unknown_keys(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"hotkey": "ctrl+alt+t", "muj_klic": 42}), encoding="utf-8")

    config.update_config({"hotkey": "win+k"}, config_path)

    on_disk = json.loads(config_path.read_text(encoding="utf-8"))
    assert on_disk["muj_klic"] == 42  # neznámý klíč nesmí zmizet
    assert on_disk["hotkey"] == "win+k"


def test_complete_file_is_not_rewritten(tmp_path):
    config_path = tmp_path / "config.json"
    config.load_config(config_path)
    before = config_path.stat().st_mtime_ns
    custom_text = config_path.read_text(encoding="utf-8")

    config.load_config(config_path)

    assert config_path.read_text(encoding="utf-8") == custom_text
    assert config_path.stat().st_mtime_ns == before
