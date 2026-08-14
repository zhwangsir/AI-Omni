"""omni_openclaw 插件入口契约测试（M32.24）。

覆盖 ``omni_openclaw/__init__.py`` 的两个未覆盖路径：
- ``register(ctx)`` 惰性导入函数体（``from .tools import register``）
- ``OpenClawPlugin.__init__``（compat 层 wiring）

只调用 ``register`` 本身做注册断言，**不调用任何 handler**（避免网络）。
"""

from __future__ import annotations

from typing import Any

import omni_openclaw
from omni_openclaw import OpenClawPlugin


class FakeContext:
    """模拟 Hermes/WeBrain 插件上下文（与 test_tools.py 中的 FakeContext 同构）。"""

    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []

    def register_tool(
        self,
        name: str,
        description: str,
        emoji: str,
        schema: dict[str, Any],
        handler_func: Any,
    ) -> None:
        self.tools.append(
            {
                "name": name,
                "description": description,
                "emoji": emoji,
                "schema": schema,
                "handler": handler_func,
            }
        )


class TestRegister:
    def test_register_registers_tools(self) -> None:
        """register(ctx) 惰性导入 .tools.register 并注册 openclaw_* 工具。"""
        ctx = FakeContext()
        omni_openclaw.register(ctx)
        names = {t["name"] for t in ctx.tools}
        assert "openclaw_health" in names
        assert "openclaw_chat" in names


class TestPluginClassWiring:
    def test_plugin_class_wiring(self) -> None:
        """OpenClawPlugin 元数据齐备，compat 层持有的 register_func 即 omni_openclaw.register。"""
        plugin = OpenClawPlugin()
        assert plugin.name == "omni_openclaw"
        assert plugin.version
        assert plugin.description
        assert plugin.emoji
        # RegisterCompatPlugin（LegacyPluginAdapter）双名存储 _register_func/_register_fn
        assert plugin._register_func is omni_openclaw.register
        assert plugin._register_fn is omni_openclaw.register
