/**
 * 粒子系统硬约束（CLAUDE.md 第六节）：同屏 ≤ 300 个、速度 ≤ 1.2、颜色 ≤ 5 种。
 * 约束全部做成导出常量并附带硬校验函数，任何注入的粒子都必须过校验。
 */

/** 同屏粒子上限。 */
export const MAX_PARTICLES = 300;
/** 粒子速率上限（px / 帧，1 帧 ≈ 16.7ms）。 */
export const MAX_SPEED = 1.2;
/** 粒子速率下限，避免静止粒子看起来像坏点。 */
export const MIN_SPEED = 0.15;
/** 调色板颜色数上限。 */
export const MAX_COLORS = 5;

/**
 * Film Atelier 暗房调色板（≤ 5 色，与 src/styles/tokens.css 中的
 * --omni-particle-* 保持同步）：安全灯琥珀、灰蓝、雾白、暗钢、暗房红。
 */
export const PALETTE = ["#c9a86a", "#8b93a7", "#d8d9dc", "#5d6678", "#b04a3a"] as const;

// 模块加载即硬校验：调色板违反 ≤ 5 色约束时直接拒绝启动。
if (PALETTE.length > MAX_COLORS) {
  throw new Error(`粒子调色板 ${PALETTE.length} 色，违反 ≤ ${MAX_COLORS} 色硬约束`);
}

export interface ParticleSpecLike {
  readonly vx: number;
  readonly vy: number;
  readonly radius: number;
  readonly color: string;
}

/** 粒子数量规范化：取整并钳制到 [0, MAX_PARTICLES]。 */
export function clampParticleCount(count: number): number {
  if (!Number.isFinite(count)) return 0;
  return Math.min(Math.max(Math.floor(count), 0), MAX_PARTICLES);
}

/** 粒子速率（速度向量的模）。 */
export function particleSpeed(spec: { readonly vx: number; readonly vy: number }): number {
  return Math.hypot(spec.vx, spec.vy);
}

/**
 * 校验调色板本身：1..MAX_COLORS 色。M4.4 主题换肤注入自定义调色板时过硬校验。
 */
export function validatePalette(palette: readonly string[]): void {
  if (palette.length === 0 || palette.length > MAX_COLORS) {
    throw new RangeError(`调色板 ${palette.length} 色，违反 1..${MAX_COLORS} 色硬约束`);
  }
}

/**
 * 校验单个粒子是否满足全部硬约束，违反时抛 RangeError。
 * 生成与外部注入两条路径都必须经过这里。
 * palette 缺省用全局 PALETTE；主题换肤时传入主题调色板。
 */
export function validateParticleSpec(
  spec: ParticleSpecLike,
  palette: readonly string[] = PALETTE,
): void {
  if (!Number.isFinite(spec.radius) || spec.radius <= 0) {
    throw new RangeError(`粒子半径非法: ${spec.radius}`);
  }
  const speed = particleSpeed(spec);
  if (speed > MAX_SPEED + 1e-9) {
    throw new RangeError(`粒子速率 ${speed} 超过上限 ${MAX_SPEED}`);
  }
  if (!palette.includes(spec.color)) {
    throw new RangeError(`粒子颜色 ${spec.color} 不在调色板内（≤ ${MAX_COLORS} 色约束）`);
  }
}
