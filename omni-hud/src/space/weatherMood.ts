/**
 * weatherMood 天气情绪 → FieldStage 视觉联动（M23.3）。
 *
 * 把 WeatherMood 数据映射为 Three.js 场景可视参数：
 * - ``AmbientLight`` 颜色 = ``colorPalette[0]``（主色调）
 * - ``AmbientLight`` 强度 = ``particleParams.brightness × DEFAULT_AMBIENT_INTENSITY``
 * - 粒子色板 = ``colorPalette``（hex → RGB 数组，截断到 ≤6 色，CLAUDE.md §六.3 红线）
 * - 粒子密度 = ``particleParams.density × tier.particleCount``（钳到 tier 上限）
 * - 粒子流速倍率 = ``particleParams.speed``（写入 uWeatherSpeed uniform）
 * - 粒子亮度 = ``particleParams.brightness``（写入 uWeatherBrightness uniform）
 *
 * 与 M21 节奏粒子共存：weatherMood 影响 AmbientLight + 粒子色板 + 粒子密度
 * （互不冲突，叠加生效）；M21 节奏粒子影响粒子动效（bass/mid/treble/beat）。
 * 与 M5.3 语音氛围共存：voice mood 通过 setMood 设置 flowScale（影响 uFlowTime），
 * weatherMood 通过 uWeatherSpeed uniform 独立叠加（不冲突）。
 *
 * 纯逻辑模块：不依赖 three / WebGL，所有 Three.js 结构经契约接口注入，
 * fake AmbientLight / fake ParticleSystem 可独立单测。
 */
import type { WeatherMood, WeatherMoodKind } from "../data/sources";
import type { QualityTierSpec } from "./quality";

// ---------------------------------------------------------------------------
// 数值范围常量（与后端 mood_table 对齐，前端二次钳制）
// ---------------------------------------------------------------------------

/** 粒子流速倍率下限。 */
export const WEATHER_SPEED_MIN = 0.3;
/** 粒子流速倍率上限。 */
export const WEATHER_SPEED_MAX = 2.0;
/** 粒子密度倍率下限。 */
export const WEATHER_DENSITY_MIN = 0.5;
/** 粒子密度倍率上限。 */
export const WEATHER_DENSITY_MAX = 2.0;
/** 粒子亮度下限。 */
export const WEATHER_BRIGHTNESS_MIN = 0.2;
/** 粒子亮度上限。 */
export const WEATHER_BRIGHTNESS_MAX = 1.0;

/** 默认 AmbientLight 强度（暗房风克制基线，被 brightness 倍率缩放）。 */
export const DEFAULT_AMBIENT_INTENSITY = 0.5;
/** 默认 AmbientLight 颜色（暖白 RGB，clearWeatherMood 恢复到此值）。 */
export const DEFAULT_AMBIENT_COLOR: readonly [number, number, number] = [1, 0.96, 0.86];
/** 默认粒子密度倍率（1 = tier.particleCount 基线）。 */
export const DEFAULT_PARTICLE_DENSITY = 1;
/** 默认粒子流速倍率（1 = 基线，不加速不减速）。 */
export const DEFAULT_PARTICLE_SPEED = 1;
/** 默认粒子亮度（1 = 基线，不暗不亮）。 */
export const DEFAULT_PARTICLE_BRIGHTNESS = 1;

/** 主题内容色硬上限（CLAUDE.md §六.3 红线 ≤6 色）。 */
const PALETTE_MAX = 6;

// ---------------------------------------------------------------------------
// hex → RGB 解析
// ---------------------------------------------------------------------------

/**
 * hex 字符串解析为 [r, g, b] 浮点数组（0-1 区间）。
 *
 * 支持 3 位简写（``#abc`` → [10/15, 11/15, 12/15]）与 6 位标准写法（``#aabbcc``）。
 * 前导 ``#`` 可选。非法 hex / 非字符串返回 null（不抛错，调用方按 null 跳过）。
 */
export function hexToRgb(hex: string | null | undefined): [number, number, number] | null {
  if (typeof hex !== "string") return null;
  const match = /^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.exec(hex);
  if (match === null) return null;
  const digits = match[1]!;
  if (digits.length === 3) {
    const r = parseInt(digits[0]! + digits[0]!, 16);
    const g = parseInt(digits[1]! + digits[1]!, 16);
    const b = parseInt(digits[2]! + digits[2]!, 16);
    return [r / 255, g / 255, b / 255];
  }
  const r = parseInt(digits.slice(0, 2), 16);
  const g = parseInt(digits.slice(2, 4), 16);
  const b = parseInt(digits.slice(4, 6), 16);
  return [r / 255, g / 255, b / 255];
}

// ---------------------------------------------------------------------------
// FieldStage 视觉联动 target 契约
// ---------------------------------------------------------------------------

/** AmbientLight 最小契约（真实 three.AmbientLight 与 fake 均满足）。 */
export interface AmbientLightLike {
  /** 颜色对象（支持 setRGB 三参写入）。 */
  readonly color: {
    setRGB(r: number, g: number, b: number): unknown;
  };
  /** 强度数值（可写）。 */
  intensity: number;
}

