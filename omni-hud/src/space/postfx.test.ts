/**
 * postfx 测试（M5.1 TDD 红）：验证效果链组装契约——
 * Bloom 强度随画质档变化、vignette 存在且强度在克制范围、grain 为静态颗粒。
 * 注入 fake three/examples 模块，不创建真实 WebGL 上下文。
 */
import { describe, expect, it, vi } from "vitest";

import { createPostfx } from "./postfx";
import type { PostfxDeps } from "./postfx";

function makeFakePostModules() {
  const passes: Array<{ kind: string; opts?: unknown; enabled: boolean }> = [];
  const composers: EffectComposer[] = [];
  class WebGLRenderTarget {
    dispose = vi.fn();
    constructor(public width: number, public height: number, public options?: unknown) {}
  }
  class EffectComposer {
    passes: unknown[] = [];
    addPass = vi.fn((pass: { kind: string }) => {
      this.passes.push(pass);
    });
    setSize = vi.fn();
    setPixelRatio = vi.fn();
    render = vi.fn();
    dispose = vi.fn();
    constructor(public renderer: unknown, public renderTarget?: unknown) {
      composers.push(this);
    }
  }
  class RenderPass {
    kind = "render";
    enabled = true;
    constructor(
      public scene: unknown,
      public camera: unknown,
    ) {
      passes.push({ kind: "render", enabled: true });
    }
  }
  class UnrealBloomPass {
    kind = "bloom";
    enabled = true;
    strength: number;
    radius: number;
    threshold: number;
    constructor(
      public resolution: unknown,
      strength: number,
      radius: number,
      threshold: number,
    ) {
      this.strength = strength;
      this.radius = radius;
      this.threshold = threshold;
      // opts 持有 pass 实例本身：实现侧改 bloom.strength 时测试能读到活值
      passes.push({ kind: "bloom", opts: this, enabled: true });
    }
  }
  class ShaderPass {
    kind = "shader";
    enabled = true;
    uniforms: Record<string, { value: unknown }>;
    constructor(public shader: { uniforms?: Record<string, { value: unknown }> }) {
      this.uniforms = shader.uniforms ?? {};
      passes.push({ kind: "shader", opts: this, enabled: true });
    }
  }
  class OutputPass {
    kind = "output";
    enabled = true;
    constructor() {
      passes.push({ kind: "output", enabled: true });
    }
  }
  return {
    WebGLRenderTarget,
    HalfFloatType: 1,
    RGBAFormat: 2,
    LinearFilter: 1,
    LinearSRGBColorSpace: "srgb-linear",
    EffectComposer,
    RenderPass,
    UnrealBloomPass,
    ShaderPass,
    OutputPass,
    __passes: passes,
    __composers: composers,
  };
}

function makeDeps(): { deps: PostfxDeps; fake: ReturnType<typeof makeFakePostModules> } {
  const fake = makeFakePostModules();
  const deps: PostfxDeps = {
    modules: fake as unknown as PostfxDeps["modules"],
    renderer: {} as PostfxDeps["renderer"],
    scene: {} as PostfxDeps["scene"],
    camera: {} as PostfxDeps["camera"],
    width: 1280,
    height: 800,
  };
  return { deps, fake };
}

