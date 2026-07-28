"""LifecycleHost：插件生命周期管理（加载/卸载/拓扑排序/错误隔离/权限校验）。

加载流程：manifest 校验 → 权限校验 → 构造 PluginContext → on_load → register_tools → 注册到 PluginRegistry。
卸载流程：on_unload → 注销工具 → 取消事件订阅 → 从 PluginRegistry 移除（反向顺序）。
错误隔离：单个插件 on_load 失败记录日志，不阻塞其他插件。
"""

from __future__ import annotations

import logging
from typing import Any

from omni_sdk.context import PluginContext
from omni_sdk.event_bus import EventBus
from omni_sdk.manifest import Manifest, validate_manifest
from omni_sdk.permissions import PermissionChecker
from omni_sdk.plugin import OmniPlugin
from omni_sdk.registry import PluginRegistry, ToolRegistry


class LifecycleHost:
    """插件生命周期宿主：加载/卸载/拓扑排序/错误隔离。

    持有共享的 EventBus / ToolRegistry / PermissionChecker / logger，
    为每个插件构造独立的 PluginContext（含 plugin_name 命名空间 logger）。
    """

    def __init__(
        self,
        event_bus: EventBus,
        tool_registry: ToolRegistry,
        permission_checker: PermissionChecker,
        config_provider: dict[str, Any] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """构造 LifecycleHost。

        :param event_bus: 共享事件总线
        :param tool_registry: 共享工具注册表
        :param permission_checker: 权限校验器
        :param config_provider: 全局配置 dict，按 plugin_name 查 ``plugins.<name>`` 段
        :param logger: 可选 logger；默认 ``omni.sdk.lifecycle``
        """
        self.event_bus: EventBus = event_bus
        self.tool_registry: ToolRegistry = tool_registry
        self.permission_checker: PermissionChecker = permission_checker
        self._config_provider: dict[str, Any] = config_provider or {}
        self._logger: logging.Logger = logger or logging.getLogger("omni.sdk.lifecycle")
        self._registry: PluginRegistry = PluginRegistry()
        # 已加载插件按加载顺序记录（用于 unload_all 反向卸载）
        self._load_order: list[str] = []
        # 每个插件保留 sub_id 列表，便于 unload 时取消订阅
        self._plugin_subs: dict[str, list[str]] = {}
        # 每个插件注册的工具名列表，便于 unload 时注销
        self._plugin_tools: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # 单插件加载/卸载
    # ------------------------------------------------------------------
    async def load_plugin(self, plugin: OmniPlugin, manifest: Manifest) -> None:
        """加载单个插件：manifest 校验 → 权限校验 → on_load → register_tools。

        若 manifest.name 与 plugin.name 不一致，或权限严格模式下未授予，
        或 on_load 抛异常，均记录日志并跳过该插件，不影响后续。

        :param plugin: OmniPlugin 实例
        :param manifest: 对应的 Manifest 实例
        """
        # 1. manifest.name 与 plugin.name 必须一致
        if manifest.name != plugin.name:
            self._logger.error(
                "插件加载拒绝：manifest.name=%r 与 plugin.name=%r 不一致",
                manifest.name,
                plugin.name,
            )
            return

        # 2. manifest 软校验（仅记录 warning，不拒绝）
        soft_errors = validate_manifest(manifest)
        for err in soft_errors:
            self._logger.warning("插件 %s manifest 软校验: %s", manifest.name, err)

        # 3. 权限校验：所有 manifest.permissions 都必须被 permission_checker 授予
        denied = [
            perm
            for perm in manifest.permissions
            if not self.permission_checker.check(perm)
        ]
        if denied:
            self._logger.error(
                "插件 %s 因权限未授予被拒绝加载: %s", manifest.name, denied
            )
            return

        # 4. 若同名插件已加载，先卸载旧的（热替换语义）
        if self._registry.get(manifest.name) is not None:
            self._logger.info("插件 %s 已加载，先卸载旧实例再加载新实例", manifest.name)
            await self._do_unload(manifest.name)

        # 5. 构造 PluginContext
        plugin_config = self._get_plugin_config(manifest.name)
        ctx = PluginContext(
            config=plugin_config,
            event_bus=self.event_bus,
            tool_registry=self.tool_registry,
            permission_checker=self.permission_checker,
            plugin_name=manifest.name,
        )

        # 6. 调用 on_load（错误隔离）
        # 捕获 on_load 前的工具快照，用于追踪 on_load + register_tools 期间新增的工具
        # （LegacyPluginAdapter 等兼容适配层在 on_load 中经 register(ctx) 注册工具）
        before_tools = set(self.tool_registry.list_tools())
        try:
            await plugin.on_load(ctx)
        except Exception as exc:  # noqa: BLE001
            self._logger.error(
                "插件 %s on_load 失败，跳过加载: %s",
                manifest.name,
                exc,
                exc_info=True,
            )
            return

        # 7. 调用 register_tools（同步）
        # 捕获 register_tools 后的工具数差异（含 on_load 期间注册的工具），记录新增的工具名
        try:
            plugin.register_tools(ctx)
        except Exception as exc:  # noqa: BLE001
            self._logger.error(
                "插件 %s register_tools 失败: %s",
                manifest.name,
                exc,
                exc_info=True,
            )
        after_tools = set(self.tool_registry.list_tools())
        new_tools = sorted(after_tools - before_tools)
        self._plugin_tools[manifest.name] = new_tools

        # 8. 注册到 PluginRegistry 与加载顺序
        self._registry.register(plugin)
        if manifest.name not in self._load_order:
            self._load_order.append(manifest.name)
        self._plugin_subs.setdefault(manifest.name, [])
        self._logger.info("插件 %s 加载完成（v%s）", manifest.name, manifest.version)

    async def unload_plugin(self, name: str) -> None:
        """卸载单个插件：on_unload → 注销工具 → 从注册表移除。

        不存在时静默返回（幂等）。

        :param name: 插件 name
        """
        await self._do_unload(name)

    async def _do_unload(self, name: str) -> None:
        """实际卸载逻辑：on_unload → 注销工具 → 取消订阅 → 移除注册。"""
        plugin = self._registry.get(name)
        if plugin is None:
            return

        # 1. 调用 on_unload（错误隔离：失败仅记录日志）
        try:
            await plugin.on_unload()
        except Exception as exc:  # noqa: BLE001
            self._logger.error(
                "插件 %s on_unload 失败: %s", name, exc, exc_info=True
            )

        # 2. 注销该插件注册的工具
        for tool_name in self._plugin_tools.get(name, []):
            self.tool_registry.unregister_tool(tool_name)
        self._plugin_tools.pop(name, None)

        # 3. 取消该插件的事件订阅
        for sub_id in self._plugin_subs.get(name, []):
            self.event_bus.unsubscribe(sub_id)
        self._plugin_subs.pop(name, None)

        # 4. 从注册表与加载顺序移除
        self._registry.unregister(name)
        if name in self._load_order:
            self._load_order.remove(name)
        self._logger.info("插件 %s 已卸载", name)

    # ------------------------------------------------------------------
    # 批量加载/卸载
    # ------------------------------------------------------------------
    async def load_all(self, plugins: list[tuple[OmniPlugin, Manifest]]) -> None:
        """按 dependencies 拓扑排序后批量加载。

        :param plugins: [(plugin, manifest), ...] 列表，顺序任意
        """
        ordered = self._topological_sort(plugins)
        for plugin, manifest in ordered:
            await self.load_plugin(plugin, manifest)

    async def unload_all(self) -> None:
        """按加载顺序的逆序卸载全部插件。"""
        for name in reversed(list(self._load_order)):
            await self._do_unload(name)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def list_loaded_plugins(self) -> list[str]:
        """返回当前已加载插件名列表（按加载顺序）。"""
        return list(self._load_order)

    def get_plugin(self, name: str) -> OmniPlugin | None:
        """按名查找已加载插件。"""
        return self._registry.get(name)

    # ------------------------------------------------------------------
    # 拓扑排序
    # ------------------------------------------------------------------
    @staticmethod
    def _topological_sort(
        plugins: list[tuple[OmniPlugin, Manifest]],
    ) -> list[tuple[OmniPlugin, Manifest]]:
        """按 manifest.dependencies 拓扑排序。

        依赖未在加载列表中（如 omni_sdk 本身）的项被忽略（假定已加载）。
        若存在循环依赖，按出现顺序处理（不抛错）。

        :return: 排序后的 [(plugin, manifest), ...]
        """
        # name -> (plugin, manifest)
        by_name: dict[str, tuple[OmniPlugin, Manifest]] = {
            m.name: (p, m) for p, m in plugins
        }
        visited: set[str] = set()
        on_stack: set[str] = set()
        result: list[tuple[OmniPlugin, Manifest]] = []

        def _visit(name: str) -> None:
            if name in visited:
                return
            if name in on_stack:
                # 循环依赖：跳过避免无限递归
                return
            on_stack.add(name)
            entry = by_name.get(name)
            if entry is not None:
                _, manifest = entry
                for dep_name in manifest.dependencies.keys():
                    # 仅处理本批次内的依赖；外部依赖（omni_sdk 等）忽略
                    if dep_name in by_name:
                        _visit(dep_name)
            on_stack.discard(name)
            if name not in visited:
                visited.add(name)
                if entry is not None:
                    result.append(entry)

        # 按输入顺序遍历，保证稳定排序
        for plugin, manifest in plugins:
            _visit(manifest.name)

        return result

    # ------------------------------------------------------------------
    # 配置查找
    # ------------------------------------------------------------------
    def _get_plugin_config(self, plugin_name: str) -> dict[str, Any]:
        """从 config_provider 取 ``plugins.<plugin_name>`` 段。

        支持两种格式：
        - ``config_provider = {"plugins": {"omni_voice": {...}}}``
        - ``config_provider = {"omni_voice": {...}}``（直接平铺）
        """
        if not self._config_provider:
            return {}
        plugins_section = self._config_provider.get("plugins")
        if isinstance(plugins_section, dict) and plugin_name in plugins_section:
            cfg = plugins_section[plugin_name]
            return dict(cfg) if isinstance(cfg, dict) else {}
        if plugin_name in self._config_provider:
            cfg = self._config_provider[plugin_name]
            return dict(cfg) if isinstance(cfg, dict) else {}
        return {}
