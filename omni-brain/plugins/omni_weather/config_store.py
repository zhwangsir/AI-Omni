"""城市配置持久化：``~/.ai-omni/weather/config.json``。

存储当前城市与经纬度，便于跨进程恢复（CLI 子进程模式）。
env ``AI_OMNI_WEATHER_CONFIG`` 可覆盖路径（测试指向 tmp_path）。

写入采用临时文件 + ``os.replace`` 原子替换，避免读到半截 JSON。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

__all__ = ["get_config_path", "load_config", "save_config"]

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path.home() / ".ai-omni" / "weather" / "config.json"


def get_config_path() -> Path:
    """取 config.json 路径；env ``AI_OMNI_WEATHER_CONFIG`` 优先。"""
    env = os.environ.get("AI_OMNI_WEATHER_CONFIG")
    if env:
        return Path(env)
    return _DEFAULT_CONFIG_PATH


def load_config() -> dict[str, Any]:
    """读取 config.json；文件不存在或解析失败时返回空 dict。

    :return: 配置 dict（可能含 ``city`` / ``lat`` / ``lon``）
    """
    path = get_config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.debug("config 读取失败: %s", path, exc_info=True)
        return {}


def save_config(config: dict[str, Any]) -> None:
    """原子写入 config.json；父目录自动创建。

    :param config: 配置 dict
    """
    path = get_config_path()
    tmp: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001 - 配置写入失败不拖垮工具调用
        logger.debug("config 写入失败: %s", path, exc_info=True)
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
