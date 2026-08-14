"""omni_music library.watcher watchdog 文件监听测试（M19.4）。

TDD 测试先行：覆盖 LibraryWatcher 的生命周期、防抖、事件回调、stop 幂等。
全部用 fake observer（不启动真实线程，不依赖 watchdog 库）。
watchdog 缺失时构造抛 ImportError 但测试用注入的 observer 不受影响。
"""

from __future__ import annotations

import threading
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


# ===========================================================================
# 锁内回调死锁回归（M32.26 P1）
# ===========================================================================
class TestCallbackReentrancyDeadlock:
    """用户回调重入 watcher 不得死锁。

    M32.26 修复前：``_flush_locked`` 在持有不可重入的 ``self._lock`` 时调用
    用户回调；回调里再调 ``stop()`` / ``_schedule_debounce()`` 会二次获取
    同一把锁，同线程永久 hang。回归测试统一在 daemon 线程中间接触发，
    join 超时判定——死锁时测试失败而非挂死 pytest 进程。
    """

    def test_on_added_callback_calling_stop_does_not_deadlock(self, tmp_path: Path) -> None:
        """on_added 回调里调 watcher.stop()：修复前 stop() → _flush_debounce()
        二次取锁死锁。"""
        obs = FakeObserver()
        w = LibraryWatcher(
            root_dir=str(tmp_path),
            observer=obs,
            debounce_ms=0,
            on_added=lambda p: w.stop(),
        )
        w.start()
        handler = obs._handlers[str(tmp_path)][0]

        t = threading.Thread(
            target=lambda: _dispatch(handler, "created", str(tmp_path / "new.mp3")),
            daemon=True,
        )
        t.start()
        t.join(timeout=2.0)
        assert not t.is_alive(), "回调重入 stop() 未在 2 秒内返回（疑似死锁）"
        assert w.is_running() is False

    def test_on_added_callback_reentrant_schedule_does_not_deadlock(self, tmp_path: Path) -> None:
        """on_added 回调里再次 _schedule_debounce：修复前持锁回调二次取锁死锁。"""
        obs = FakeObserver()
        modified: list[str] = []
        rescheduled: list[str] = []

        def _on_added(p: str) -> None:
            if not rescheduled:  # 只重入一次，避免无限递归
                rescheduled.append(p)
                w._schedule_debounce("modified", str(tmp_path / "followup.mp3"))

        w = LibraryWatcher(
            root_dir=str(tmp_path),
            observer=obs,
            debounce_ms=0,
            on_added=_on_added,
            on_modified=lambda p: modified.append(p),
        )
        w.start()
        handler = obs._handlers[str(tmp_path)][0]

        t = threading.Thread(
            target=lambda: _dispatch(handler, "created", str(tmp_path / "new.mp3")),
            daemon=True,
        )
        t.start()
        t.join(timeout=2.0)
        assert not t.is_alive(), "回调重入 _schedule_debounce 未在 2 秒内返回（疑似死锁）"
        w.stop()
        assert rescheduled == [str(tmp_path / "new.mp3")]
        assert str(tmp_path / "followup.mp3") in modified

    def test_stop_inside_timer_flush_callback_does_not_deadlock(self, tmp_path: Path) -> None:
        """防抖定时器线程里执行的回调调 stop() 同样不得死锁。"""
        obs = FakeObserver()
        w = LibraryWatcher(
            root_dir=str(tmp_path),
            observer=obs,
            debounce_ms=30,
            on_added=lambda p: w.stop(),
        )
        w.start()
        handler = obs._handlers[str(tmp_path)][0]
        _dispatch(handler, "created", str(tmp_path / "new.mp3"))
        # 定时器线程执行 flush → 回调 → stop()；若死锁 is_running 永远为 True
        deadline = time.time() + 2.0
        while time.time() < deadline and w.is_running():
            time.sleep(0.01)
        assert w.is_running() is False, "定时器回调重入 stop() 疑似死锁"
        w.stop()  # 幂等清理


