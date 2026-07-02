from timetrack import config, ticketcache


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "default_config_path", lambda: tmp_path / ".timetrack" / "config.json")

    ticketcache.save_names({"PROJ-1": "Oprava", "19ABC0100000007-24": "Sebevzdělávání"})

    assert ticketcache.load_names() == {
        "PROJ-1": "Oprava",
        "19ABC0100000007-24": "Sebevzdělávání",
    }


def test_load_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "default_config_path", lambda: tmp_path / ".timetrack" / "config.json")

    assert ticketcache.load_names() == {}


def test_load_corrupt_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "default_config_path", lambda: tmp_path / ".timetrack" / "config.json")
    path = tmp_path / ".timetrack" / "ticket_names.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ rozbity json", encoding="utf-8")

    assert ticketcache.load_names() == {}


def test_save_leaves_no_temp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "default_config_path", lambda: tmp_path / ".timetrack" / "config.json")

    ticketcache.save_names({"PROJ-1": "Oprava"})

    leftovers = [p.name for p in (tmp_path / ".timetrack").iterdir() if p.name != "ticket_names.json"]
    assert leftovers == []


def test_failed_replace_keeps_old_cache_intact(tmp_path, monkeypatch):
    # Regrese nalezu #4: zapis je atomicky — kdyz vymena selze, stara cache
    # zustane cela (zadny napul prepsany soubor) a docasny soubor se uklidi.
    monkeypatch.setattr(config, "default_config_path", lambda: tmp_path / ".timetrack" / "config.json")
    ticketcache.save_names({"PROJ-1": "Oprava"})

    import os as os_module

    def boom(src, dst):
        raise OSError("simulovany souboj o soubor")

    monkeypatch.setattr(ticketcache.os, "replace", boom)
    ticketcache.save_names({"PROJ-2": "Nova"})  # nesmi spadnout ani nic rozbit
    monkeypatch.setattr(ticketcache.os, "replace", os_module.replace)

    assert ticketcache.load_names() == {"PROJ-1": "Oprava"}
    leftovers = [p.name for p in (tmp_path / ".timetrack").iterdir() if p.name != "ticket_names.json"]
    assert leftovers == []
