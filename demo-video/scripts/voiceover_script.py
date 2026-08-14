"""演示视频旁白文案与场景时间轴（M40 单一数据源）。

``tests/unit/test_demo_voiceover.py`` 与 ``demo-video/scripts/gen_voiceover.py``
共用本模块，保证「文案 ↔ 场景 ↔ 生成资产」三者一致。

时间轴与 ``demo-video/src/Demo.tsx`` 的 ``<Scene from duration>`` 一一对应（30fps）；
``offset_s`` 为旁白在场景内的起始延迟（避开淡入），生成/渲染两侧共用。
"""

from __future__ import annotations

FPS = 30

#: 旁白在场景内的起始延迟（秒）：避开场景淡入（FADE=14 帧 ≈ 0.47s）
VOICEOVER_OFFSET_S = 0.6

#: 场景表：(文件名, from 帧, 时长帧, 旁白文案)
SCENES: list[tuple[str, int, int, str]] = [
    (
        "scene-01-intro.wav",
        0,
        150,
        "你好，我是雪莉。欢迎来到 AI-OMNI。",
    ),
    (
        "scene-02-space.wav",
        150,
        240,
        "沉浸式粒子空间，数千 GPU 粒子，随语音状态呼吸起伏。",
    ),
    (
        "scene-03-voice.wav",
        390,
        240,
        "语音管道全本地运行：唤醒、识别、合成，都在你的设备上完成。",
    ),
    (
        "scene-04-well.wav",
        630,
        240,
        "WellZone 交互井，悬停显影，一触即达。",
    ),
    (
        "scene-05-caption.wav",
        870,
        240,
        "实时字幕，流式上屏，每一句话，都清晰可见。",
    ),
    (
        "scene-06-music.wav",
        1110,
        240,
        "音乐 Dock 与歌词总线联动，播放切歌，逐行高亮。",
    ),
    (
        "scene-07-theme.wav",
        1350,
        240,
        "Film Atelier 暗房主题，安全灯红，一键切换。",
    ),
    (
        "scene-08-outro.wav",
        1590,
        180,
        "隐私优先，核心数据全本地。AI-OMNI，与你同在。",
    ),
]


def scene_duration_s(duration_frames: int) -> float:
    """场景时长（秒）。"""
    return duration_frames / FPS


def voiceover_tail_room_s() -> float:
    """旁白末尾留白（秒）：避免压到下一场景淡入。"""
    return 0.3
