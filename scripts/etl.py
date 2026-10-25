"""Download Elexon FUELHH (WIND) + WINDFOR into backend/data cache."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.elexon import download_and_cache  # noqa: E402


if __name__ == "__main__":
    download_and_cache()
