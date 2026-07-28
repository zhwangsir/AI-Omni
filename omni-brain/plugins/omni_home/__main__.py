"""``python -m omni_home`` 入口：转发到 cli.main 并以返回码退出。"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
