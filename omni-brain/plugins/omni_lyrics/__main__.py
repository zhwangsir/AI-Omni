"""omni_lyrics 包入口：``python -m omni_lyrics <子命令>``。"""

from __future__ import annotations

import sys

from omni_lyrics.cli import main

if __name__ == "__main__":
    sys.exit(main())
