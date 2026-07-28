"""omni_sdk CLI 脚手架测试（M15.11）。

验证 ``python3 -m omni_sdk create <name>`` 生成的插件骨架：
- 目录结构（__init__.py / manifest.json / tools.py / tests/）
- __init__.py 含 ``<Name>Plugin(OmniPlugin)`` 子类
- manifest.json 经 ``parse_manifest`` 合法
- tests/test_plugin.py + tests/test_tools.py 存在且可被 pytest 收集
- 拒绝非 ``omni_`` 前缀的名字
- 拒绝已存在的目标目录
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from omni_sdk.cli import create_plugin, main


def _class_name(plugin_name: str) -> str:
    """omni_music -> MusicPlugin。"""
    parts = plugin_name[len("omni_") :].split("_")
    return "".join(p.capitalize() for p in parts) + "Plugin"


class TestCreateGeneratesStructure:
    def test_create_generates_directory_structure(self, tmp_path: Path) -> None:
        """create_plugin 生成 omni_<name>/ 目录与子文件。"""
        create_plugin("omni_music", tmp_path)
        plugin_dir = tmp_path / "omni_music"
        assert plugin_dir.is_dir()
        assert (plugin_dir / "__init__.py").is_file()
        assert (plugin_dir / "manifest.json").is_file()
        assert (plugin_dir / "tools.py").is_file()
        assert (plugin_dir / "tests").is_dir()
        assert (plugin_dir / "tests" / "__init__.py").is_file()
        assert (plugin_dir / "tests" / "test_plugin.py").is_file()
        assert (plugin_dir / "tests" / "test_tools.py").is_file()

    def test_create_generates_init_py_with_plugin_class(self, tmp_path: Path) -> None:
        """__init__.py 含 <Name>Plugin(OmniPlugin) 子类定义。"""
        create_plugin("omni_music", tmp_path)
        init_py = (tmp_path / "omni_music" / "__init__.py").read_text(encoding="utf-8")
        assert "class MusicPlugin(OmniPlugin)" in init_py
        # name 属性带类型注解（CLAUDE.md §一 类型注解约束）
        assert 'name: str = "omni_music"' in init_py
        assert "async def on_load" in init_py
        # 保留 register(ctx) 兼容入口
        assert "def register(ctx)" in init_py

    def test_create_generates_manifest_json(self, tmp_path: Path) -> None:
        """manifest.json 合法且 name=omni_<name>。"""
        from omni_sdk.manifest import parse_manifest, validate_manifest

        create_plugin("omni_music", tmp_path)
        data = json.loads(
            (tmp_path / "omni_music" / "manifest.json").read_text(encoding="utf-8")
        )
        manifest = parse_manifest(data)
        assert manifest.name == "omni_music"
        assert manifest.version == "0.1.0"
        assert manifest.description  # 非空
        assert "tools.register" in manifest.permissions
        # 软校验无错误
        errors = validate_manifest(manifest)
        assert errors == []

    def test_create_generates_test_files(self, tmp_path: Path) -> None:
        """tests/test_plugin.py + test_tools.py 含可运行测试骨架。"""
        create_plugin("omni_music", tmp_path)
        test_plugin = (tmp_path / "omni_music" / "tests" / "test_plugin.py").read_text(
            encoding="utf-8"
        )
        test_tools = (tmp_path / "omni_music" / "tests" / "test_tools.py").read_text(
            encoding="utf-8"
        )
        # test_plugin.py 含生命周期测试
        assert "def test_" in test_plugin
        assert "MusicPlugin" in test_plugin
        assert "on_load" in test_plugin
        # test_tools.py 含工具测试骨架
        assert "def test_" in test_tools

    def test_create_generates_tools_py(self, tmp_path: Path) -> None:
        """tools.py 含 TOOLS 列表与 register 函数骨架。"""
        create_plugin("omni_music", tmp_path)
        tools_py = (tmp_path / "omni_music" / "tools.py").read_text(encoding="utf-8")
        assert "TOOLS" in tools_py
        assert "def register(ctx)" in tools_py
        assert "register_tool" in tools_py


class TestCreateValidation:
    def test_create_rejects_non_omni_prefix(self, tmp_path: Path) -> None:
        """name 不以 omni_ 开头时拒绝。"""
        with pytest.raises(ValueError, match="omni_"):
            create_plugin("music", tmp_path)

    def test_create_rejects_invalid_name(self, tmp_path: Path) -> None:
        """name 含非法字符（大写/连字符）时拒绝。"""
        for bad in ["omni_Music", "omni-music", "omni_music!", "omni_"]:
            with pytest.raises((ValueError,)):
                create_plugin(bad, tmp_path)

    def test_create_rejects_existing_dir(self, tmp_path: Path) -> None:
        """目标目录已存在时拒绝（不覆盖）。"""
        (tmp_path / "omni_music").mkdir()
        with pytest.raises((FileExistsError, ValueError)):
            create_plugin("omni_music", tmp_path)


class TestMainEntry:
    def test_main_creates_plugin(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """main(argv) 解析参数并调用 create_plugin。"""
        monkeypatch.setattr(sys, "argv", ["omni_sdk", "create", "omni_music", "--target", str(tmp_path)])
        main()
        assert (tmp_path / "omni_music").is_dir()

    def test_main_rejects_non_omni_prefix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """main 对非 omni_ 前缀打印错误并以非零退出。"""
        monkeypatch.setattr(sys, "argv", ["omni_sdk", "create", "music", "--target", str(tmp_path)])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code != 0


class TestGeneratedPluginImportable:
    """生成的插件骨架可被 import 且 VoicePlugin 风格的 on_load 可调用。"""

    def test_generated_plugin_can_be_imported_and_loaded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """生成的 omni_<name> 包可被 import，MusicPlugin 可 on_load。"""
        import importlib
        import asyncio

        from omni_sdk.context import PluginContext
        from omni_sdk.event_bus import EventBus
        from omni_sdk.permissions import PermissionChecker
        from omni_sdk.registry import ToolRegistry

        create_plugin("omni_music", tmp_path)
        # 把 tmp_path 加入 sys.path 以便 import omni_music
        monkeypatch.syspath_prepend(str(tmp_path))
        # 清理可能缓存的 omni_music 模块
        for mod_name in list(sys.modules):
            if mod_name == "omni_music" or mod_name.startswith("omni_music."):
                sys.modules.pop(mod_name, None)
        module = importlib.import_module("omni_music")
        plugin = module.MusicPlugin()
        assert plugin.name == "omni_music"

        ctx = PluginContext(
            config={},
            event_bus=EventBus(),
            tool_registry=ToolRegistry(),
            permission_checker=PermissionChecker(allowed=["tools.register"]),
            plugin_name="omni_music",
        )
        asyncio.run(plugin.on_load(ctx))
        # 骨架默认注册一个 example_tool
        assert "music_status" in ctx.tool_registry.list_tools()