/** ParticleSystem 最小契约（与 particles.ts ParticleSystem 子集对齐）。 */
export interface ParticleTargetLike {
  /** 材质 uniforms（写入 uWeatherSpeed / uWeatherBrightness 等）。 */
  readonly uniforms: Record<string, { value: unknown }>;
  /** 写入 ≤6 槽色板（hex → RGB 数组）。 */
  setPalette(palette: readonly (readonly [number, number, number])[]): void;
  /** 按画质档重建实例数（density × tier.particleCount 钳到 tier 上限）。 */
  setCount(count: number): void;
}

/**
 * WeatherMoodScene：applyWeatherMood / clearWeatherMood 消费的最小场景契约。
 *
 * 真实 Three.js scene 经 createSpace 装配时持有 AmbientLight + ParticleSystem，
 * 这里以显式字段而非 scene.children 遍历查找——契约清晰、测试无需构造完整 scene。
 * ``ambientLight`` 为 null 时跳过颜色 / 强度写入（无 Three.js light 时降级为粒子色板联动）。
 */
export interface WeatherMoodScene {
  readonly ambientLight: AmbientLightLike | null;
  readonly particles: ParticleTargetLike;
  /** 当前画质档定义（particleCount 上限钳制依据）。 */
  readonly tierSpec: QualityTierSpec;
}

/**
 * WeatherMoodSpec：buildWeatherMoodSpec 输出的可应用规格，
 * 供 Space.setWeatherMood(spec) 消费——把 mood 数据预编译为 target 友好的形式。
 */
export interface WeatherMoodSpec {
  /** AmbientLight 颜色 RGB（0-1 浮点）。 */
  readonly ambientColor: readonly [number, number, number];
  /** AmbientLight 强度。 */
  readonly ambientIntensity: number;
  /** 粒子色板 RGB 数组（≤6 色）。 */
  readonly palette: readonly (readonly [number, number, number])[];
  /** 粒子流速倍率（uWeatherSpeed uniform）。 */
  readonly flowScale: number;
  /** 粒子实例数（density × tier.particleCount 钳到 tier 上限）。 */
  readonly particleCount: number;
  /** 粒子亮度（uWeatherBrightness uniform）。 */
  readonly brightness: number;
}

/** 数值钳制到 [min, max]，NaN 视为非法返回 min。 */
function clamp(v: number, min: number, max: number): number {
  if (!Number.isFinite(v)) return min;
  return Math.min(max, Math.max(min, v));
}

/**
 * 从 WeatherMood + tierSpec 构造可应用的 WeatherMoodSpec。
 *
 * - ``ambientColor`` = colorPalette[0] 解析失败时回退到 DEFAULT_AMBIENT_COLOR
 * - ``ambientIntensity`` = brightness × DEFAULT_AMBIENT_INTENSITY
 * - ``palette`` = colorPalette 解析为 RGB 数组，过滤非法 hex，截断到 ≤6 色
 * - ``flowScale`` = particleParams.speed（已钳到 [0.3, 2.0]）
 * - ``particleCount`` = round(density × tier.particleCount)，钳到 [1, tier.particleCount]
 * - ``brightness`` = particleParams.brightness（已钳到 [0.2, 1.0]）
 */
export function buildWeatherMoodSpec(
  mood: WeatherMood,
  tierSpec: QualityTierSpec,
): WeatherMoodSpec {
  const speed = clamp(mood.particleParams.speed, WEATHER_SPEED_MIN, WEATHER_SPEED_MAX);
  const density = clamp(mood.particleParams.density, WEATHER_DENSITY_MIN, WEATHER_DENSITY_MAX);
  const brightness = clamp(
    mood.particleParams.brightness,
    WEATHER_BRIGHTNESS_MIN,
    WEATHER_BRIGHTNESS_MAX,
  );

  // colorPalette → RGB 数组，过滤 hexToRgb 返回 null 的项
  const palette = mood.colorPalette
    .map((hex) => hexToRgb(hex))
    .filter((rgb): rgb is [number, number, number] => rgb !== null)
    .slice(0, PALETTE_MAX) as (readonly [number, number, number])[];

  // ambientColor 取 palette[0]，回退到默认暖白
  const ambientColor: readonly [number, number, number] =
    palette.length > 0 ? palette[0]! : DEFAULT_AMBIENT_COLOR;

  // particleCount：density × tier 上限，钳到 [1, tier.particleCount]
  const rawCount = Math.round(density * tierSpec.particleCount);
  const particleCount = Math.min(tierSpec.particleCount, Math.max(1, rawCount));

  return {
    ambientColor,
    ambientIntensity: brightness * DEFAULT_AMBIENT_INTENSITY,
    palette,
    flowScale: speed,
    particleCount,
    brightness,
  };
}