# ===========================================================================
# flush 语义（M32.26 锁外回调重构后保持不变）
# ===========================================================================
class TestFlushSemantics:
    def test_callback_exception_swallowed_and_flush_continues(self, tmp_path: Path) -> None:
        """回调抛异常被吞，后续回调仍派发，不崩监听线程。"""
        obs = FakeObserver()
        modified: list[str] = []

        def _boom(p: str) -> None:
            raise RuntimeError("回调故障")

        w = LibraryWatcher(
            root_dir=str(tmp_path),
            observer=obs,
            debounce_ms=1000,
            on_added=_boom,
            on_modified=lambda p: modified.append(p),
        )
        w.start()
        handler = obs._handlers[str(tmp_path)][0]
        _dispatch(handler, "created", str(tmp_path / "a.mp3"))
        _dispatch(handler, "modified", str(tmp_path / "b.mp3"))
        w._flush_debounce()  # 不抛
        w.stop()
        assert str(tmp_path / "b.mp3") in modified

    def test_pending_cleared_after_flush(self, tmp_path: Path) -> None:
        """flush 后 pending 缓冲清空；再次 flush 不重复派发。"""
        obs = FakeObserver()
        added: list[str] = []
        w = LibraryWatcher(
            root_dir=str(tmp_path),
            observer=obs,
            debounce_ms=1000,
            on_added=lambda p: added.append(p),
        )
        w.start()
        handler = obs._handlers[str(tmp_path)][0]
        _dispatch(handler, "created", str(tmp_path / "a.mp3"))
        w._flush_debounce()
        assert w._pending_added == set()
        assert w._pending_removed == set()
        assert w._pending_modified == set()
        w._flush_debounce()  # 空 flush：不重复回调
        w.stop()
        assert added == [str(tmp_path / "a.mp3")]

    def test_all_three_kinds_dispatched_in_one_flush(self, tmp_path: Path) -> None:
        """added / removed / modified 三种事件在同一次 flush 中全部派发。"""
        obs = FakeObserver()
        added: list[str] = []
        removed: list[str] = []
        modified: list[str] = []
        w = LibraryWatcher(
            root_dir=str(tmp_path),
            observer=obs,
            debounce_ms=1000,
            on_added=lambda p: added.append(p),
            on_removed=lambda p: removed.append(p),
            on_modified=lambda p: modified.append(p),
        )
        w.start()
        handler = obs._handlers[str(tmp_path)][0]
        _dispatch(handler, "created", str(tmp_path / "a.mp3"))
        _dispatch(handler, "deleted", str(tmp_path / "b.mp3"))
        _dispatch(handler, "modified", str(tmp_path / "c.mp3"))
        w._flush_debounce()
        w.stop()
        assert added == [str(tmp_path / "a.mp3")]
        assert removed == [str(tmp_path / "b.mp3")]
        assert modified == [str(tmp_path / "c.mp3")]


# ===========================================================================
# _create_observer 成功路径（fake watchdog 模块注入）
# ===========================================================================
class TestCreateObserver:
    def test_create_observer_returns_observer_instance(self, monkeypatch) -> None:
        """watchdog 可用时 _create_observer 返回 Observer() 实例。"""
        import sys
        import types

        class _FakeWatchdogObserver:
            pass

        fake_observers = types.ModuleType("watchdog.observers")
        fake_observers.Observer = _FakeWatchdogObserver  # type: ignore[attr-defined]
        fake_watchdog = types.ModuleType("watchdog")
        monkeypatch.setitem(sys.modules, "watchdog", fake_watchdog)
        monkeypatch.setitem(sys.modules, "watchdog.observers", fake_observers)
        obs = LibraryWatcher._create_observer()
        assert isinstance(obs, _FakeWatchdogObserver)

    def test_construct_without_observer_uses_created_observer(self, tmp_path: Path, monkeypatch) -> None:
        """未注入 observer 时构造走惰性 _create_observer()。"""
        import sys
        import types

        class _FakeWatchdogObserver:
            pass

        fake_observers = types.ModuleType("watchdog.observers")
        fake_observers.Observer = _FakeWatchdogObserver  # type: ignore[attr-defined]
        fake_watchdog = types.ModuleType("watchdog")
        monkeypatch.setitem(sys.modules, "watchdog", fake_watchdog)
        monkeypatch.setitem(sys.modules, "watchdog.observers", fake_observers)
        w = LibraryWatcher(root_dir=str(tmp_path), debounce_ms=0)
        assert isinstance(w._observer, _FakeWatchdogObserver)


