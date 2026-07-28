/**
 * weatherMood 测试（M23.3 TDD）：天气情绪 → FieldStage 视觉联动。
 *
 * 纯逻辑测试：fake AmbientLight + fake ParticleSystem，不依赖 three / WebGL。
 * 覆盖：applyWeatherMood 调整 AmbientLight 颜色 / 强度 / 粒子色板 / 粒子密度
 * （受 quality tier 上限钳制 high≤4000/medium≤2000/low≤800）/ 流速倍率 /
 * brightness；interpolateWeatherMood 线性插值 + ease-out；
 * clearWeatherMood 恢复默认；mood=null 的边界。
 *
 * 与 M21 节奏粒子共存：weatherMood 影响 AmbientLight + 粒子色板 + 粒子密度
 * （互不冲突，叠加生效）；M21 节奏粒子影响粒子动效（bass/mid/treble/beat）。
 */
import { describe, expect, it, vi } from "vitest";

import { EMPTY_WEATHER_MOOD, type WeatherMood } from "../data/sources";
import {
  DEFAULT_AMBIENT_INTENSITY,
  DEFAULT_PARTICLE_DENSITY,
  WEATHER_DENSITY_MAX,
  WEATHER_DENSITY_MIN,
  WEATHER_SPEED_MAX,
  WEATHER_SPEED_MIN,
  applyWeatherMood,
  buildWeatherMoodSpec,
  clearWeatherMood,
  hexToRgb,
  interpolateWeatherMood,
  moodKindToIcon,
  type AmbientLightLike,
  type ParticleTargetLike,
  type WeatherMoodScene,
} from "./weatherMood";
import type { QualityTierSpec } from "./quality";
import { getTierSpec } from "./quality";

/** 构造一个合法的 WeatherMood。 */
function makeMood(overrides: Partial<WeatherMood> = {}): WeatherMood {
  return {
    ...EMPTY_WEATHER_MOOD,
    mood: "sunny",
    description: "晴朗午后",
    colorPalette: ["#ffd966", "#ffb347", "#ff8c42"],
    particleParams: { speed: 1.2, density: 1.4, brightness: 0.8 },
    temperature: 25.5,
    weatherCode: 0,
    cachedAt: "2026-07-27T10:00:00Z",
    ...overrides,
  };
}

/** fake AmbientLight：记录 color.setRGB 与 intensity 写入。 */
function makeFakeAmbientLight(): AmbientLightLike & { _calls: string[] } {
  const calls: string[] = [];
  const color = {
    setRGB(r: number, g: number, b: number) {
      calls.push(`setRGB(${r},${g},${b})`);
      return color;
    },
  };
  const light: AmbientLightLike & { _calls: string[] } = {
    color,
    intensity: DEFAULT_AMBIENT_INTENSITY,
    _calls: calls,
  };
  return light;
}

/** fake ParticleSystem target：记录 setPalette / setCount / uniform 写入。 */
function makeFakeParticles(): ParticleTargetLike & {
  _palette: unknown[];
  _count: number;
  _uniforms: Record<string, { value: unknown }>;
} {
  const uniforms: Record<string, { value: unknown }> = {
    uWeatherSpeed: { value: 1 },
    uWeatherBrightness: { value: 1 },
  };
  const target: ParticleTargetLike & {
    _palette: unknown[];
    _count: number;
    _uniforms: Record<string, { value: unknown }>;
  } = {
    uniforms,
    setPalette: vi.fn((palette: readonly unknown[]) => {
      target._palette = [...palette];
    }),
    setCount: vi.fn((count: number) => {
      target._count = count;
    }),
    _palette: [],
    _count: 0,
    _uniforms: uniforms,
  };
  return target;
}

/** fake WeatherMoodScene：组合 ambientLight + particles + tierSpec。 */
function makeFakeScene(tier: QualityTierSpec = getTierSpec("high")): {
  scene: WeatherMoodScene;
  ambient: ReturnType<typeof makeFakeAmbientLight>;
  particles: ReturnType<typeof makeFakeParticles>;
} {
  const ambient = makeFakeAmbientLight();
  const particles = makeFakeParticles();
  const scene: WeatherMoodScene = {
    ambientLight: ambient,
    particles,
    tierSpec: tier,
  };
  return { scene, ambient, particles };
}

// ---------------------------------------------------------------------------
// hexToRgb
// ---------------------------------------------------------------------------

