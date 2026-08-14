"""演示视频粒子系统结构性护栏（M46）

一整套程序化粒子引擎（Canvas 2D，纯函数帧驱动）的约束锁定：

- 确定性：种子 RNG + 纯帧驱动，禁止 Math.random / 墙钟（Remotion 并行渲染
  要求每帧状态 = f(frame)，跨进程一致）
- 调色板 ≤6 色（Film Atelier 暗房色系）
- 预算：MAX_PARTICLES ≤ 300、SPEED_LIMIT ≤ 1.2、连线距离有界
- 文字安全区衰减（粒子不覆盖标题）
- 防频闪：呼吸振幅/周期双约束
- 行为全集：nebula / converge / orbit / ripple / scatter
- Demo.tsx 集成：intro 汇聚、过场涟漪、outro 轨道球、静态 hero 移除
"""

from pathlib import Path
import re

import pytest

SRC = Path(__file__).resolve().parents[2] / "demo-video" / "src"
PARTICLES_DIR = SRC / "particles"
ENGINE_TS = PARTICLES_DIR / "engine.ts"
BEHAVIORS_TS = PARTICLES_DIR / "behaviors.ts"
CANVAS_TSX = PARTICLES_DIR / "ParticleCanvas.tsx"
DEMO_TSX = SRC / "Demo.tsx"
PUBLIC_DIR = Path(__file__).resolve().parents[2] / "demo-video" / "public"


@pytest.fixture(scope="module")
def engine() -> str:
    assert ENGINE_TS.exists(), f"粒子引擎缺失: {ENGINE_TS}"
    return ENGINE_TS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def behaviors() -> str:
    assert BEHAVIORS_TS.exists(), f"粒子行为集缺失: {BEHAVIORS_TS}"
    return BEHAVIORS_TS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def canvas() -> str:
    assert CANVAS_TSX.exists(), f"粒子画布组件缺失: {CANVAS_TSX}"
    return CANVAS_TSX.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def demo() -> str:
    assert DEMO_TSX.exists(), f"Demo.tsx 缺失: {DEMO_TSX}"
    return DEMO_TSX.read_text(encoding="utf-8")


class TestEngineFiles:
    """粒子系统三件套必须齐备。"""

    def test_engine_file_exists(self) -> None:
        assert ENGINE_TS.exists(), "particles/engine.ts 不存在"

    def test_behaviors_file_exists(self) -> None:
        assert BEHAVIORS_TS.exists(), "particles/behaviors.ts 不存在"

    def test_canvas_component_exists(self) -> None:
        assert CANVAS_TSX.exists(), "particles/ParticleCanvas.tsx 不存在"


class TestDeterminism:
    """渲染进程并行/乱序 seek —— 粒子状态必须是帧号的纯函数。"""

    def test_seeded_rng_present(self, engine: str) -> None:
        assert "mulberry32" in engine, "引擎缺少种子 RNG（mulberry32）"
        assert re.search(r"export\s+const\s+seedParticle", engine), (
            "引擎缺少 seedParticle 单粒子种子派生"
        )

    @pytest.mark.parametrize("fixture", ["engine", "behaviors", "canvas"])
    def test_no_math_random(self, fixture: str, request: pytest.FixtureRequest) -> None:
        src = request.getfixturevalue(fixture)
        assert "Math.random" not in src, (
            f"{fixture} 使用 Math.random —— 破坏跨进程帧一致性，必须用种子 RNG"
        )

    @pytest.mark.parametrize("fixture", ["engine", "behaviors", "canvas"])
    def test_no_wall_clock(self, fixture: str, request: pytest.FixtureRequest) -> None:
        src = request.getfixturevalue(fixture)
        assert "Date.now" not in src, f"{fixture} 使用墙钟 Date.now，禁止"
        assert "performance.now" not in src, f"{fixture} 使用墙钟 performance.now，禁止"

    def test_canvas_is_frame_driven(self, canvas: str) -> None:
        assert "useCurrentFrame" in canvas, "ParticleCanvas 必须由 useCurrentFrame 驱动"


