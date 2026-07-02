import pytest

from timetrack.hotkey import MOD_ALT, MOD_CTRL, MOD_SHIFT, MOD_WIN, parse_hotkey


def test_ctrl_alt_letter():
    assert parse_hotkey("ctrl+alt+t") == (MOD_CTRL | MOD_ALT, ord("T"))


def test_is_case_insensitive():
    assert parse_hotkey("CTRL+Alt+T") == (MOD_CTRL | MOD_ALT, ord("T"))


def test_win_shift_function_key():
    assert parse_hotkey("win+shift+f5") == (MOD_WIN | MOD_SHIFT, 0x74)


def test_digit_key():
    assert parse_hotkey("ctrl+1") == (MOD_CTRL, ord("1"))


def test_unknown_modifier_raises():
    with pytest.raises(ValueError):
        parse_hotkey("super+t")


def test_unknown_key_raises():
    with pytest.raises(ValueError):
        parse_hotkey("ctrl+totalniblbost")
