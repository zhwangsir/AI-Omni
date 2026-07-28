"""项目根 pytest 配置。

omni-brain 目录名含连字符，不是合法的 Python 包名，
因此将 omni-brain/plugins 插入 sys.path，使插件以顶层包
``omni_voice`` 的形式被测试与 CLI 导入。
"""

import sys
from pathlib import Path

_PLUGINS_DIR = Path(__file__).resolve().parent / "omni-brain" / "plugins"
if _PLUGINS_DIR.is_dir() and str(_PLUGINS_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGINS_DIR))