class TestPaletteConstraint:
    """内容色 ≤6（用户硬性约束），暗房琥珀/青色系。"""

    def test_palette_color_count(self, engine: str) -> None:
        match = re.search(
            r"PARTICLE_PALETTE[^=]*=\s*\{(.*?)\}", engine, re.DOTALL
        )
        assert match, "未找到 PARTICLE_PALETTE 定义"
        colors = re.findall(r'"#[0-9a-fA-F]{6}"', match.group(1))
        assert 3 <= len(colors) <= 6, (
            f"调色板 {len(colors)} 色，违反 3–6 色约束"
        )

    def test_palette_has_amber_anchor(self, engine: str) -> None:
        assert "amber" in engine, "调色板缺少暗房琥珀锚点色"


class TestBudgetConstraints:
    """数量/速度/连线预算（用户硬性约束：≤300 粒子、流速 ≤1.2）。"""

    def test_max_particles_budget(self, engine: str) -> None:
        match = re.search(r"MAX_PARTICLES\s*=\s*(\d+)", engine)
        assert match, "未找到 MAX_PARTICLES 常量"
        assert int(match.group(1)) <= 300, (
            f"MAX_PARTICLES={match.group(1)} 超出 300 上限"
        )

    def test_speed_limit_budget(self, engine: str) -> None:
        match = re.search(r"SPEED_LIMIT\s*=\s*([\d.]+)", engine)
        assert match, "未找到 SPEED_LIMIT 常量"
        assert float(match.group(1)) <= 1.2, (
            f"SPEED_LIMIT={match.group(1)} 超出 1.2 上限"
        )

    def test_connection_distance_bounded(self, engine: str) -> None:
        match = re.search(r"CONNECTION_MAX_DIST\s*=\s*(\d+)", engine)
        assert match, "未找到 CONNECTION_MAX_DIST 常量"
        assert int(match.group(1)) <= 160, "连线距离过远会产生蛛网感"

    def test_nebula_drift_clamped_by_speed_limit(self, behaviors: str) -> None:
        """环境漂移行为必须显式受 SPEED_LIMIT 约束（防高频抖动）。"""
        nebula_body = re.search(
            r"export const nebula.*?(?=export const |\Z)", behaviors, re.DOTALL
        )
        assert nebula_body, "未找到 nebula 行为"
        assert "SPEED_LIMIT" in nebula_body.group(0), (
            "nebula 漂移未用 SPEED_LIMIT 钳制"
        )


class TestSafeZone:
    """文字安全区：粒子在标题区域衰减为零。"""

    def test_safe_zone_type_and_fade(self, engine: str) -> None:
        assert re.search(r"interface\s+SafeZone", engine), "缺少 SafeZone 类型"
        assert re.search(r"export\s+const\s+safeZoneFade", engine), (
            "缺少 safeZoneFade 衰减函数"
        )

    def test_canvas_wires_safe_zones(self, canvas: str) -> None:
        assert "safeZones" in canvas, "ParticleCanvas 未接 safeZones"

    def test_demo_scenes_declare_safe_zone(self, demo: str) -> None:
        assert "safeZones" in demo, "Demo.tsx 场景未声明文字安全区"


class TestAntiFlicker:
    """防频闪：呼吸振幅小、周期长（光敏红线）。"""

    def test_twinkle_amplitude_bounded(self, engine: str) -> None:
        match = re.search(r"TWINKLE_AMPLITUDE\s*=\s*([\d.]+)", engine)
        assert match, "未找到 TWINKLE_AMPLITUDE 常量"
        assert float(match.group(1)) <= 0.1, (
            f"呼吸振幅 {match.group(1)} 超过 0.1，会产生可见闪烁"
        )

    def test_twinkle_period_minimum(self, engine: str) -> None:
        match = re.search(r"TWINKLE_PERIOD_FRAMES\s*=\s*(\d+)", engine)
        assert match, "未找到 TWINKLE_PERIOD_FRAMES 常量"
        assert int(match.group(1)) >= 45, (
            f"呼吸周期 {match.group(1)} 帧 < 45（1.5s@30fps），有频闪风险"
        )


