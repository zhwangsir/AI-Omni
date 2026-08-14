"""omni_weather.config_store 覆盖率补测（M32.24）。

针对既有未覆盖降级路径：
- ``load_config`` 读取失败降级（非法 JSON / OSError）→ 返回 ``{}``
- ``save_config`` 写入失败 → 吞异常并清理临时文件
- 正常读写 roundtrip

全部经 ``AI_OMNI_WEATHER_CONFIG`` 指向 tmp_path，零真实用户目录、零网络。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from omni_weather import config_store
from omni_weather.config_store import load_config, save_config


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 config 路径指到 tmp_path 下的 config.json。"""
    path = tmp_path / "config.json"
    monkeypatch.setenv("AI_OMNI_WEATHER_CONFIG", str(path))
    return path


class TestLoadConfigFailure:
    def test_load_config_invalid_json_returns_empty(self, config_path: Path) -> None:
        """文件存在但内容为非法 JSON 时，load_config 降级返回 {}。"""
        config_path.write_text("{not valid json!!!", encoding="utf-8")
        assert load_config() == {}

    def test_load_config_oserror_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """config 路径是目录时，read_text 抛 IsADirectoryError（OSError 子类），降级返回 {}。"""
        config_dir = tmp_path / "config_as_dir"
        config_dir.mkdir()
        monkeypatch.setenv("AI_OMNI_WEATHER_CONFIG", str(config_dir))
        assert load_config() == {}


class TestSaveConfigFailure:
    def test_save_config_failure_cleans_tmp_and_swallows(
        self, config_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """os.replace 抛 OSError 时：save_config 不抛异常，且目录下无残留 .tmp 文件。"""
        monkeypatch.setattr(
            config_store.os,
            "replace",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
        )
        # 不抛异常
        save_config({"city": "上海", "lat": 31.23, "lon": 121.47})
        # 目标文件未生成
        assert not config_path.exists()
        # 临时文件已清理
        leftovers = list(tmp_path.glob(".config.json.*.tmp"))
        assert leftovers == []


class TestRoundTrip:
    def test_save_and_load_roundtrip(self, config_path: Path) -> None:
        """正常写入后可读回（原子替换路径）。"""
        cfg = {"city": "上海", "lat": 31.23, "lon": 121.47}
        save_config(cfg)
        assert config_path.exists()
        assert load_config() == cfg

    def test_load_config_missing_file_returns_empty(self, config_path: Path) -> None:
        """config 文件不存在时返回 {}。"""
        assert load_config() == {}
