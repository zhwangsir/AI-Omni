"""omni_music sources 包：音乐源抽象基类与具体实现。

- :class:`MusicSource`：抽象基类（M17.2）
- :class:`FakeMusicSource`：测试用 fake 后端
- ``netease`` / ``qqmusic`` / ``local``：具体源（M17.5-M17.7 实现）
"""

from __future__ import annotations

from omni_music.sources.base import FakeMusicSource, MusicSource

__all__ = ["MusicSource", "FakeMusicSource"]
