/**
 * themeBridge（M5.1）：Film Atelier 主题 → 3D 场景参数映射（雾色 / 色板槽位 /
 * bloom 微调），以及主题切换的 260ms 平滑过渡插值。
 * 纯逻辑模块：颜色用 0..1 浮点三元组（Rgb）表示，不依赖 three，可独立单测。
 */
import type { DarkroomTheme } from "../theme/themes";

/** 0..1 浮点 RGB 三元组。 */
export type Rgb = [number, number, number];

/** 3D 场景消费的一套完整参数（每帧经过渡插值后应用）。 */
export interface SceneParams {
  /** 雾 / 底色，取自主题 abyss。 */
  readonly fogColor: Rgb;
  /** 粒子色板槽位，固定 6 格（主题色不足时循环复用）。 */
  readonly palette: readonly Rgb[];
  /** bloom 强度（克制区间 [BLOOM_MIN, BLOOM_MAX]，随主题强调色亮度微调）。 */
  readonly bloomStrength: number;
  /** bloom 阈值（≥0.7，避免全屏泛光）。 */
  readonly bloomThreshold: number;
  /** 暗角强度。 */
  readonly vignetteStrength: number;
  /** 胶片颗粒不透明度。 */
  readonly grainOpacity: number;
}

/** 色板槽位数：每主题 ≤6 内容色（M5 新约束）。 */
export const PALETTE_SLOTS = 6;
export const BLOOM_MIN = 0.3;
export const BLOOM_MAX = 0.5;
/** 主题切换过渡时长：与 CSS 变量换肤的 260ms 保持一致。 */
export const THEME_TRANSITION_MS = 260;

const HEX_FULL = /^#([0-9a-fA-F]{6})$/;
const HEX_SHORT = /^#([0-9a-fA-F]{3})$/;
const RGB_FN = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*[\d.]+%?\s*)?\)$/;

/** 解析 #rrggbb / #rgb / rgb() / rgba()（alpha 丢弃）。非法输入抛 RangeError。 */
export function hexToRgb(color: string): Rgb {
  const full = HEX_FULL.exec(color);
  if (full) {
    const value = Number.parseInt(full[1]!, 16);
    return [((value >> 16) & 0xff) / 255, ((value >> 8) & 0xff) / 255, (value & 0xff) / 255];
  }
  const short = HEX_SHORT.exec(color);
  if (short) {
    const s = short[1]!;
    return [
      Number.parseInt(s[0]! + s[0]!, 16) / 255,
      Number.parseInt(s[1]! + s[1]!, 16) / 255,
      Number.parseInt(s[2]! + s[2]!, 16) / 255,
    ];
  }
  const fn = RGB_FN.exec(color);
  if (fn) {
    return [Number(fn[1]) / 255, Number(fn[2]) / 255, Number(fn[3]) / 255];
  }
  throw new RangeError(`无法解析颜色: ${color}`);
}

/** 相对亮度（Rec.601 系数的简化版），用于 bloom 随主题微调。 */
function luminance([r, g, b]: Rgb): number {
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** 主题 → 场景参数。色板循环写满 6 格；bloom 强度随强调色亮度落在克制区间。 */
export function themeToSceneParams(theme: DarkroomTheme): SceneParams {
  // 每主题 ≤6 内容色硬校验（M5 新约束）：超过即拒绝，不放行到 GPU 色板
  if (theme.particles.length > PALETTE_SLOTS) {
    throw new RangeError(
      `主题 ${theme.id} 粒子色板 ${theme.particles.length} 色超过 ${PALETTE_SLOTS} 槽硬上限`,
    );
  }
  const palette: Rgb[] = [];
  for (let i = 0; i < PALETTE_SLOTS; i++) {
    palette.push(hexToRgb(theme.particles[i % theme.particles.length]!));
  }
  const accent = hexToRgb(theme.tokens.accent);
  return {
    fogColor: hexToRgb(theme.tokens.abyss),
    palette,
    bloomStrength: BLOOM_MIN + (BLOOM_MAX - BLOOM_MIN) * luminance(accent),
    bloomThreshold: 0.75,
    vignetteStrength: 0.45,
    grainOpacity: 0.05,
  };
}

const clamp01 = (t: number): number => Math.min(1, Math.max(0, t));
const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;
const lerpRgb = (a: Rgb, b: Rgb, t: number): Rgb => [
  lerp(a[0], b[0], t),
  lerp(a[1], b[1], t),
  lerp(a[2], b[2], t),
];

/** 场景参数线性插值；t 被钳制到 [0, 1]。 */
export function lerpSceneParams(from: SceneParams, to: SceneParams, t: number): SceneParams {
  const k = clamp01(t);
  return {
    fogColor: lerpRgb(from.fogColor, to.fogColor, k),
    palette: from.palette.map((color, i) => lerpRgb(color, to.palette[i] ?? color, k)),
    bloomStrength: lerp(from.bloomStrength, to.bloomStrength, k),
    bloomThreshold: lerp(from.bloomThreshold, to.bloomThreshold, k),
    vignetteStrength: lerp(from.vignetteStrength, to.vignetteStrength, k),
    grainOpacity: lerp(from.grainOpacity, to.grainOpacity, k),
  };
}

export interface ThemeTransitionSample {
  readonly params: SceneParams;
  readonly done: boolean;
}

export interface ThemeTransition {
  /** 开始朝向 target 过渡；从当前插值点出发（中途重定向无跳变）。 */
  start(target: SceneParams, now: number): void;
  /** 采样 now 时刻的参数；结束后再采样保持在目标参数。 */
  sample(now: number): ThemeTransitionSample;
  /** 立即跳到目标参数（reduced-motion 静态帧用）。 */
  finish(): SceneParams;
  current(): SceneParams;
}

/** 主题过渡状态机；durationMs 必须为正，否则抛 RangeError。 */
export function createThemeTransition(
  initial: SceneParams,
  durationMs: number = THEME_TRANSITION_MS,
): ThemeTransition {
  if (!Number.isFinite(durationMs) || durationMs <= 0) {
    throw new RangeError(`过渡时长必须为正数: ${durationMs}`);
  }
  let currentParams = initial;
  let fromParams = initial;
  let toParams = initial;
  let startAt = 0;
  let active = false;

  return {
    start(target: SceneParams, now: number): void {
      fromParams = currentParams; // 从当前插值点出发，而非跳回上一次起点
      toParams = target;
      startAt = now;
      active = true;
    },

    sample(now: number): ThemeTransitionSample {
      if (!active) return { params: currentParams, done: true };
      const t = (now - startAt) / durationMs;
      if (t >= 1) {
        currentParams = toParams;
        active = false;
        return { params: currentParams, done: true };
      }
      currentParams = lerpSceneParams(fromParams, toParams, t);
      return { params: currentParams, done: false };
    },

    finish(): SceneParams {
      currentParams = toParams;
      active = false;
      return currentParams;
    },

    current(): SceneParams {
      return currentParams;
    },
  };
}
