"""M40 演示视频配音资产校验（TDD）。

校验 ``demo-video/public/voiceover/`` 下 8 段旁白 WAV：

1. 文件存在且为合法 RIFF/WAV（PCM16、22050Hz——IndexTTS2 服务契约）；
2. 时长 ≤ 场景时长 − 起始延迟 − 末尾留白（不压下一场景淡入）；
3. 时长 ≥ 0.5s 且非静音（峰值振幅 > 500，防空调用产物被误提交）。

资产由 ``demo-video/scripts/gen_voiceover.py`` 生成（复用 omni_voice IndexTTS2
后端，Workstation :9200 雪莉默认音色）；文案/时间轴单一数据源为
``demo-video/scripts/voiceover_script.py``。
"""

from __future__ import annotations

import importlib.util
import wave
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VOICEOVER_DIR = REPO_ROOT / "demo-video" / "public" / "voiceover"
SCRIPT_PATH = REPO_ROOT / "demo-video" / "scripts" / "voiceover_script.py"


def _load_script_module():
    """按路径加载 voiceover_script（demo-video 非 Python 包，不走 sys.path）。"""
    spec = importlib.util.spec_from_file_location("voiceover_script", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vs = _load_script_module()


def _wav_info(path: Path) -> tuple[float, int, int, int]:
    """返回 (时长秒, 采样率, 采样位宽字节, 峰值振幅)。"""
    with wave.open(str(path), "rb") as wav:
        frames = wav.getnframes()
        rate = wav.getframerate()
        width = wav.getsampwidth()
        pcm = wav.readframes(frames)
    peak = 0
    if width == 2 and pcm:
        # PCM16 小端：逐样本取绝对值峰值
        peak = max(
            abs(int.from_bytes(pcm[i : i + 2], "little", signed=True))
            for i in range(0, len(pcm), 2)
        )
    return frames / rate, rate, width, peak


@pytest.mark.parametrize(
    ("filename", "from_frame", "duration_frames", "text"),
    vs.SCENES,
    ids=[scene[0] for scene in vs.SCENES],
)
def test_voiceover_wav(filename: str, from_frame: int, duration_frames: int, text: str) -> None:
    path = VOICEOVER_DIR / filename
    assert path.exists(), (
        f"旁白缺失: {path}（先运行 demo-video/scripts/gen_voiceover.py 生成）"
    )

    duration_s, rate, width, peak = _wav_info(path)

    # IndexTTS2 服务契约：PCM16 / 22050Hz
    assert width == 2, f"{filename}: 期望 PCM16，实际位宽 {width * 8}bit"
    assert rate == 22050, f"{filename}: 期望 22050Hz，实际 {rate}Hz"

    # 时长必须落在场景窗口内（起始延迟 + 末尾留白之外不可越界）
    budget = vs.scene_duration_s(duration_frames) - vs.VOICEOVER_OFFSET_S - vs.voiceover_tail_room_s()
    assert duration_s <= budget, (
        f"{filename}: 旁白 {duration_s:.2f}s 超出场景预算 {budget:.2f}s（文案：{text}）"
    )
    assert duration_s >= 0.5, f"{filename}: 旁白过短 {duration_s:.2f}s，疑似生成失败"

    # 非静音守卫
    assert peak > 500, f"{filename}: 峰值振幅 {peak}，疑似静音产物"


def test_scenes_cover_full_timeline() -> None:
    """场景表连续覆盖整条时间轴（无空洞/重叠），并与 Demo.tsx 总长一致。"""
    expected_from = 0
    for _filename, from_frame, duration_frames, _text in vs.SCENES:
        assert from_frame == expected_from, (
            f"场景时间轴断裂：期望 from={expected_from}，实际 {from_frame}"
        )
        expected_from = from_frame + duration_frames
    # Root.tsx durationInFrames = 1770
    assert expected_from == 1770, f"时间轴总长 {expected_from} ≠ 1770（Root.tsx）"
