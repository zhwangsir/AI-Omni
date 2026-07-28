"""omni_sdk CLI：插件脚手架与运维工具（M15.11）。

子命令：
- ``create <name> [--target <dir>]``：在 ``<dir>/<name>/`` 下生成 ``OmniPlugin`` 骨架

生成的骨架结构（AGENTS.md §7.3）::

    <target>/<name>/
    ├── __init__.py          # <Name>Plugin(OmniPlugin) 子类 + register(ctx) 兼容入口
    ├── manifest.json        # 元数据 + 权限 + 事件 + 工具声明
    ├── tools.py             # TOOLS 列表 + register(ctx) 骨架（含一个示例工具）
    └── tests/
        ├── __init__.py
        ├── test_plugin.py   # 生命周期 + 元数据测试骨架
        └── test_tools.py    # 工具 handler 测试骨架

入口：``python3 -m omni_sdk create <name>``（见 ``__main__.py``）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# name 必须以 omni_ 开头，全小写蛇形（与 manifest.py _NAME_RE 对齐）
_NAME_RE = re.compile(r"^omni_[a-z][a-z0-9_]*$")


def _class_name(plugin_name: str) -> str:
    """把 ``omni_<name>`` 转为 ``<Name>Plugin`` 类名。

    ``omni_music`` → ``MusicPlugin``；``omni_test_plugin`` → ``TestPluginPlugin``。
    """
    parts = plugin_name[len("omni_") :].split("_")
    return "".join(p.capitalize() for p in parts) + "Plugin"


def _domain(plugin_name: str) -> str:
    """取 ``omni_<name>`` 的首个段作为工具前缀域。

    ``omni_music`` → ``music``；用于生成示例工具 ``<domain>_status``。
    """
    return plugin_name[len("omni_") :].split("_", 1)[0]


def _validate_name(name: str) -> None:
    """校验插件名：必须以 ``omni_`` 开头且为全小写 snake_case。"""
    if not _NAME_RE.match(name):
        raise ValueError(
            f"插件名必须以 omni_ 开头且为全小写 snake_case（如 omni_music），got: {name!r}"
        )


# ---------------------------------------------------------------------------
# 模板
# ---------------------------------------------------------------------------

_INIT_PY_TEMPLATE = '''"""{plugin_name}：自动生成的 omni_sdk 插件骨架（M15.11 脚手架）。

对外暴露两个入口：
- ``register(ctx)``：Hermes/WeBrain 旧式插件契约（向后兼容，经 tools.register 注册）
- ``{class_name}``：M15 ``OmniPlugin`` 子类，``on_load`` 用新式 API 注册 {domain}_* 工具

按需替换示例工具 ``{domain}_status`` 为真实业务逻辑。
"""

from __future__ import annotations

from typing import Any

from omni_sdk.context import PluginContext
from omni_sdk.plugin import OmniPlugin

__all__ = ["register", "{class_name}"]


def register(ctx) -> None:
    """Hermes/WeBrain 插件入口：把 {domain}_* tools 注册到插件上下文（旧式契约）。"""
    from .tools import register as _register

    _register(ctx)


class {class_name}(OmniPlugin):
    """{plugin_name} 的 OmniPlugin 子类（脚手架生成）。

    ``on_load(ctx)`` 用新式 ``ctx.register_tool`` API 注册 ``tools.TOOLS`` 中声明的工具；
    ``register(ctx)`` 旧式入口保留向后兼容（经 ``tools.register`` 走 legacy kwargs）。
    """

    name: str = "{plugin_name}"
    version: str = "0.1.0"
    description: str = "{plugin_name} 插件（脚手架生成，请替换描述）"
    emoji: str = "📦"

    async def on_load(self, ctx: PluginContext) -> None:
        """加载时把 tools.TOOLS 中声明的工具注册到 ctx.tool_registry。"""
        from .tools import TOOLS

        for meta in TOOLS:
            ctx.register_tool(
                name=meta["name"],
                description=meta["description"],
                emoji=meta["emoji"],
                schema=meta["schema"],
                handler_func=meta["handler_func"],
            )
'''


_TOOLS_PY_TEMPLATE = '''"""{plugin_name} 工具实现（脚手架生成，含一个示例工具 {domain}_status）。

工具统一返回 JSON 字符串 ``{{"ok": bool, "data": ..., "error": ...}}``（CLAUDE.md §二）。
按需新增更多 {domain}_* 工具并登记到 TOOLS 列表。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