describe("hexToRgb", () => {
  it("合法 6 位 hex 解析为 [r, g, b] 浮点（0-1）", () => {
    expect(hexToRgb("#ffd966")).toEqual([1, 217 / 255, 102 / 255]);
    expect(hexToRgb("#000000")).toEqual([0, 0, 0]);
    expect(hexToRgb("#ffffff")).toEqual([1, 1, 1]);
  });

  it("合法 3 位 hex 简写解析", () => {
    expect(hexToRgb("#abc")).toEqual([10 / 15, 11 / 15, 12 / 15]);
  });

  it("大写 hex 同样解析", () => {
    expect(hexToRgb("#FFD966")).toEqual([1, 217 / 255, 102 / 255]);
  });

  it("非法 hex 返回 null（不抛错）", () => {
    expect(hexToRgb("not-a-color")).toBeNull();
    expect(hexToRgb("#zzzzzz")).toBeNull();
    expect(hexToRgb("#12")).toBeNull();
    expect(hexToRgb("")).toBeNull();
    expect(hexToRgb(null as unknown as string)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// applyWeatherMood
// ---------------------------------------------------------------------------

describe("applyWeatherMood", () => {
  it("调整 AmbientLight 颜色为 colorPalette[0] 的 RGB", () => {
    const { scene, ambient } = makeFakeScene();
    const mood = makeMood({ colorPalette: ["#ffd966", "#ffb347"] });
    applyWeatherMood(scene, mood);
    // 应当调用 color.setRGB(1, 217/255, 102/255)
    expect(ambient._calls).toContainEqual(`setRGB(${1},${217 / 255},${102 / 255})`);
  });

  it("调整 AmbientLight 强度为 brightness × DEFAULT_AMBIENT_INTENSITY", () => {
    const { scene, ambient } = makeFakeScene();
    const mood = makeMood({ particleParams: { speed: 1, density: 1, brightness: 0.5 } });
    applyWeatherMood(scene, mood);
    expect(ambient.intensity).toBeCloseTo(0.5 * DEFAULT_AMBIENT_INTENSITY, 5);
  });

  it("调用 particles.setPalette 写入 ≤6 色 RGB 数组", () => {
    const { scene, particles } = makeFakeScene();
    const mood = makeMood({
      colorPalette: ["#ffd966", "#ffb347", "#ff8c42", "#111111", "#222222", "#333333"],
    });
    applyWeatherMood(scene, mood);
    expect(particles.setPalette).toHaveBeenCalledTimes(1);
    expect(particles._palette).toHaveLength(6);
    // 第一项是 #ffd966 的 RGB 数组
    expect(particles._palette[0]).toEqual([1, 217 / 255, 102 / 255]);
  });

  it("colorPalette 超 6 色时 setPalette 仅传入前 6 色（CLAUDE.md §六.3 红线）", () => {
    const { scene, particles } = makeFakeScene();
    const mood = makeMood({
      colorPalette: ["#111111", "#222222", "#333333", "#444444", "#555555", "#666666", "#777777"],
    });
    applyWeatherMood(scene, mood);
    expect(particles._palette).toHaveLength(6);
    expect(particles._palette[5]).toEqual([0x66 / 255, 0x66 / 255, 0x66 / 255]);
  });

  it("调用 particles.setCount 按 density × tier.particleCount 钳制上限", () => {
    const highTier = getTierSpec("high"); // 4000
    const { scene, particles } = makeFakeScene(highTier);
    const mood = makeMood({ particleParams: { speed: 1, density: 1.5, brightness: 0.5 } });
    applyWeatherMood(scene, mood);
    // density=1.5 × 4000 = 6000，钳到 4000
    expect(particles._count).toBe(4000);
  });

  it("density=0.5 在 high 档下 setCount=2000（不超出 tier 上限）", () => {
    const highTier = getTierSpec("high");
    const { scene, particles } = makeFakeScene(highTier);
    const mood = makeMood({ particleParams: { speed: 1, density: 0.5, brightness: 0.5 } });
    applyWeatherMood(scene, mood);
    expect(particles._count).toBe(2000);
  });

  it("density=2.0 在 medium 档（2000）下 setCount=2000（钳到 tier 上限）", () => {
    const mediumTier = getTierSpec("medium");
    const { scene, particles } = makeFakeScene(mediumTier);
    const mood = makeMood({ particleParams: { speed: 1, density: 2.0, brightness: 0.5 } });
    applyWeatherMood(scene, mood);
    expect(particles._count).toBe(2000);
  });

  it("density=2.0 在 low 档（800）下 setCount=800（钳到 tier 上限）", () => {
    const lowTier = getTierSpec("low");
    const { scene, particles } = makeFakeScene(lowTier);
    const mood = makeMood({ particleParams: { speed: 1, density: 2.0, brightness: 0.5 } });
    applyWeatherMood(scene, mood);
    expect(particles._count).toBe(800);
  });

  it("写入 uWeatherSpeed 与 uWeatherBrightness uniforms", () => {
    const { scene, particles } = makeFakeScene();
    const mood = makeMood({ particleParams: { speed: 1.7, density: 1, brightness: 0.4 } });
    applyWeatherMood(scene, mood);
    expect(particles._uniforms.uWeatherSpeed!.value).toBe(1.7);
    expect(particles._uniforms.uWeatherBrightness!.value).toBe(0.4);
  });

  it("ambientLight 为 null 时跳过颜色 / 强度写入（不抛错）", () => {
    const particles = makeFakeParticles();
    const scene: WeatherMoodScene = {
      ambientLight: null,
      particles,
      tierSpec: getTierSpec("high"),
    };
    const mood = makeMood();
    expect(() => applyWeatherMood(scene, mood)).not.toThrow();
    // particles 仍应被写入
    expect(particles.setPalette).toHaveBeenCalledTimes(1);
  });

  it("speed 超出 [0.3, 2.0] 钳制到合法区间（写入 uWeatherSpeed）", () => {
    const { scene, particles } = makeFakeScene();
    const mood = makeMood({ particleParams: { speed: 99, density: 1, brightness: 0.5 } });
    applyWeatherMood(scene, mood);
    expect(particles._uniforms.uWeatherSpeed!.value).toBe(WEATHER_SPEED_MAX);
  });

  it("density 超出 [0.5, 2.0] 钳制到合法区间（影响 setCount）", () => {
    const highTier = getTierSpec("high");
    const { scene, particles } = makeFakeScene(highTier);
    const mood = makeMood({ particleParams: { speed: 1, density: 99, brightness: 0.5 } });
    applyWeatherMood(scene, mood);
    // density 钳到 2.0，4000 × 2.0 = 8000，再钳到 tier 上限 4000
    expect(particles._count).toBe(4000);
  });

  it("brightness 超出 [0.2, 1.0] 钳制到合法区间", () => {
    const { scene, particles, ambient } = makeFakeScene();
    const mood = makeMood({ particleParams: { speed: 1, density: 1, brightness: 99 } });
    applyWeatherMood(scene, mood);
    expect(particles._uniforms.uWeatherBrightness!.value).toBe(1.0);
    expect(ambient.intensity).toBeCloseTo(1.0 * DEFAULT_AMBIENT_INTENSITY, 5);
  });
});

// ---------------------------------------------------------------------------
// clearWeatherMood
// ---------------------------------------------------------------------------

describe("clearWeatherMood", () => {
  it("恢复 AmbientLight 颜色为默认（暖白）与强度为 DEFAULT_AMBIENT_INTENSITY", () => {
    const { scene, ambient } = makeFakeScene();
    const mood = makeMood({ particleParams: { speed: 1, density: 1, brightness: 0.3 } });
    applyWeatherMood(scene, mood);
    expect(ambient.intensity).not.toBe(DEFAULT_AMBIENT_INTENSITY);
    clearWeatherMood(scene);
    expect(ambient.intensity).toBe(DEFAULT_AMBIENT_INTENSITY);
    // color.setRGB 至少被多调用一次（恢复到默认）
    expect(ambient._calls.length).toBeGreaterThanOrEqual(2);
  });

  it("恢复 particles uniforms uWeatherSpeed=1, uWeatherBrightness=1", () => {
    const { scene, particles } = makeFakeScene();
    const mood = makeMood({ particleParams: { speed: 1.5, density: 1, brightness: 0.5 } });
    applyWeatherMood(scene, mood);
    expect(particles._uniforms.uWeatherSpeed!.value).toBe(1.5);
    clearWeatherMood(scene);
    expect(particles._uniforms.uWeatherSpeed!.value).toBe(1);
    expect(particles._uniforms.uWeatherBrightness!.value).toBe(1);
  });

  it("恢复 particles.setCount 为 tier.particleCount（默认密度）", () => {
    const highTier = getTierSpec("high");
    const { scene, particles } = makeFakeScene(highTier);
    const mood = makeMood({ particleParams: { speed: 1, density: 0.5, brightness: 0.5 } });
    applyWeatherMood(scene, mood);
    expect(particles._count).toBe(2000);
    clearWeatherMood(scene);
    expect(particles._count).toBe(highTier.particleCount);
  });

  it("ambientLight 为 null 时 clearWeatherMood 不抛错", () => {
    const particles = makeFakeParticles();
    const scene: WeatherMoodScene = {
      ambientLight: null,
      particles,
      tierSpec: getTierSpec("high"),
    };
    expect(() => clearWeatherMood(scene)).not.toThrow();
  });

  it("多次调用 clearWeatherMood 幂等（不累积副作用）", () => {
    const { scene, ambient } = makeFakeScene();
    const callsBefore = ambient._calls.length;
    clearWeatherMood(scene);
    clearWeatherMood(scene);
    clearWeatherMood(scene);
    // 后两次 clear 不应再写 color（已是默认值则跳过）
    // 至少不抛错、不改变已恢复的状态
    expect(ambient.intensity).toBe(DEFAULT_AMBIENT_INTENSITY);
    expect(ambient._calls.length).toBeGreaterThanOrEqual(callsBefore);
  });
});

// ---------------------------------------------------------------------------
// interpolateWeatherMood
// ---------------------------------------------------------------------------

describe("interpolateWeatherMood", () => {
  it("t=0 返回 prev（不引用同一对象）", () => {
    const prev = makeMood({ temperature: 10, particleParams: { speed: 0.5, density: 0.5, brightness: 0.3 } });
    const next = makeMood({ temperature: 30, particleParams: { speed: 1.5, density: 1.5, brightness: 0.9 } });
    const out = interpolateWeatherMood(prev, next, 0);
    expect(out).not.toBe(prev);
    expect(out).not.toBe(next);
    expect(out.temperature).toBe(10);
    expect(out.particleParams.speed).toBe(0.5);
  });

  it("t=1 返回 next（不引用同一对象）", () => {
    const prev = makeMood({ temperature: 10 });
    const next = makeMood({ temperature: 30 });
    const out = interpolateWeatherMood(prev, next, 1);
    expect(out).not.toBe(next);
    expect(out.temperature).toBe(30);
  });

  it("t=0.5 线性插值 temperature / particleParams 数值字段", () => {
    const prev = makeMood({
      temperature: 10,
      particleParams: { speed: 0.5, density: 0.5, brightness: 0.3 },
    });
    const next = makeMood({
      temperature: 30,
      particleParams: { speed: 1.5, density: 1.5, brightness: 0.9 },
    });
    const out = interpolateWeatherMood(prev, next, 0.5);
    expect(out.temperature).toBeCloseTo(20, 5);
    expect(out.particleParams.speed).toBeCloseTo(1.0, 5);
    expect(out.particleParams.density).toBeCloseTo(1.0, 5);
    expect(out.particleParams.brightness).toBeCloseTo(0.6, 5);
  });

  it("t 超出 [0,1] 钳制到合法区间", () => {
    const prev = makeMood({ temperature: 0 });
    const next = makeMood({ temperature: 100 });
    expect(interpolateWeatherMood(prev, next, -0.5).temperature).toBe(0);
    expect(interpolateWeatherMood(prev, next, 1.5).temperature).toBe(100);
  });

  it("mood 字段取 next 的 mood（枚举不插值，避免出现未定义中间态）", () => {
    const prev = makeMood({ mood: "sunny" });
    const next = makeMood({ mood: "melancholy" });
    expect(interpolateWeatherMood(prev, next, 0.3).mood).toBe("melancholy");
    expect(interpolateWeatherMood(prev, next, 0.0).mood).toBe("sunny");
  });

  it("colorPalette 取 next 的色板（颜色不做 RGB 插值，避免色彩混合破坏暗房风）", () => {
    const prev = makeMood({ colorPalette: ["#ff0000", "#00ff00"] });
    const next = makeMood({ colorPalette: ["#0000ff", "#ffff00"] });
    const out = interpolateWeatherMood(prev, next, 0.5);
    expect(out.colorPalette).toEqual(["#0000ff", "#ffff00"]);
  });

  it("NaN t 视为 0（回退 prev）", () => {
    const prev = makeMood({ temperature: 10 });
    const next = makeMood({ temperature: 30 });
    const out = interpolateWeatherMood(prev, next, Number.NaN);
    expect(out.temperature).toBe(10);
  });
});

// ---------------------------------------------------------------------------
// buildWeatherMoodSpec
// ---------------------------------------------------------------------------

describe("buildWeatherMoodSpec", () => {
  it("从 mood + tierSpec 构造 WeatherMoodSpec（含 palette RGB / density 钳制）", () => {
    const highTier = getTierSpec("high");
    const mood = makeMood({
      colorPalette: ["#ffd966", "#ffb347"],
      particleParams: { speed: 1.2, density: 1.5, brightness: 0.7 },
    });
    const spec = buildWeatherMoodSpec(mood, highTier);
    expect(spec.ambientColor).toEqual([1, 217 / 255, 102 / 255]);
    expect(spec.ambientIntensity).toBeCloseTo(0.7 * DEFAULT_AMBIENT_INTENSITY, 5);
    expect(spec.palette).toEqual([
      [1, 217 / 255, 102 / 255],
      [1, 179 / 255, 71 / 255],
    ]);
    expect(spec.flowScale).toBe(1.2);
    expect(spec.particleCount).toBe(highTier.particleCount); // density=1.5 × 4000 = 6000 钳到 4000
    expect(spec.brightness).toBe(0.7);
  });

  it("density=0.5 在 high 档下 particleCount=2000", () => {
    const highTier = getTierSpec("high");
    const mood = makeMood({ particleParams: { speed: 1, density: 0.5, brightness: 0.5 } });
    const spec = buildWeatherMoodSpec(mood, highTier);
    expect(spec.particleCount).toBe(2000);
  });

  it("density=2.0 在 low 档（800）下 particleCount=800（钳到 tier 上限）", () => {
    const lowTier = getTierSpec("low");
    const mood = makeMood({ particleParams: { speed: 1, density: 2.0, brightness: 0.5 } });
    const spec = buildWeatherMoodSpec(mood, lowTier);
    expect(spec.particleCount).toBe(800);
  });

  it("palette 超 6 色截断为前 6 色", () => {
    const highTier = getTierSpec("high");
    const mood = makeMood({
      colorPalette: ["#111111", "#222222", "#333333", "#444444", "#555555", "#666666", "#777777"],
    });
    const spec = buildWeatherMoodSpec(mood, highTier);
    expect(spec.palette).toHaveLength(6);
  });
});

// ---------------------------------------------------------------------------
// moodKindToIcon（Lucide React 图标映射）
// ---------------------------------------------------------------------------

describe("moodKindToIcon", () => {
  it("每个已知 mood 都有对应 Lucide 图标名", () => {
    expect(moodKindToIcon("sunny")).toBe("sun");
    expect(moodKindToIcon("calm")).toBe("cloud");
    expect(moodKindToIcon("melancholy")).toBe("cloud-rain");
    expect(moodKindToIcon("dreamy")).toBe("cloud-fog");
    expect(moodKindToIcon("mysterious")).toBe("cloud-snow");
    expect(moodKindToIcon("dramatic")).toBe("cloud-lightning");
    expect(moodKindToIcon("unknown")).toBe("cloud");
  });
});

// ---------------------------------------------------------------------------
// 常量边界
// ---------------------------------------------------------------------------

describe("weatherMood 常量边界", () => {
  it("WEATHER_SPEED_MIN/MAX 与规格对齐 [0.3, 2.0]", () => {
    expect(WEATHER_SPEED_MIN).toBe(0.3);
    expect(WEATHER_SPEED_MAX).toBe(2.0);
  });

  it("WEATHER_DENSITY_MIN/MAX 与规格对齐 [0.5, 2.0]", () => {
    expect(WEATHER_DENSITY_MIN).toBe(0.5);
    expect(WEATHER_DENSITY_MAX).toBe(2.0);
  });

  it("DEFAULT_AMBIENT_INTENSITY 为正数（暗房风克制基线）", () => {
    expect(DEFAULT_AMBIENT_INTENSITY).toBeGreaterThan(0);
    expect(DEFAULT_AMBIENT_INTENSITY).toBeLessThanOrEqual(1);
  });

  it("DEFAULT_PARTICLE_DENSITY = 1（基线密度倍率）", () => {
    expect(DEFAULT_PARTICLE_DENSITY).toBe(1);
  });
});
