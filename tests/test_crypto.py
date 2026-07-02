from timetrack import crypto


def test_protect_unprotect_round_trips():
    assert crypto.unprotect(crypto.protect("tajny-token-123")) == "tajny-token-123"


def test_protect_produces_opaque_bytes():
    blob = crypto.protect("ABCD")
    assert b"ABCD" not in blob  # nesmi byt citelne


def test_write_then_read_round_trips(tmp_path):
    path = tmp_path / "jira_token"

    crypto.write_secret(path, "muj-token")

    on_disk = path.read_text(encoding="utf-8")
    assert on_disk.startswith(crypto.PREFIX)
    assert "muj-token" not in on_disk  # zasifrovano
    assert crypto.read_secret(path) == "muj-token"


def test_read_legacy_plaintext_still_works(tmp_path):
    path = tmp_path / "jira_token"
    path.write_text("stary-plaintext-token\n", encoding="utf-8")

    assert crypto.read_secret(path) == "stary-plaintext-token"


def test_read_missing_file_is_empty(tmp_path):
    assert crypto.read_secret(tmp_path / "neexistuje") == ""


def test_write_empty_removes_file(tmp_path):
    path = tmp_path / "jira_token"
    crypto.write_secret(path, "neco")

    crypto.write_secret(path, "   ")

    assert not path.exists()