# ===========================================================================
# _safe_call / start 幂等
# ===========================================================================
class TestSafeCallAndStartGuard:
    def test_safe_call_none_callback_is_noop(self) -> None:
        """回调为 None 时 _safe_call 直接返回，不抛异常。"""
        LibraryWatcher._safe_call(None, "/x/a.mp3")

    def test_start_twice_schedules_only_once(self, tmp_path: Path) -> None:
        """重复 start 直接返回：observer 只被 schedule/start 一次。"""
        obs = FakeObserver()
        w = LibraryWatcher(root_dir=str(tmp_path), observer=obs, debounce_ms=0)
        w.start()
        w.start()  # 已启动，直接 return
        assert len(obs.scheduled) == 1
        assert w.is_running() is True
        w.stop()


# ===========================================================================
# stop 降级路径（内部异常全部吞掉，stop 幂等完成）
# ===========================================================================
class TestStopDegradation:
    def test_stop_swallows_flush_error(self, tmp_path: Path) -> None:
        """stop 时 _flush_debounce 抛异常被吞，stop 仍完成。"""
        obs = FakeObserver()
        w = LibraryWatcher(root_dir=str(tmp_path), observer=obs, debounce_ms=0)
        w.start()

        def _boom() -> None:
            raise RuntimeError("flush boom")

        w._flush_debounce = _boom  # type: ignore[method-assign]
        w.stop()  # 不抛
        assert w.is_running() is False
        assert obs.stopped is True

    def test_stop_swallows_observer_stop_error(self, tmp_path: Path) -> None:
        """observer.stop 抛异常被吞，stop 仍完成。"""
        class _StopBoomObserver(FakeObserver):
            def stop(self) -> None:
                raise RuntimeError("stop boom")

        obs = _StopBoomObserver()
        w = LibraryWatcher(root_dir=str(tmp_path), observer=obs, debounce_ms=0)
        w.start()
        w.stop()  # 不抛
        assert w.is_running() is False

    def test_stop_swallows_observer_join_error(self, tmp_path: Path) -> None:
        """observer.join 抛异常被吞，stop 仍完成。"""
        class _JoinBoomObserver(FakeObserver):
            def join(self, timeout: float | None = None) -> None:
                raise RuntimeError("join boom")

        obs = _JoinBoomObserver()
        w = LibraryWatcher(root_dir=str(tmp_path), observer=obs, debounce_ms=0)
        w.start()
        w.stop()  # 不抛
        assert w.is_running() is False


# ===========================================================================
# deleted / modified 事件的过滤分支（目录 / 非音频）
# ===========================================================================
class TestDeletedModifiedFiltering:
    def test_deleted_directory_ignored(self, tmp_path: Path) -> None:
        """deleted 事件 is_directory=True 被忽略。"""
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
        event = FakeFileSystemEvent("deleted", str(tmp_path / "subdir"), is_directory=True)
        handler.dispatch(event)
        w._flush_debounce()
        w.stop()
        assert removed == []

    def test_deleted_non_audio_ignored(self, tmp_path: Path) -> None:
        """deleted 事件非音频扩展名被忽略。"""
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
        _dispatch(handler, "deleted", str(tmp_path / "notes.txt"))
        w._flush_debounce()
        w.stop()
        assert removed == []

    def test_modified_directory_ignored(self, tmp_path: Path) -> None:
        """modified 事件 is_directory=True 被忽略。"""
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
        event = FakeFileSystemEvent("modified", str(tmp_path / "subdir"), is_directory=True)
        handler.dispatch(event)
        w._flush_debounce()
        w.stop()
        assert modified == []

    def test_modified_non_audio_ignored(self, tmp_path: Path) -> None:
        """modified 事件非音频扩展名被忽略。"""
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
        _dispatch(handler, "modified", str(tmp_path / "notes.txt"))
        w._flush_debounce()
        w.stop()
        assert modified == []

    def test_unknown_event_type_ignored(self, tmp_path: Path) -> None:
        """未知 event_type 不路由到任何 on_* 方法。"""
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
        _dispatch(handler, "closed", str(tmp_path / "a.mp3"))
        w._flush_debounce()
        w.stop()
        assert added == []


