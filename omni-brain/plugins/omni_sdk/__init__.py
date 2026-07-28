"""omni_sdk：AI-Omni 插件 SDK 核心包。

公开 API：
- :class:`OmniPlugin`：插件基类
- :class:`PluginContext`：注入到 on_load 的上下文
- :class:`EventBus`：事件总线
- :class:`Manifest` / :class:`Events` / :func:`parse_manifest` / :func:`validate_manifest` / :class:`ManifestError`
- :class:`PermissionChecker`：权限校验器
- :class:`Tool` / :class:`ToolRegistry` / :class:`PluginRegistry`
- :class:`LifecycleHost`：生命周期管理
- :class:`LegacyPluginAdapter` / :func:`wrap_legacy_plugin`：register(ctx) 兼容适配层（M15.9+）
- :class:`TaskTracker` / :func:`create_tracked_task` / :func:`safe_publish` / :func:`sync_to_async_publish`：异步工具
- :class:`SystemPluginBase`：系统插件公共基类

参考：AGENTS.md §7 / CLAUDE.md §2.1。
"""

from __future__ import annotations

from omni_sdk.compat import LegacyPluginAdapter, wrap_legacy_plugin
from omni_sdk.context import PluginContext
from omni_sdk.debounce import DebouncedWriter
from omni_sdk.event_bus import EventBus
from omni_sdk.identity import AssistantIdentity, DEFAULT_IDENTITY, get_identity
from omni_sdk.lifecycle import LifecycleHost
from omni_sdk.manifest import (
    Events,
    Manifest,
    ManifestError,
    parse_manifest,
    validate_manifest,
)
from omni_sdk.permissions import PermissionChecker
from omni_sdk.plugin import OmniPlugin
from omni_sdk.registry import PluginRegistry, Tool, ToolRegistry
from omni_sdk.system_plugin import SystemPluginBase
from omni_sdk.utils import (
    TaskTracker,
    create_tracked_task,
    safe_publish,
    sync_to_async_publish,
)

__all__ = [
    "OmniPlugin",
    "PluginContext",
    "EventBus",
    "Manifest",
    "Events",
    "ManifestError",
    "parse_manifest",
    "validate_manifest",
    "PermissionChecker",
    "Tool",
    "ToolRegistry",
    "PluginRegistry",
    "LifecycleHost",
    "LegacyPluginAdapter",
    "wrap_legacy_plugin",
    "TaskTracker",
    "create_tracked_task",
    "safe_publish",
    "sync_to_async_publish",
    "SystemPluginBase",
    "DebouncedWriter",
    "AssistantIdentity",
    "DEFAULT_IDENTITY",
    "get_identity",
]
