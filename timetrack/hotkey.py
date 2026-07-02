"""Parsing hotkey specs like ``"ctrl+alt+t"`` into Win32 RegisterHotKey values.

The actual registration and message loop live in :mod:`timetrack.tray`.
"""

MOD_ALT = 0x0001
MOD_CTRL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_MODIFIERS = {"alt": MOD_ALT, "ctrl": MOD_CTRL, "shift": MOD_SHIFT, "win": MOD_WIN}


def parse_hotkey(spec: str) -> tuple[int, int]:
    """Parse e.g. ``"ctrl+alt+t"`` into (modifier flags, virtual-key code)."""
    *modifier_names, key = spec.lower().split("+")
    modifiers = 0
    for name in modifier_names:
        if name not in _MODIFIERS:
            raise ValueError(f"Neznámý modifikátor: {name!r}")
        modifiers |= _MODIFIERS[name]
    if len(key) == 1 and key.isalnum():
        return modifiers, ord(key.upper())
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return modifiers, 0x70 + int(key[1:]) - 1
    raise ValueError(f"Neznámá klávesa: {key!r}")