# 工具元数据列表：每项含 name / description / emoji / schema / handler_func
TOOLS: list[dict[str, Any]] = []


def _ok(data: Any) -> str:
    """成功响应 JSON 字符串。"""
    return json.dumps({{"ok": True, "data": data}}, ensure_ascii=False)


def _err(message: str) -> str:
    """失败响应 JSON 字符串。"""
    return json.dumps({{"ok": False, "error": message}}, ensure_ascii=False)


def _handle_status(args: dict[str, Any]) -> str:
    """示例工具 {domain}_status 的 handler：返回固定状态。"""
    return _ok({{"plugin": "{plugin_name}", "status": "ok"}})


# 示例工具登记
TOOLS.append({{
    "name": "{domain}_status",
    "description": "查询 {plugin_name} 状态（示例工具）",
    "emoji": "📊",
    "schema": {{
        "name": "{domain}_status",
        "parameters": {{
            "type": "object",
            "properties": {{}},
            "required": [],
        }},
    }},
    "handler_func": _handle_status,
}})


def _make_handler(func: Callable) -> Callable:
    """把工具函数适配为 registry handler：``(args: dict, **kw) -> JSON 字符串``。"""

    def handler(args: dict[str, Any], **_: Any) -> str:
        return func(args)

    return handler


def register(ctx) -> None:
    """把 TOOLS 中所有工具注册到插件上下文。"""
    for meta in TOOLS:
        ctx.register_tool(
            name=meta["name"],
            toolset="{plugin_name}",
            schema=meta["schema"],
            handler=_make_handler(meta["handler_func"]),
            description=meta["description"],
            emoji=meta["emoji"],
        )
    bus = getattr(ctx, "event_bus", None)
    if bus is not None and callable(getattr(bus, "publish", None)):
        logger.info("{plugin_name} 已接入事件总线")
    logger.info("{plugin_name} 插件已注册 %d 个 tools", len(TOOLS))
'''


_TEST_PLUGIN_TEMPLATE = '''"""{plugin_name} 生命周期测试（脚手架生成）。

覆盖：元数据、on_load 注册工具、on_unload 幂等。
"""

from __future__ import annotations

import asyncio

import pytest

from omni_sdk.context import PluginContext
from omni_sdk.event_bus import EventBus
from omni_sdk.permissions import PermissionChecker
from omni_sdk.registry import ToolRegistry

from {plugin_name} import {class_name}, register


