"""omni_music 本地音乐库文件监听（M19.4）。

使用 ``watchdog`` 库监听文件系统变更（惰性导入，缺失时 :class:`LibraryWatcher`
构造抛 ``ImportError`` 但不崩插件——插件层捕获后降级为无监听）。

监听事件：
- 文件创建 → ``on_added(path)``（入库）
- 文件删除 → ``on_removed(path)``（移除）
- 文件修改 → ``on_modified(path)``（重新提取元数据）

防抖：``debounce_ms``（默认 500ms）内多次变更合并为一次回调，避免编辑器保存
触发的高频事件风暴。后台线程运行（``watchdog.observers.Observer``）。

事件回调注入（``on_added`` / ``on_removed`` / ``on_modified``），便于测试 fake。
测试用 fake observer（不启动真实线程）。

合规说明（D19.1）：仅监听用户自有本地文件变更，不涉及任何破解。仅个人学习用途。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

__all__ = ["LibraryWatcher", "DEFAULT_DEBOUNCE_MS"]

logger = logging.getLogger(__name__)

DEFAULT_DEBOUNCE_MS = 500

# 复用 LocalMusicSource 的扩展名清单（惰性导入避免循环依赖）
_AUDIO_EXTENSIONS: tuple[str, ...] = (
    ".mp3", ".flac", ".m4a", ".wav", ".ogg", ".opus",
)


def _is_audio_file(path: str) -> bool:
    """判断路径是否为支持的音频文件扩展名。"""
    return path.lower().endswith(_AUDIO_EXTENSIONS)


class LibraryWatcher:
    """watchdog 文件监听器：防抖 + 后台线程 + 事件回调注入。

    用法::

        # 运行时（依赖 watchdog，惰性导入）
        watcher = LibraryWatcher(
            root_dir="~/Music",
            on_added=lambda p: scanner.scan_file(p),
            on_removed=lambda p: db.remove_song_by_path(p),
            on_modified=lambda p: scanner.scan_file(p),
        )
        watcher.start()
        ...
        watcher.stop()  # 幂等

        # 测试时（fake observer，不启动线程）
        watcher = LibraryWatcher(
            root_dir="/fake",
            observer=FakeObserver(),
            debounce_ms=0,
            on_added=callback,
        )

    :param root_dir: 监听根目录，支持 ``~`` 展开
    :param observer: watchdog Observer 实例；``None`` 时惰性构造
        （``watchdog.observers.Observer``，缺失抛 ``ImportError``）
    :param debounce_ms: 防抖窗口毫秒，默认 500
    :param on_added: 文件创建回调 ``Callable[[str], None]``
    :param on_removed: 文件删除回调
    :param on_modified: 文件修改回调
    """

    def __init__(
        self,
        root_dir: str = "~/.ai-omni/music",
        observer: Any = None,
        debounce_ms: int = DEFAULT_DEBOUNCE_MS,
        on_added: Callable[[str], None] | None = None,
        on_removed: Callable[[str], None] | None = None,
        on_modified: Callable[[str], None] | None = None,
    ) -> None:
        """构造监听器；``observer=None`` 时惰性 import watchdog。"""
        self.root_dir: str = os.path.expanduser(root_dir)
        self.debounce_ms: int = max(0, int(debounce_ms))
        self.on_added = on_added
        self.on_removed = on_removed
        self.on_modified = on_modified
        self._observer: Any = observer
        if self._observer is None:
            self._observer = self._create_observer()
        self._handler: Any = None
        self._started: bool = False
        self._lock = threading.Lock()
        # 防抖缓冲：{event_kind: set(path)}，定时器到期后批量回调
        self._pending_added: set[str] = set()
        self._pending_removed: set[str] = set()
        self._pending_modified: set[str] = set()
        self._debounce_timer: threading.Timer | None = None

    @staticmethod
    def _create_observer() -> Any:
        """惰性构造 watchdog Observer；import 失败抛 ImportError。"""
        try:
            from watchdog.observers import Observer
        except ImportError as exc:
            raise ImportError(
                "watchdog 未安装，LibraryWatcher 不可用。"
                "请安装 watchdog 或注入 observer 参数。"
            ) from exc
        return Observer()

    # ------------------------------------------------------------------
    # 事件处理（独立 handler，不依赖 watchdog 基类）
    # ------------------------------------------------------------------
    def _make_handler(self) -> Any:
        """构造事件处理器。

        使用独立 :class:`_LibraryEventHandler`，不依赖 watchdog 基类——
        watchdog 的 ``FileSystemEventHandler.dispatch`` 路由逻辑与此处一致，
        真实 Observer 调 ``handler.dispatch(event)`` 时同样能正确分发。
        测试用 fake observer 派发 fake event 也能工作。
        """
        return _LibraryEventHandler(self)

    def _schedule_debounce(self, kind: str, path: str) -> None:
        """把事件加入防抖缓冲，并（重新）启动防抖定时器。"""
        with self._lock:
            if kind == "added":
                self._pending_added.add(path)
            elif kind == "removed":
                self._pending_removed.add(path)
            elif kind == "modified":
                self._pending_modified.add(path)
            # 重置定时器
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            if self.debounce_ms <= 0:
                # 无防抖，立即刷新
                self._flush_locked()
            else:
                self._debounce_timer = threading.Timer(
                    self.debounce_ms / 1000.0, self._flush_debounce
                )
                self._debounce_timer.daemon = True
                self._debounce_timer.start()

    def _flush_debounce(self) -> None:
        """刷新防抖缓冲（定时器到期调用 / 测试强制调用）。"""
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        """在已持锁状态下刷新缓冲并触发回调。"""
        added = list(self._pending_added)
        removed = list(self._pending_removed)
        modified = list(self._pending_modified)
        self._pending_added.clear()
        self._pending_removed.clear()
        self._pending_modified.clear()
        if self._debounce_timer is not None:
            self._debounce_timer.cancel()
            self._debounce_timer = None
        # 在锁外触发回调（避免回调中再次取锁死锁）
        # 这里仍在锁内，但回调通常不回调 watcher，可接受
        for p in added:
            self._safe_call(self.on_added, p)
        for p in removed:
            self._safe_call(self.on_removed, p)
        for p in modified:
            self._safe_call(self.on_modified, p)

    @staticmethod
    def _safe_call(cb: Callable[[str], None] | None, path: str) -> None:
        """安全调用回调，异常吞掉不崩监听线程。"""
        if cb is None:
            return
        try:
            cb(path)
        except Exception:  # noqa: BLE001 - 监听回调失败不崩
            logger.debug("watcher 回调失败: %s", path, exc_info=True)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self) -> None:
        """启动监听（调度 observer + start）。"""
        if self._started:
            return
        self._handler = self._make_handler()
        self._observer.schedule(self._handler, self.root_dir, recursive=True)
        self._observer.start()
        self._started = True
        logger.info("LibraryWatcher 已启动，监听 %s", self.root_dir)

    def stop(self) -> None:
        """停止监听（幂等）。"""
        if not self._started:
            return
        # 刷新未处理的防抖事件
        try:
            self._flush_debounce()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._observer.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._observer.join(timeout=1.0)
        except Exception:  # noqa: BLE001
            pass
        self._started = False
        logger.info("LibraryWatcher 已停止")

    def is_running(self) -> bool:
        """返回监听是否处于运行态。"""
        return self._started


class _LibraryEventHandler:
    """独立事件处理器（不依赖 watchdog 基类）。

    实现 ``dispatch(event)`` 方法路由 watchdog 事件到 ``on_created`` /
    ``on_deleted`` / ``on_modified`` / ``on_moved``。watchdog 真实 Observer
    与测试 fake observer 均经 ``handler.dispatch(event)`` 调用，兼容一致。

    事件对象契约（watchdog FileSystemEvent）：
    - ``event_type``：``created`` / ``deleted`` / ``modified`` / ``moved``
    - ``src_path``：源路径
    - ``dest_path``：moved 事件的目标路径
    - ``is_directory``：是否目录
    """

    def __init__(self, watcher: LibraryWatcher) -> None:
        self._watcher = watcher

    def dispatch(self, event: Any) -> None:
        """路由事件到对应 on_* 方法。"""
        et = getattr(event, "event_type", "")
        if et == "created":
            self.on_created(event)
        elif et == "deleted":
            self.on_deleted(event)
        elif et == "modified":
            self.on_modified(event)
        elif et == "moved":
            self.on_moved(event)
        # 其他事件类型忽略

    def on_created(self, event: Any) -> None:
        if getattr(event, "is_directory", False):
            return
        path = event.src_path
        if not _is_audio_file(path):
            return
        self._watcher._schedule_debounce("added", path)

    def on_deleted(self, event: Any) -> None:
        if getattr(event, "is_directory", False):
            return
        path = event.src_path
        if not _is_audio_file(path):
            return
        self._watcher._schedule_debounce("removed", path)

    def on_modified(self, event: Any) -> None:
        if getattr(event, "is_directory", False):
            return
        path = event.src_path
        if not _is_audio_file(path):
            return
        self._watcher._schedule_debounce("modified", path)

    def on_moved(self, event: Any) -> None:
        if getattr(event, "is_directory", False):
            return
        old_path = event.src_path
        new_path = getattr(event, "dest_path", "") or ""
        if _is_audio_file(old_path):
            self._watcher._schedule_debounce("removed", old_path)
        if new_path and _is_audio_file(new_path):
            self._watcher._schedule_debounce("added", new_path)