class TestBehaviorSuite:
    """一整套行为全集：环境星云 / 汇聚 / 轨道球 / 涟漪 / 弥散。"""

    @pytest.mark.parametrize(
        "name", ["nebula", "converge", "orbit", "ripple", "scatter"]
    )
    def test_behavior_exported(self, behaviors: str, name: str) -> None:
        assert re.search(rf"export\s+const\s+{name}\b", behaviors), (
            f"行为 {name} 未导出"
        )

    def test_behavior_registry_complete(self, behaviors: str) -> None:
        match = re.search(r"BEHAVIORS\s*=\s*\{(.*?)\}", behaviors, re.DOTALL)
        assert match, "缺少 BEHAVIORS 注册表"
        for name in ["nebula", "converge", "orbit", "ripple", "scatter"]:
            assert name in match.group(1), f"BEHAVIORS 注册表缺少 {name}"

    def test_converge_uses_ease_out(self, behaviors: str) -> None:
        body = re.search(
            r"export const converge.*?(?=export const |\Z)", behaviors, re.DOTALL
        )
        assert body and "easeOutCubic" in body.group(0), (
            "converge 必须使用 easeOutCubic（物理感缓动）"
        )

    def test_orbit_has_inclination(self, behaviors: str) -> None:
        body = re.search(
            r"export const orbit.*?(?=export const |\Z)", behaviors, re.DOTALL
        )
        assert body and "tilt" in body.group(0), (
            "orbit 必须有轨道倾角（tilt）形成球面层次"
        )

    def test_ripple_expands_outward(self, behaviors: str) -> None:
        body = re.search(
            r"export const ripple.*?(?=export const |\Z)", behaviors, re.DOTALL
        )
        assert body, "未找到 ripple 行为"
        assert "maxR" in body.group(0), "ripple 必须向 maxR 外扩散"
        assert "lane" in body.group(0), "ripple 必须分环带（lane）错峰扩散"

    def test_scatter_is_gentle_fade(self, behaviors: str) -> None:
        """弥散是柔和漂移淡出，禁止粒子爆炸（用户红线）。"""
        body = re.search(
            r"export const scatter.*?(?=export const |\Z)", behaviors, re.DOTALL
        )
        assert body, "未找到 scatter 行为"
        assert "easeOutCubic" in body.group(0) or "easeOutQuad" in body.group(0), (
            "scatter 必须用缓出曲线（柔和弥散，非爆炸）"
        )


class TestDemoIntegration:
    """Demo.tsx 集成：intro 汇聚、过场涟漪、outro 轨道球、静态 hero 退役。"""

    def test_intro_uses_converge(self, demo: str) -> None:
        assert 'behavior="converge"' in demo, "intro 未接入 converge 汇聚行为"

    def test_ambient_nebula_present(self, demo: str) -> None:
        assert 'behavior="nebula"' in demo, "缺少 nebula 环境星云层"

    def test_transition_ripple_present(self, demo: str) -> None:
        assert 'behavior="ripple"' in demo, "场景过场未接入 ripple 涟漪"

    def test_outro_uses_orbit(self, demo: str) -> None:
        assert 'behavior="orbit"' in demo, "outro 未接入 orbit 轨道球"

    def test_static_hero_retired(self, demo: str) -> None:
        assert "hero-particles" not in demo, (
            "静态 hero 主视觉仍在引用 —— intro/outro 应由程序化粒子取代"
        )

    def test_legacy_svg_converge_removed(self, demo: str) -> None:
        assert "ParticleConverge" not in demo, (
            "旧 SVG ParticleConverge 实现残留，应已被 ParticleCanvas 取代"
        )

    def test_hero_assets_removed(self) -> None:
        for name in ("hero-particles.jpg", "hero-particles-v2.jpg"):
            assert not (PUBLIC_DIR / name).exists(), (
                f"退役素材 {name} 仍在 public/，应删除避免误用"
            )


class TestRenderPerformance:
    """1770 帧 × 数百粒子：必须走精灵缓存 + 发光叠加，避免逐帧渐变填充。"""

    def test_sprite_cache_used(self, engine: str) -> None:
        assert re.search(r"class\s+SpriteCache", engine), "缺少 SpriteCache 精灵缓存"

    def test_additive_blending(self, engine: str) -> None:
        assert '"lighter"' in engine or "'lighter'" in engine, (
            "粒子绘制必须用 lighter 叠加（光晕融合，暗房发光质感）"
        )

    def test_canvas_element_rendered(self, canvas: str) -> None:
        assert "<canvas" in canvas, "ParticleCanvas 必须渲染 canvas 元素"