describe("createPostfx 效果链组装", () => {
  it("效果链顺序：render → bloom → vignette/grain（shader）→ output", () => {
    const { deps, fake } = makeDeps();
    const postfx = createPostfx(deps, { tier: "high" });
    const kinds = fake.__passes.map((p) => p.kind);
    expect(kinds[0]).toBe("render");
    expect(kinds).toContain("bloom");
    expect(kinds).toContain("shader");
    expect(kinds[kinds.length - 1]).toBe("output");
    // bloom 在 shader 之前
    expect(kinds.indexOf("bloom")).toBeLessThan(kinds.indexOf("shader"));
    postfx.dispose();
  });

  it("high 档 bloom 强度高于 low 档（克制区间，high ≤ 0.9）", () => {
    const { deps, fake } = makeDeps();
    const high = createPostfx(deps, { tier: "high" });
    const highBloom = fake.__passes.find((p) => p.kind === "bloom")!;
    const highStrength = (highBloom.opts as { strength: number }).strength;
    high.dispose();

    fake.__passes.length = 0;
    const low = createPostfx(deps, { tier: "low" });
    const lowBloom = fake.__passes.find((p) => p.kind === "bloom")!;
    const lowStrength = (lowBloom.opts as { strength: number }).strength;
    low.dispose();

    expect(highStrength).toBeGreaterThan(lowStrength);
    expect(highStrength).toBeLessThanOrEqual(0.9);
    expect(lowStrength).toBeGreaterThan(0);
  });

  it("setQuality 动态调整 bloom 强度", () => {
    const { deps, fake } = makeDeps();
    const postfx = createPostfx(deps, { tier: "high" });
    const bloom = fake.__passes.find((p) => p.kind === "bloom")!;
    const initial = (bloom.opts as { strength: number }).strength;
    postfx.setQuality("low");
    // setQuality 后 bloom 强度应被改写（通过 pass.strength 或重建）
    const after = (bloom.opts as { strength: number }).strength;
    expect(after).toBeLessThan(initial);
    postfx.dispose();
  });

  it("vignette shader uniform 强度 ∈ (0, 0.55]（克制，不黑边糊脸）", () => {
    const { deps } = makeDeps();
    const postfx = createPostfx(deps, { tier: "medium" });
    const vignette = postfx.getVignetteStrength();
    expect(vignette).toBeGreaterThan(0);
    expect(vignette).toBeLessThanOrEqual(0.55);
    postfx.dispose();
  });

  it("grain 为静态颗粒：amount 小且非 0，grainTime 离散步进（未跨步不变，跨步量化跳变）", () => {
    const { deps, fake } = makeDeps();
    const postfx = createPostfx(deps, { tier: "medium" });
    const grain = postfx.getGrainAmount();
    expect(grain).toBeGreaterThan(0);
    expect(grain).toBeLessThanOrEqual(0.08);

    const shader = fake.__passes.find((p) => p.kind === "shader")!.opts as {
      uniforms: Record<string, { value: unknown }>;
    };
    const grainTime = (): number => shader.uniforms.grainTime!.value as number;
    // 小步累积未跨过 1/8s 量化边界：grainTime 保持不变（不逐帧闪烁）
    postfx.render(1 / 60);
    const t0 = grainTime();
    postfx.render(1 / 60);
    postfx.render(1 / 60);
    expect(grainTime()).toBe(t0);
    // 累计越过 1/8s：量化跳变到下一个步进值
    for (let i = 0; i < 7; i += 1) postfx.render(1 / 60);
    expect(grainTime()).toBeGreaterThan(t0);
    expect(grainTime()).toBeCloseTo(1 / 8, 5);
    postfx.dispose();
  });

  it("resize 同步 composer 尺寸", () => {
    const { deps, fake } = makeDeps();
    const postfx = createPostfx(deps, { tier: "medium" });
    postfx.resize(640, 480);
    const composer = fake.__composers[0]!;
    expect(composer.setSize).toHaveBeenLastCalledWith(640, 480);
    postfx.dispose();
  });

  it("render 委托给 composer.render", () => {
    const { deps, fake } = makeDeps();
    const postfx = createPostfx(deps, { tier: "medium" });
    const composer = fake.__composers[0]!;
    postfx.render(1 / 60);
    expect(composer.render).toHaveBeenCalledTimes(1);
    postfx.dispose();
  });

  it("非法画质档抛 RangeError", () => {
    const { deps } = makeDeps();
    expect(() => createPostfx(deps, { tier: "ultra" as never })).toThrow(RangeError);
  });
});