# ===========================================================================
# moved 事件路由（旧路径 removed + 新路径 added）
# ===========================================================================
class TestMovedEvent:
    def _make_watcher(self, tmp_path: Path, added: list, removed: list) -> tuple:
        obs = FakeObserver()
        w = LibraryWatcher(
            root_dir=str(tmp_path),
            observer=obs,
            debounce_ms=0,
            on_added=lambda p: added.append(p),
            on_removed=lambda p: removed.append(p),
        )
        w.start()
        handler = obs._handlers[str(tmp_path)][0]
        return w, handler

    def test_moved_audio_to_audio(self, tmp_path: Path) -> None:
        """音频 → 音频：旧路径触发 removed，新路径触发 added。"""
        added: list[str] = []
        removed: list[str] = []
        w, handler = self._make_watcher(tmp_path, added, removed)
        event = FakeFileSystemEvent("moved", str(tmp_path / "old.mp3"))
        event.dest_path = str(tmp_path / "new.flac")
        handler.dispatch(event)
        w._flush_debounce()
        w.stop()
        assert removed == [str(tmp_path / "old.mp3")]
        assert added == [str(tmp_path / "new.flac")]

    def test_moved_audio_to_non_audio(self, tmp_path: Path) -> None:
        """音频 → 非音频：只触发 removed。"""
        added: list[str] = []
        removed: list[str] = []
        w, handler = self._make_watcher(tmp_path, added, removed)
        event = FakeFileSystemEvent("moved", str(tmp_path / "old.mp3"))
        event.dest_path = str(tmp_path / "old.txt")
        handler.dispatch(event)
        w._flush_debounce()
        w.stop()
        assert removed == [str(tmp_path / "old.mp3")]
        assert added == []

    def test_moved_non_audio_to_audio(self, tmp_path: Path) -> None:
        """非音频 → 音频：只触发 added。"""
        added: list[str] = []
        removed: list[str] = []
        w, handler = self._make_watcher(tmp_path, added, removed)
        event = FakeFileSystemEvent("moved", str(tmp_path / "old.txt"))
        event.dest_path = str(tmp_path / "new.mp3")
        handler.dispatch(event)
        w._flush_debounce()
        w.stop()
        assert removed == []
        assert added == [str(tmp_path / "new.mp3")]

    def test_moved_without_dest_path(self, tmp_path: Path) -> None:
        """dest_path 缺失/为空：只触发 removed，不触发 added。"""
        added: list[str] = []
        removed: list[str] = []
        w, handler = self._make_watcher(tmp_path, added, removed)
        event = FakeFileSystemEvent("moved", str(tmp_path / "old.mp3"))
        event.dest_path = ""  # 显式空目标
        handler.dispatch(event)
        w._flush_debounce()
        w.stop()
        assert removed == [str(tmp_path / "old.mp3")]
        assert added == []

    def test_moved_directory_ignored(self, tmp_path: Path) -> None:
        """目录 moved 事件被忽略。"""
        added: list[str] = []
        removed: list[str] = []
        w, handler = self._make_watcher(tmp_path, added, removed)
        event = FakeFileSystemEvent("moved", str(tmp_path / "dir_a"), is_directory=True)
        event.dest_path = str(tmp_path / "dir_b")
        handler.dispatch(event)
        w._flush_debounce()
        w.stop()
        assert removed == []
        assert added == []