/**
 * 把 WeatherMood 应用到场景：写入 AmbientLight 颜色 / 强度 + 粒子色板 / 密度 / uniforms。
 *
 * - ambientLight 为 null 时跳过 light 写入（不抛错，降级为仅粒子色板联动）
 * - 粒子色板为空（colorPalette 全非法 hex）时跳过 setPalette（保持原主题色板）
 * - 数值范围由 buildWeatherMoodSpec 钳制，本函数不重复钳制
 */
export function applyWeatherMood(scene: WeatherMoodScene, mood: WeatherMood): void {
  const spec = buildWeatherMoodSpec(mood, scene.tierSpec);

  // AmbientLight 颜色 + 强度
  if (scene.ambientLight !== null) {
    const [r, g, b] = spec.ambientColor;
    scene.ambientLight.color.setRGB(r, g, b);
    scene.ambientLight.intensity = spec.ambientIntensity;
  }

  // 粒子色板（空 palette 跳过，保持原色板不动）
  if (spec.palette.length > 0) {
    scene.particles.setPalette(spec.palette);
  }

  // 粒子密度（density × tier.particleCount 钳到 tier 上限）
  scene.particles.setCount(spec.particleCount);

  // uniforms：流速倍率 + 亮度
  const uniforms = scene.particles.uniforms;
  if ("uWeatherSpeed" in uniforms) {
    uniforms.uWeatherSpeed!.value = spec.flowScale;
  }
  if ("uWeatherBrightness" in uniforms) {
    uniforms.uWeatherBrightness!.value = spec.brightness;
  }
}

/**
 * 恢复场景为默认 AmbientLight + 粒子参数。
 *
 * - AmbientLight 颜色 = DEFAULT_AMBIENT_COLOR，强度 = DEFAULT_AMBIENT_INTENSITY
 * - 粒子密度 = tier.particleCount（基线，不缩放）
 * - uWeatherSpeed = 1, uWeatherBrightness = 1（no-op 倍率，等价于无天气情绪叠加）
 *
 * 幂等：多次调用不累积副作用（已是默认值时跳过 color.setRGB 调用）。
 */
export function clearWeatherMood(scene: WeatherMoodScene): void {
  if (scene.ambientLight !== null) {
    const [r, g, b] = DEFAULT_AMBIENT_COLOR;
    scene.ambientLight.color.setRGB(r, g, b);
    scene.ambientLight.intensity = DEFAULT_AMBIENT_INTENSITY;
  }
  scene.particles.setCount(scene.tierSpec.particleCount);
  const uniforms = scene.particles.uniforms;
  if ("uWeatherSpeed" in uniforms) {
    uniforms.uWeatherSpeed!.value = DEFAULT_PARTICLE_SPEED;
  }
  if ("uWeatherBrightness" in uniforms) {
    uniforms.uWeatherBrightness!.value = DEFAULT_PARTICLE_BRIGHTNESS;
  }
}

/**
 * 在两个 WeatherMood 之间线性插值（用于平滑过渡 ~1.5s ease-out）。
 *
 * - 数值字段（temperature / particleParams.speed/density/brightness）线性插值
 * - 枚举字段（mood）：t=0 取 prev.mood，t>0 取 next.mood（枚举不插值，避免出现未定义中间态；
 *   起点保留 prev 语义，过渡一开始即切到 next）
 * - colorPalette 取 next.colorPalette（颜色不做 RGB 插值，避免色彩混合破坏暗房风）
 * - description / weatherCode / cachedAt 取 next 值
 * - t 钳制到 [0, 1]，NaN 视为 0（回退 prev）
 *
 * 返回新对象（不修改 prev / next），调用方可多次采样实现 ease-out 曲线。
 */
export function interpolateWeatherMood(
  prev: WeatherMood,
  next: WeatherMood,
  t: number,
): WeatherMood {
  const tt = Number.isFinite(t) ? Math.min(1, Math.max(0, t)) : 0;
  const lerp = (a: number, b: number): number => a + (b - a) * tt;
  return {
    mood: tt === 0 ? prev.mood : next.mood,
    description: next.description,
    colorPalette: next.colorPalette,
    particleParams: {
      speed: lerp(prev.particleParams.speed, next.particleParams.speed),
      density: lerp(prev.particleParams.density, next.particleParams.density),
      brightness: lerp(prev.particleParams.brightness, next.particleParams.brightness),
    },
    temperature: lerp(prev.temperature, next.temperature),
    weatherCode: next.weatherCode,
    cachedAt: next.cachedAt,
  };
}

/**
 * 天气情绪枚举 → Lucide React 图标名映射（MiniBar 显示用）。
 *
 * Lucide React 是前端唯一图标源（CLAUDE.md §五），返回值为 Icon.tsx 已登记的图标名。
 * ``unknown`` 回退到 ``cloud``（中性云图标）。
 */
export function moodKindToIcon(kind: WeatherMoodKind): string {
  switch (kind) {
    case "sunny":
      return "sun";
    case "calm":
      return "cloud";
    case "melancholy":
      return "cloud-rain";
    case "dreamy":
      return "cloud-fog";
    case "mysterious":
      return "cloud-snow";
    case "dramatic":
      return "cloud-lightning";
    case "unknown":
      return "cloud";
  }
}