describe("createPostfx M21.8 强拍 bloom 脉冲 + 色差 + 暗角呼吸", () => {
  it("setBeatPulse 抬升 bloom 强度（叠加 beatPulse * MAX_BEAT_BLOOM_BOOST 增量）", () => {
    const { deps, fake } = makeDeps();
    const postfx = createPostfx(deps, { tier: "high" });
    const bloom = fake.__passes.find((p) => p.kind === "bloom")!.opts as { strength: number };
    const baseline = bloom.strength;
    postfx.setBeatPulse(2);
    postfx.render(1 / 60);
    expect(bloom.strength).toBeGreaterThan(baseline);
    expect(postfx.getBeatPulse()).toBeGreaterThan(0);
    postfx.dispose();
  });

  it("beatPulse 指数衰减：render 多帧后强度回落到 0", () => {
    const { deps } = makeDeps();
    const postfx = createPostfx(deps, { tier: "high" });
    postfx.setBeatPulse(2);
    // 衰减时间常数 0.15s；2 * exp(-2/0.15) ≈ 3e-6，低于 0.001 阈值后被钳到 0
    for (let i = 0; i < 120; i += 1) postfx.render(1 / 60);
    expect(postfx.getBeatPulse()).toBe(0);
    postfx.dispose();
  });

  it("setBeatPulse(0) 硬重置：立即清零衰减中的脉冲（停止音乐模式语义）", () => {
    const { deps, fake } = makeDeps();
    const postfx = createPostfx(deps, { tier: "high" });
    const bloom = fake.__passes.find((p) => p.kind === "bloom")!.opts as { strength: number };
    postfx.setBeatPulse(2);
    postfx.render(1 / 60);
    expect(postfx.getBeatPulse()).toBeGreaterThan(0);
    const lifted = bloom.strength;
    postfx.setBeatPulse(0);
    postfx.render(1 / 60);
    expect(postfx.getBeatPulse()).toBe(0);
    expect(bloom.strength).toBeLessThan(lifted);
    postfx.dispose();
  });

  it("setBeatPulse 取较大值：新拍点叠加到进行中脉冲但不覆盖更强脉冲", () => {
    const { deps } = makeDeps();
    const postfx = createPostfx(deps, { tier: "high" });
    postfx.setBeatPulse(2);
    postfx.setBeatPulse(1); // 较弱新拍点不覆盖更强进行中脉冲
    expect(postfx.getBeatPulse()).toBe(2);
    postfx.setBeatPulse(3); // 更强新拍点覆盖
    expect(postfx.getBeatPulse()).toBe(3);
    postfx.dispose();
  });

  it("beatPulse 触发色差与暗角呼吸 uniform（非零），归零后同步清零", () => {
    const { deps, fake } = makeDeps();
    const postfx = createPostfx(deps, { tier: "high" });
    const shader = fake.__passes.find((p) => p.kind === "shader")!.opts as {
      uniforms: Record<string, { value: unknown }>;
    };
    postfx.setBeatPulse(2);
    postfx.render(1 / 60);
    expect(shader.uniforms.chromaticAberration!.value as number).toBeGreaterThan(0);
    expect(shader.uniforms.vignetteBreath!.value as number).toBeGreaterThan(0);
    expect(shader.uniforms.breathPhase!.value as number).toBeGreaterThan(0);
    // 硬重置 + 渲染一帧 → 色差与呼吸归零
    postfx.setBeatPulse(0);
    postfx.render(1 / 60);
    expect(shader.uniforms.chromaticAberration!.value as number).toBe(0);
    expect(shader.uniforms.vignetteBreath!.value as number).toBe(0);
    postfx.dispose();
  });

  it("setBeatPulse 钳制 [0,3]，NaN 视为 0", () => {
    const { deps } = makeDeps();
    const postfx = createPostfx(deps, { tier: "high" });
    postfx.setBeatPulse(99);
    expect(postfx.getBeatPulse()).toBe(3);
    postfx.setBeatPulse(-5);
    expect(postfx.getBeatPulse()).toBe(0);
    postfx.setBeatPulse(Number.NaN);
    expect(postfx.getBeatPulse()).toBe(0);
    postfx.dispose();
  });
});
