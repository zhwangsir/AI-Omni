"""
演示视频场景素材完整性测试（M43）

验证 Demo.tsx 引用的所有静态素材真实存在于 demo-video/public/，
并锁定 M43 重捕的四张活跃态场景图（修复 idle 透明态导致的
近全黑空屏场景）。
"""

from pathlib import Path
import json
import re

import pytest

DEMO_DIR = Path(__file__).resolve().parents[2] / "demo-video"
DEMO_TSX = DEMO_DIR / "src" / "Demo.tsx"
PUBLIC_DIR = DEMO_DIR / "public"
STATE_JSON = Path(__file__).resolve().parents[2] / "STATE.json"


@pytest.fixture(scope="module")
def src() -> str:
    assert DEMO_TSX.exists(), f"Demo.tsx 缺失: {DEMO_TSX}"
    return DEMO_TSX.read_text(encoding="utf-8")


class TestReferencedAssetsExist:
    """Demo.tsx 引用的每个图片/音频素材必须存在于 public/。"""

    def test_shot_scene_images_exist(self, src: str) -> None:
        imgs = re.findall(r'img="([^"]+\.png)"', src)
        assert len(imgs) >= 6, f"ShotScene 图片引用 {len(imgs)} 个，预期 ≥6"
        for img in imgs:
            path = PUBLIC_DIR / img
            assert path.exists(), f"场景截图缺失: {path}"
            assert path.stat().st_size > 50_000, (
                f"场景截图 {img} 仅 {path.stat().st_size}B，疑似空图/损坏"
            )

    def test_intro_is_particle_driven(self, src: str) -> None:
        """M46：intro/outro 由程序化粒子引擎驱动，静态 hero 主视觉已退役。"""
        assert "hero-particles" not in src, "静态 hero 主视觉引用残留"
        assert 'behavior="converge"' in src, "intro 未接入 converge 粒子汇聚"

    def test_voiceover_files_exist(self, src: str) -> None:
        vos = re.findall(r'vo="([^"]+\.wav)"', src)
        assert vos, "未找到旁白引用"
        for vo in vos:
            path = PUBLIC_DIR / "voiceover" / vo
            assert path.exists(), f"旁白文件缺失: {path}"

    def test_bgm_exists(self, src: str) -> None:
        match = re.search(r'staticFile\("(bgm-[^"]+\.mp3)"\)', src)
        assert match, "未找到 BGM 引用"
        assert (PUBLIC_DIR / match.group(1)).exists()


class TestActiveStateAssets:
    """M43 重捕素材：中场场景必须使用活跃态截图（粒子可见 + Dock 播放中）。"""

    def test_voice_scene_uses_active_asset(self, src: str) -> None:
        """语音助手场景引用 01-voice-active.png（wake_listening 汇聚球），
        不再是 idle 透明态的 01-initial-idle.png。"""
        assert 'img="01-voice-active.png"' in src
        assert "01-initial-idle" not in src

    def test_retired_idle_asset_removed(self) -> None:
        """旧 idle 素材已从 public/ 移除，避免误用。"""
        assert not (PUBLIC_DIR / "01-initial-idle.png").exists()

    @pytest.mark.parametrize(
        "asset",
        [
            "01-voice-active.png",
            "02-well-ring-hover.png",
            "04-music-dock.png",
            "05-theme-safelight-red.png",
        ],
    )
    def test_recaptured_assets_present(self, asset: str) -> None:
        path = PUBLIC_DIR / asset
        assert path.exists(), f"M43 重捕素材缺失: {asset}"
        # 活跃态截图含粒子球 + Dock，体积应显著大于近纯黑图（~100KB 级）
        assert path.stat().st_size > 300_000, (
            f"{asset} 仅 {path.stat().st_size}B，疑似仍为近黑空屏"
        )


class TestOutroStatsSync:
    """M44：outro 字幕数据必须与 STATE.json 同步，防止里程碑/测试数过时。"""

    def test_outro_milestone_matches_state(self, src: str) -> None:
        """outro subtitle 的里程碑上界 = STATE.json current_milestone。"""
        current = json.loads(STATE_JSON.read_text(encoding="utf-8"))[
            "current_milestone"
        ]
        match = re.search(r'subtitle="核心数据全本地 · (M0–M\d+) · ', src)
        assert match, "未找到 outro subtitle 里程碑文案"
        assert match.group(1) == f"M0–{current}", (
            f"outro 里程碑 {match.group(1)} 过时，STATE.json 已到 {current}"
        )

    def test_outro_test_count_format(self, src: str) -> None:
        """outro 测试数按百取整展示（如 4300+），且不低于 4000。"""
        match = re.search(r"· (\d+)00\+ 自动化测试", src)
        assert match, "未找到 outro 测试数文案（格式: N00+ 自动化测试）"
        hundreds = int(match.group(1))
        assert hundreds >= 40, f"测试数 {hundreds}00+ 偏低，疑似未随测试增长更新"
