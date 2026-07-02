"""One-off generator of assets/timetrack.ico (32x32, clock face), stdlib only.

Run from the project root:  python tools/make_icon.py
"""

import struct
from pathlib import Path

SIZE = 32
FACE = (176, 102, 30, 255)  # BGRA steel blue
WHITE = (255, 255, 255, 255)
TRANSPARENT = (0, 0, 0, 0)


def pixel(x: int, y: int) -> tuple[int, int, int, int]:
    dx, dy = x - 15.5, y - 15.5
    distance = (dx * dx + dy * dy) ** 0.5
    if distance > 14.5:
        return TRANSPARENT
    if distance >= 12.5:
        return WHITE  # rim
    if 15 <= x <= 16 and 6 <= y <= 16:
        return WHITE  # minute hand (up)
    if 15 <= y <= 16 and 16 <= x <= 23:
        return WHITE  # hour hand (right)
    return FACE


def build_ico() -> bytes:
    xor = b"".join(
        bytes(pixel(x, y)) for y in range(SIZE - 1, -1, -1) for x in range(SIZE)
    )  # bottom-up BGRA rows
    and_mask = b"\x00" * (SIZE * 4)  # 1bpp rows padded to 4 bytes; alpha does the work
    dib = struct.pack(
        "<IiiHHIIiiII", 40, SIZE, SIZE * 2, 1, 32, 0, len(xor) + len(and_mask), 0, 0, 0, 0
    )
    image = dib + xor + and_mask
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", SIZE, SIZE, 0, 0, 1, 32, len(image), 22)
    return header + entry + image


if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent / "assets" / "timetrack.ico"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(build_ico())
    print(f"Zapsano: {target} ({target.stat().st_size} B)")