def _make_ctx() -> PluginContext:
    return PluginContext(
        config={{}},
        event_bus=EventBus(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(allowed=["tools.register"]),
        plugin_name="{plugin_name}",
    )


def test_plugin_metadata() -> None:
    plugin = {class_name}()
    assert plugin.name == "{plugin_name}"
    assert plugin.version


def test_plugin_on_load_registers_tools() -> None:
    plugin = {class_name}()
    ctx = _make_ctx()
    asyncio.run(plugin.on_load(ctx))
    assert "{domain}_status" in ctx.tool_registry.list_tools()


def test_plugin_on_unload_idempotent() -> None:
    plugin = {class_name}()
    asyncio.run(plugin.on_unload())
    asyncio.run(plugin.on_unload())


def test_register_legacy_ctx() -> None:
    class _LegacyCtx:
        def __init__(self) -> None:
            self.tools: list[dict] = []

        def register_tool(self, **kwargs):
            self.tools.append(kwargs)

    ctx = _LegacyCtx()
    register(ctx)
    assert any(t["name"] == "{domain}_status" for t in ctx.tools)
'''


_TEST_TOOLS_TEMPLATE = '''"""{plugin_name} 工具测试（脚手架生成）。

覆盖：handler 返回 JSON 字符串、ok 字段、错误响应。
"""

from __future__ import annotations

import json

from {plugin_name} import tools


def _parse(result: str) -> dict:
    assert isinstance(result, str)
    return json.loads(result)


def test_status_handler_returns_ok() -> None:
    handler = next(t["handler_func"] for t in tools.TOOLS if t["name"] == "{domain}_status")
    result = handler({{}})
    payload = _parse(result)
    assert payload["ok"] is True
    assert payload["data"]["status"] == "ok"


def test_tools_registered_count() -> None:
    assert len(tools.TOOLS) >= 1
    names = [t["name"] for t in tools.TOOLS]
    assert "{domain}_status" in names


def test_make_handler_wraps_function() -> None:
    wrapped = tools._make_handler(lambda args: tools._ok({{"echo": args}}))
    result = wrapped({{"k": "v"}}, extra="ignored")
    payload = _parse(result)
    assert payload["ok"] is True
    assert payload["data"]["echo"] == {{"k": "v"}}
'''


_TESTS_INIT_TEMPLATE = '''"""{plugin_name} 测试包。"""
'''


def _build_manifest(plugin_name: str, domain: str) -> dict[str, Any]:
    """构造 manifest.json dict。"""
    return {
        "name": plugin_name,
        "version": "0.1.0",
        "description": f"{plugin_name} 插件（脚手架生成，请替换描述）",
        "author": "AI-Omni",
        "permissions": ["tools.register"],
        "platforms": ["macos", "linux"],
        "dependencies": {"omni_sdk": ">=0.1.0"},
        "events": {
            "publishes": [f"{domain}.state_changed"],
            "subscribes": [],
        },
        "tools": [f"{domain}_status"],
    }


# ---------------------------------------------------------------------------
# create_plugin
# ---------------------------------------------------------------------------

def create_plugin(name: str, target_dir: Path) -> Path:
    """在 ``target_dir/<name>/`` 下生成 ``OmniPlugin`` 骨架。

    :param name: 插件名，必须以 ``omni_`` 开头且为全小写 snake_case
    :param target_dir: 父目录；会在其下创建 ``<name>/`` 子目录
    :return: 生成的插件目录 Path
    :raises ValueError: name 不合规
    :raises FileExistsError: 目标目录已存在
    """
    _validate_name(name)
    target_dir = Path(target_dir)
    plugin_dir = target_dir / name
    if plugin_dir.exists():
        raise FileExistsError(f"目标目录已存在：{plugin_dir}")

    cls = _class_name(name)
    domain = _domain(name)

    # 渲染模板
    init_py = _INIT_PY_TEMPLATE.format(plugin_name=name, class_name=cls, domain=domain)
    tools_py = _TOOLS_PY_TEMPLATE.format(plugin_name=name, domain=domain)
    test_plugin_py = _TEST_PLUGIN_TEMPLATE.format(
        plugin_name=name, class_name=cls, domain=domain
    )
    test_tools_py = _TEST_TOOLS_TEMPLATE.format(plugin_name=name, domain=domain)
    tests_init = _TESTS_INIT_TEMPLATE.format(plugin_name=name)
    manifest = _build_manifest(name, domain)

    # 创建目录与文件
    plugin_dir.mkdir(parents=True, exist_ok=False)
    (plugin_dir / "__init__.py").write_text(init_py, encoding="utf-8")
    (plugin_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (plugin_dir / "tools.py").write_text(tools_py, encoding="utf-8")
    tests_dir = plugin_dir / "tests"
    tests_dir.mkdir(exist_ok=False)
    (tests_dir / "__init__.py").write_text(tests_init, encoding="utf-8")
    (tests_dir / "test_plugin.py").write_text(test_plugin_py, encoding="utf-8")
    (tests_dir / "test_tools.py").write_text(test_tools_py, encoding="utf-8")

    return plugin_dir


# ---------------------------------------------------------------------------
# argparse 入口
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    """构造 argparse parser。"""
    parser = argparse.ArgumentParser(
        prog="omni_sdk",
        description="AI-Omni 插件 SDK CLI（M15.11 脚手架）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="生成 omni_<name> 插件骨架")
    create.add_argument("name", help="插件名（必须以 omni_ 开头，全小写 snake_case）")
    create.add_argument(
        "--target",
        default="omni-brain/plugins",
        help="父目录（默认 omni-brain/plugins/）",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    """CLI 入口：解析参数并分发子命令。

    :param argv: 参数列表；None 时取 ``sys.argv[1:]``
    :raises SystemExit: 参数错误或 name 不合规时以非零码退出
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "create":
        try:
            plugin_dir = create_plugin(args.name, Path(args.target))
        except ValueError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            raise SystemExit(1)
        except FileExistsError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            raise SystemExit(2)
        print(f"已生成插件骨架：{plugin_dir}")
        print(f"  - {plugin_dir / '__init__.py'}")
        print(f"  - {plugin_dir / 'manifest.json'}")
        print(f"  - {plugin_dir / 'tools.py'}")
        print(f"  - {plugin_dir / 'tests' / 'test_plugin.py'}")
        print(f"  - {plugin_dir / 'tests' / 'test_tools.py'}")
        return

    # 不应到达此处（subparsers required=True）
    parser.error("未知命令")
