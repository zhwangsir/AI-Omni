"""omni_music MusicPlayer 播放控制（M17.8）。

D17.1 对齐：Python 侧**不实际播放音频**，仅管理：
- 播放队列（queue）与当前索引
- 播放状态机（STOPPED/PLAYING/PAUSED）
- 播放模式（SINGLE/LIST_LOOP/RANDOM/SEQUENCE）
- 进度（``position_s``，由前端 ``<audio>`` 元素 timeupdate 推送，Python 不计时）
- 历史记录（``max_history`` 截断旧的，相邻同曲目去重）

实际音频播放由前端 ``<audio>`` 元素 + AnalyserNode 负责（M17.10 前端 + M21 节奏分析）。
Python 通过 :meth:`MusicPlayer.to_state_dict` 把队列+状态序列化，经 state_file 推送给前端。

零音频依赖：不 import sounddevice / pygame / vlc 等任何音频库；
仅用标准库 ``random``（RANDOM 模式选索引），可注入 seed 便于测试。

合规说明（D17.4）：仅承载免费/试听曲目元数据；VIP 曲目 ``ensure_song_url`` 返回 None
表示无权限，不携带任何破解付费内容的逻辑。仅个人学习用途。
"""

from __future__ import annotations

import random
from enum import Enum
from typing import Any

from omni_music.models import Song
from omni_music.sources.base import MusicSource


class RepeatMode(Enum):
    """播放模式。"""

    SINGLE = "single"        # 单曲循环
    LIST_LOOP = "list_loop"  # 列表循环
    RANDOM = "random"        # 随机播放
    SEQUENCE = "sequence"    # 顺序播放（播完停止）


class PlayerState(Enum):
    """播放状态。"""

    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


