"""omni_music library.watcher watchdog 文件监听测试（M19.4）。

TDD 测试先行：覆盖 LibraryWatcher 的生命周期、防抖、事件回调、stop 幂等。
全部用 fake observer（不启动真实线程，不依赖 watchdog 库）。
watchdog 缺失时构造抛 ImportError 但测试用注入的 observer 不受影响。
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from omni_music.library.watcher import LibraryWatcher


# ---------------------------------------------------------------------------
# Fake observer / event handler（不启动真实线程）
# ---------------------------------------------------------------------------


class FakeObserver:
    """假 watchdog Observer：记录 schedule/start/stop 调用，不启动线程。"""

    def __init__(self) -> None:
        self.scheduled: list[tuple[str, bool]] = []  # (path, recursive)
        self.started: bool = False
        self.stopped: bool = False
        self.stop_call_count: int = 0
        self._handlers: dict[str, list] = {}

    def schedule(self, handler, path: str, recursive: bool = False) -> None:
        self.scheduled.append((path, recursive))
        self._handlers.setdefault(path, []).append(handler)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True
        self.stop_call_count += 1

    def join(self, timeout: float | None = None) -> None:
        """no-op（假 observer 无线程）。"""

    def is_alive(self) -> bool:
        return self.started and not self.stopped


class FakeFileSystemEvent:
    """假 watchdog FileSystemEvent。"""

    def __init__(self, event_type: str, src_path: str, is_directory: bool = False) -> None:
        self.event_type = event_type  # created / deleted / modified / moved
        self.src_path = src_path
        self.is_directory = is_directory
        self.dest_path = ""


def _dispatch(handler, event_type: str, path: str) -> None:
    """向 handler 派发一个事件。"""
    event = FakeFileSystemEvent(event_type, path)
    # watchdog EventHandler 的 dispatch 方法分发到 on_created/on_deleted 等
    handler.dispatch(event)


# ===========================================================================
# 构造与生命周期
# ===========================================================================
class TestLifecycle:
    def test_start_schedules_and_starts_observer(self, tmp_path: Path) -> None:
        """start 调度 observer 到 root_dir 并启动。"""
        obs = FakeObserver()
        w = LibraryWatcher(root_dir=str(tmp_path), observer=obs, debounce_ms=0)
        w.start()
        assert obs.started is True
        assert len(obs.scheduled) == 1
        assert obs.scheduled[0][0] == str(tmp_path)
        assert obs.scheduled[0][1] is True  # recursive
        w.stop()

    def test_stop_stops_observer(self, tmp_path: Path) -> None:
        obs = FakeObserver()
        w = LibraryWatcher(root_dir=str(tmp_path), observer=obs, debounce_ms=0)
        w.start()
        w.stop()
        assert obs.stopped is True

    def test_stop_is_idempotent(self, tmp_path: Path) -> None:
        """stop 可多次调用。"""
        obs = FakeObserver()
        w = LibraryWatcher(root_dir=str(tmp_path), observer=obs, debounce_ms=0)
        w.start()
        w.stop()
        w.stop()
        w.stop()
        assert obs.stop_call_count >= 1

    def test_stop_without_start_is_safe(self, tmp_path: Path) -> None:
        """未 start 直接 stop 不报错。"""
        obs = FakeObserver()
        w = LibraryWatcher(root_dir=str(tmp_path), observer=obs, debounce_ms=0)
        w.stop()  # 不抛


# ===========================================================================
# 事件回调
# ===========================================================================
class TestEventCallbacks:
    def test_created_event_calls_on_added(self, tmp_path: Path) -> None:
        """文件创建事件触发 on_added 回调。"""
        obs = FakeObserver()
        added_paths: list[str] = []
        w = LibraryWatcher(
            root_dir=str(tmp_path),
            observer=obs,
            debounce_ms=0,
            on_added=lambda p: added_paths.append(p),
        )
        w.start()
        handler = obs._handlers[str(tmp_path)][0]
        _dispatch(handler, "created", str(tmp_path / "new.mp3"))
        w._flush_debounce()  # 强制刷新防抖
        w.stop()
        assert str(tmp_path / "new.mp3") in added_paths

    def test_deleted_event_calls_on_removed(self, tmp_path: Path) -> None:
        """文件删除事件触发 on_removed 回调。"""
        obs = FakeObserver()
        removed: list[str] = []
        w = LibraryWatcher(
            root_dir=str(tmp_path),
            observer=obs,
            debounce_ms=0,
            on_removed=lambda p: removed.append(p),
        )
        w.start()
        handler = obs._handlers[str(tmp_path)][0]
        _dispatch(handler, "deleted", str(tmp_path / "gone.mp3"))
        w._flush_debounce()
        w.stop()
        assert str(tmp_path / "gone.mp3") in removed

    def test_modified_event_calls_on_modified(self, tmp_path: Path) -> None:
        """文件修改事件触发 on_modified 回调。"""
        obs = FakeObserver()
        modified: list[str] = []
        w = LibraryWatcher(
            root_dir=str(tmp_path),
            observer=obs,
            debounce_ms=0,
            on_modified=lambda p: modified.append(p),
        )
        w.start()
        handler = obs._handlers[str(tmp_path)][0]
        _dispatch(handler, "modified", str(tmp_path / "changed.mp3"))
        w._flush_debounce()
        w.stop()
        assert str(tmp_path / "changed.mp3") in modified

    def test_directory_events_ignored(self, tmp_path: Path) -> None:
        """目录事件被忽略（只关心音频文件）。"""
        obs = FakeObserver()
        added: list[str] = []
        w = LibraryWatcher(
            root_dir=str(tmp_path),
            observer=obs,
            debounce_ms=0,
            on_added=lambda p: added.append(p),
        )
        w.start()
        handler = obs._handlers[str(tmp_path)][0]
        event = FakeFileSystemEvent("created", str(tmp_path / "subdir"), is_directory=True)
        handler.dispatch(event)
        w._flush_debounce()
        w.stop()
        assert added == []

    def test_non_audio_files_ignored(self, tmp_path: Path) -> None:
        """非音频扩展名文件被忽略。"""
        obs = FakeObserver()
        added: list[str] = []
        w = LibraryWatcher(
            root_dir=str(tmp_path),
            observer=obs,
            debounce_ms=0,
            on_added=lambda p: added.append(p),
        )
        w.start()
        handler = obs._handlers[str(tmp_path)][0]
        _dispatch(handler, "created", str(tmp_path / "readme.txt"))
        w._flush_debounce()
        w.stop()
        assert added == []


# ===========================================================================
# 防抖
# ===========================================================================
class TestDebounce:
    def test_multiple_events_within_debounce_merged(self, tmp_path: Path) -> None:
        """500ms 内多次变更合并为一次回调。"""
        obs = FakeObserver()
        added: list[str] = []
        w = LibraryWatcher(
            root_dir=str(tmp_path),
            observer=obs,
            debounce_ms=100,
            on_added=lambda p: added.append(p),
        )
        w.start()
        handler = obs._handlers[str(tmp_path)][0]
        # 同一文件 3 次创建事件
        for _ in range(3):
            _dispatch(handler, "created", str(tmp_path / "x.mp3"))
        # 在防抖窗口内，回调未触发
        assert added == []
        # 强制刷新防抖
        w._flush_debounce()
        w.stop()
        # 合并为一次
        assert len(added) == 1

    def test_different_files_both_recorded(self, tmp_path: Path) -> None:
        """不同文件的事件都记录（去重按 path）。"""
        obs = FakeObserver()
        added: list[str] = []
        w = LibraryWatcher(
            root_dir=str(tmp_path),
            observer=obs,
            debounce_ms=100,
            on_added=lambda p: added.append(p),
        )
        w.start()
        handler = obs._handlers[str(tmp_path)][0]
        _dispatch(handler, "created", str(tmp_path / "a.mp3"))
        _dispatch(handler, "created", str(tmp_path / "b.mp3"))
        w._flush_debounce()
        w.stop()
        assert len(added) == 2
        assert str(tmp_path / "a.mp3") in added
        assert str(tmp_path / "b.mp3") in added


# ===========================================================================
# 状态查询
# ===========================================================================
class TestStatus:
    def test_is_running_reflects_state(self, tmp_path: Path) -> None:
        obs = FakeObserver()
        w = LibraryWatcher(root_dir=str(tmp_path), observer=obs, debounce_ms=0)
        assert w.is_running() is False
        w.start()
        assert w.is_running() is True
        w.stop()
        assert w.is_running() is False


# ===========================================================================
# watchdog 缺失场景
# ===========================================================================
class TestWatchdogMissing:
    def test_construct_without_observer_imports_watchdog(self, tmp_path: Path, monkeypatch) -> None:
        """未注入 observer 时惰性 import watchdog；import 失败抛 ImportError。"""
        # 模拟 watchdog 不可用：把 watchdog 模块设为 None
        import sys
        monkeypatch.setitem(sys.modules, "watchdog.observers", None)
        monkeypatch.setitem(sys.modules, "watchdog", None)
        with pytest.raises(ImportError):
            LibraryWatcher(root_dir=str(tmp_path), debounce_ms=0)
