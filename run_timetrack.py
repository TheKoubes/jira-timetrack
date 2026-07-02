"""PyInstaller entry point — spustí TimeTrack (bez argumentů = GUI na pozadí)."""

import sys

from timetrack.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