class MusicPlayer:
    """音乐播放控制器（仅元数据与状态，不播放音频）。

    持有 :class:`MusicSource` 实例以惰性获取 URL / 歌词；
    队列与状态变更后通过 :meth:`to_state_dict` 序列化推送给前端 state_file。

    :ivar _queue: 播放队列
    :ivar _current_index: 当前曲目索引，-1 表示空队列
    :ivar _state: 播放状态
    :ivar _repeat_mode: 播放模式
    :ivar _position_s: 播放位置（秒，前端推送）
    :ivar _source: 音乐源实例，可空
    :ivar _history: 历史记录（max_history 截断）
    :ivar _shuffle_rng: RANDOM 模式随机数生成器，可注入 seed
    :ivar _played_indices: RANDOM 模式已播放索引集合
    """

    def __init__(
        self,
        source: MusicSource | None = None,
        max_history: int = 100,
    ) -> None:
        """构造播放器。

        :param source: 音乐源实例，可空（VIP 曲目无 URL 时 :meth:`ensure_song_url` 返回 None）
        :param max_history: 历史记录上限，超出截断旧的
        """
        self._queue: list[Song] = []
        self._current_index: int = -1
        self._state: PlayerState = PlayerState.STOPPED
        self._repeat_mode: RepeatMode = RepeatMode.SEQUENCE
        self._position_s: int = 0
        self._source: MusicSource | None = source
        self._history: list[Song] = []
        self._max_history: int = max_history
        self._shuffle_rng: random.Random = random.Random()
        self._played_indices: set[int] = set()

    # ------------------------------------------------------------------
    # 队列管理
    # ------------------------------------------------------------------

    def set_queue(self, songs: list[Song]) -> None:
        """替换整个队列，重置 current_index 为 0（若非空），state 不变。

        :param songs: 新队列歌曲列表（会复制，不持有调用方引用）
        """
        self._queue = list(songs)
        self._current_index = 0 if self._queue else -1
        self._played_indices = set()

    def add_to_queue(self, song: Song) -> None:
        """追加到队列末尾；若队列为空则 current_index=0。

        :param song: 要追加的 :class:`Song`
        """
        self._queue.append(song)
        if self._current_index < 0:
            self._current_index = 0

    def add_next(self, song: Song) -> None:
        """插入到当前曲目后一位；若队列为空则 current_index=0。

        :param song: 要插入的 :class:`Song`
        """
        if not self._queue or self._current_index < 0:
            self._queue.append(song)
            self._current_index = 0
        else:
            insert_pos = self._current_index + 1
            self._queue.insert(insert_pos, song)

    def remove_from_queue(self, index: int) -> None:
        """按索引移除歌曲；越界 raise IndexError；调整 current_index。

        移除当前曲目时，index 保持指向原 index+1 位置（即下一首）；
        若原当前为末尾则回退一位。队列空则 current_index=-1、state=STOPPED。

        :param index: 要移除的索引
        :raises IndexError: 索引越界
        """
        if index < 0 or index >= len(self._queue):
            raise IndexError(f"队列索引越界: {index}（长度 {len(self._queue)}）")
        self._queue.pop(index)
        if not self._queue:
            self._current_index = -1
            self._state = PlayerState.STOPPED
            self._position_s = 0
            self._played_indices = set()
        elif index < self._current_index:
            self._current_index -= 1
        elif index == self._current_index:
            # 移除当前：index 位置现在是原下一首；末尾则回退
            if self._current_index >= len(self._queue):
                self._current_index = len(self._queue) - 1
            self._position_s = 0
        # index > current_index 时 current_index 不变
        # RANDOM 已播集合重置为当前（避免索引漂移）
        self._played_indices = (
            {self._current_index} if self._current_index >= 0 else set()
        )

    def clear_queue(self) -> None:
        """清空队列，current_index=-1，state=STOPPED，position_s=0。"""
        self._queue = []
        self._current_index = -1
        self._state = PlayerState.STOPPED
        self._position_s = 0
        self._played_indices = set()

    def get_queue(self) -> list[Song]:
        """返回队列副本。"""
        return list(self._queue)

    @property
    def queue_length(self) -> int:
        """队列长度。"""
        return len(self._queue)

    # ------------------------------------------------------------------
    # 播放控制
    # ------------------------------------------------------------------

    def play(self, index: int | None = None) -> Song | None:
        """开始播放。

        :param index: 指定则先跳到该索引（越界 raise IndexError）；队列为空返回 None
        :return: 当前 :class:`Song`，空队列返回 None
        :raises IndexError: index 越界
        """
        if not self._queue:
            return None
        if index is not None:
            if index < 0 or index >= len(self._queue):
                raise IndexError(f"play 索引越界: {index}")
            self._current_index = index
        if self._current_index < 0:
            self._current_index = 0
        self._state = PlayerState.PLAYING
        self._position_s = 0
        current = self._queue[self._current_index]
        self._add_to_history(current)
        self._played_indices.add(self._current_index)
        return current

    def pause(self) -> None:
        """暂停；state 必须 PLAYING。

        :raises RuntimeError: 非 PLAYING 状态
        """
        if self._state is not PlayerState.PLAYING:
            raise RuntimeError("非播放状态")
        self._state = PlayerState.PAUSED

    def resume(self) -> None:
        """恢复；state 必须 PAUSED。

        :raises RuntimeError: 非 PAUSED 状态
        """
        if self._state is not PlayerState.PAUSED:
            raise RuntimeError("非暂停状态")
        self._state = PlayerState.PLAYING

    def stop(self) -> None:
        """停止；state=STOPPED, position_s=0（不清队列、不重置 index）。"""
        self._state = PlayerState.STOPPED
        self._position_s = 0

    def seek(self, position_s: int) -> None:
        """跳转到指定位置。

        :param position_s: 目标位置（秒）
        :raises ValueError: position_s < 0
        """
        if position_s < 0:
            raise ValueError(f"position_s 不能为负: {position_s}")
        self._position_s = position_s

    def next(self) -> Song | None:
        """按 repeat_mode 切换到下一首。

        - SINGLE：保持当前曲目，position 重置为 0
        - LIST_LOOP：``index=(index+1)%len``；越界回绕
        - SEQUENCE：``index+1``，越界则 stop 返回 None
        - RANDOM：随机选未播放过的索引；全播放过则重置已播集合

        state 保持原状（PLAYING 仍 PLAYING，PAUSED 仍 PAUSED）；
        SEQUENCE 越界 stop 时 state 变 STOPPED。

        :return: 新 :class:`Song`；SEQUENCE 越界则返回 None
        """
        if not self._queue or self._current_index < 0:
            return None
        if self._repeat_mode is RepeatMode.SINGLE:
            self._position_s = 0
            # 保持当前曲目
        elif self._repeat_mode is RepeatMode.LIST_LOOP:
            self._current_index = (self._current_index + 1) % len(self._queue)
            self._position_s = 0
        elif self._repeat_mode is RepeatMode.RANDOM:
            self._current_index = self._pick_random_index()
            self._position_s = 0
        else:  # SEQUENCE
            next_index = self._current_index + 1
            if next_index >= len(self._queue):
                self.stop()
                return None
            self._current_index = next_index
            self._position_s = 0
        current = self._queue[self._current_index]
        self._add_to_history(current)
        self._played_indices.add(self._current_index)
        return current

    def previous(self) -> Song | None:
        """切换到上一首。

        - LIST_LOOP：``index-1``，<0 则回绕到末尾
        - SEQUENCE / SINGLE / RANDOM：``index-1``，<0 则保持 0

        :return: 新 :class:`Song`；空队列返回 None
        """
        if not self._queue or self._current_index < 0:
            return None
        if self._repeat_mode is RepeatMode.LIST_LOOP:
            self._current_index = (self._current_index - 1) % len(self._queue)
        else:
            prev = self._current_index - 1
            self._current_index = prev if prev >= 0 else 0
        self._position_s = 0
        current = self._queue[self._current_index]
        self._add_to_history(current)
        self._played_indices.add(self._current_index)
        return current

    def set_repeat_mode(self, mode: RepeatMode) -> None:
        """设置播放模式。"""
        self._repeat_mode = mode

    def get_repeat_mode(self) -> RepeatMode:
        """获取播放模式。"""
        return self._repeat_mode

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    @property
    def current_song(self) -> Song | None:
        """当前曲目（队列空或 index 无效返回 None）。"""
        if 0 <= self._current_index < len(self._queue):
            return self._queue[self._current_index]
        return None

    @property
    def current_state(self) -> PlayerState:
        """当前播放状态。"""
        return self._state

    @property
    def current_index(self) -> int:
        """当前曲目索引。"""
        return self._current_index

    @property
    def position_s(self) -> int:
        """当前播放位置（秒）。"""
        return self._position_s

    @position_s.setter
    def position_s(self, value: int) -> None:
        """设置播放位置（前端 ``timeupdate`` 推送）。

        :raises ValueError: value < 0
        """
        if value < 0:
            raise ValueError(f"position_s 不能为负: {value}")
        self._position_s = value

    @property
    def history(self) -> list[Song]:
        """历史记录副本。"""
        return list(self._history)

    @property
    def is_playing(self) -> bool:
        """是否正在播放。"""
        return self._state is PlayerState.PLAYING

    # ------------------------------------------------------------------
    # 与 MusicSource 协作
    # ------------------------------------------------------------------

    def ensure_song_url(self, quality: str = "standard") -> str | None:
        """确保当前曲目有可播放 URL。

        若当前 Song 已有 ``url`` 直接返回；否则调 ``source.get_song_url``。
        source 为 None 或返回 None（VIP 无权限）则返回 None。惰性不预取。

        :param quality: 音质，``standard`` / ``hires`` / ``lossless`` 等
        :return: URL 字符串或 None
        """
        song = self.current_song
        if song is None:
            return None
        if song.url:
            return song.url
        if self._source is None:
            return None
        return self._source.get_song_url(song.id, quality)

    def ensure_lyrics(self) -> str | None:
        """确保当前曲目有歌词。

        若当前 ``Song.lyrics`` 非空返回；否则调 ``source.get_lyrics``。

        :return: 歌词字符串或 None
        """
        song = self.current_song
        if song is None:
            return None
        if song.lyrics:
            return song.lyrics
        if self._source is None:
            return None
        return self._source.get_lyrics(song.id)

    def set_source(self, source: MusicSource) -> None:
        """替换 source。

        :param source: 新的 :class:`MusicSource` 实例
        """
        self._source = source

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def to_state_dict(self) -> dict[str, Any]:
        """导出完整状态供 state_file 推送给前端。

        :return: dict，含 queue（Song.to_dict 列表）/ current_index / state /
            repeat_mode / position_s / current_song（或 None）
        """
        current = self.current_song
        return {
            "queue": [s.to_dict() for s in self._queue],
            "current_index": self._current_index,
            "state": self._state.value,
            "repeat_mode": self._repeat_mode.value,
            "position_s": self._position_s,
            "current_song": current.to_dict() if current is not None else None,
        }

    @classmethod
    def from_state_dict(
        cls,
        data: dict[str, Any],
        source: MusicSource | None = None,
    ) -> MusicPlayer:
        """从 dict 恢复 player。

        :param data: :meth:`to_state_dict` 产出的 dict
        :param source: 可选的音乐源
        :return: :class:`MusicPlayer` 实例
        """
        player = cls(source=source)
        queue = [Song.from_dict(s) for s in data.get("queue", [])]
        player._queue = queue
        player._current_index = int(data.get("current_index", -1))
        player._state = PlayerState(data.get("state", "stopped"))
        player._repeat_mode = RepeatMode(data.get("repeat_mode", "sequence"))
        player._position_s = int(data.get("position_s", 0))
        if 0 <= player._current_index < len(player._queue):
            player._played_indices.add(player._current_index)
        return player

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _add_to_history(self, song: Song) -> None:
        """加入 history；相邻同曲目去重；超 max_history 截断旧的。

        :param song: 刚播放的 :class:`Song`
        """
        if self._history and self._history[-1] == song:
            return
        self._history.append(song)
        while len(self._history) > self._max_history:
            self._history.pop(0)

    def _pick_random_index(self) -> int:
        """随机选一个未播放过的索引；全播放过则重置已播集合。

        :return: 选中的索引；空队列返回 -1
        """
        if not self._queue:
            return -1
        self._played_indices.add(self._current_index)
        candidates = [
            i for i in range(len(self._queue)) if i not in self._played_indices
        ]
        if not candidates:
            # 全播放过，重置为只含当前，重新选
            self._played_indices = {self._current_index}
            candidates = [
                i for i in range(len(self._queue)) if i not in self._played_indices
            ]
        return self._shuffle_rng.choice(candidates)
