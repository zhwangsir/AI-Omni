/**
 * shapes 形状目标点云生成器（M5.2）：球壳 / 水平环 / 双螺旋三种聚集形状，
 * 每种生成 count 个三维目标点（Float32Array，作为 aTarget attribute 上传）；
 * 以及 morphFactor 过渡状态机——成形 / 消散 ≥600ms smoothstep 缓动，禁瞬跳。
 * 纯逻辑模块：不依赖 three / WebGL，可独立单测。本里程碑只落地机制与 API，
 * 触发时机由 M5.3 接线。
 */

/** 支持的形状种类。 */
export const SHAPE_KINDS = ["sphere", "ring", "helix", "dna_helix"] as const;
export type ShapeKind = (typeof SHAPE_KINDS)[number];

/** 形状整体半径（世界单位），与粒子体积分布同量级。 */
export const SHAPE_RADIUS = 2.2;

/** morph 过渡时长下限：成形 / 消散都必须 ≥600ms 缓动（审美红线：禁瞬跳）。 */
export const MORPH_MIN_MS = 600;
/** 默认过渡时长：略长于下限，spring 感的从容节奏。 */
export const MORPH_DEFAULT_MS = 750;

/** 类型守卫：运行时校验形状名。 */
export function isShapeKind(value: unknown): value is ShapeKind {
  return typeof value === "string" && (SHAPE_KINDS as readonly string[]).includes(value);
}

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const TWO_PI = Math.PI * 2;

/**
 * 生成形状目标点云（确定性，无随机源——同参同结果，档切换重建时形状不抖动）。
 * @param kind 形状种类；未知形状抛 RangeError
 * @param count 目标点数（必须与粒子实例数一致）；非正整数抛 RangeError
 */
export function generateShapePoints(kind: ShapeKind, count: number): Float32Array {
  if (!isShapeKind(kind)) throw new RangeError(`未知形状: ${String(kind)}`);
  if (!Number.isInteger(count) || count <= 0) {
    throw new RangeError(`形状点数必须为正整数: ${count}`);
  }
  const out = new Float32Array(count * 3);
  const R = SHAPE_RADIUS;
  for (let i = 0; i < count; i++) {
    if (kind === "sphere") {
      // Fibonacci 球壳：均匀无级联，全部点精确落在半径 R 的球面上
      const y = 1 - (2 * (i + 0.5)) / count;
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const theta = i * GOLDEN_ANGLE;
      out[i * 3] = R * r * Math.cos(theta);
      out[i * 3 + 1] = R * y;
      out[i * 3 + 2] = R * r * Math.sin(theta);
    } else if (kind === "ring") {
      // 水平环：xz 平面等角分布 + 微管厚度（确定性抖动，避免完美数学环的呆板）
      const theta = (i / count) * TWO_PI;
      const tube = Math.sin(i * GOLDEN_ANGLE) * 0.06 * R;
      const lift = Math.cos(i * GOLDEN_ANGLE * 1.7) * 0.05 * R;
      out[i * 3] = (R + tube) * Math.cos(theta);
      out[i * 3 + 1] = lift;
      out[i * 3 + 2] = (R + tube) * Math.sin(theta);
    } else if (kind === "helix") {
      // 双螺旋：两股沿 y 轴缠绕，相邻点交替到另一股（相位差 π）
      const strand = i % 2;
      const t = Math.floor(i / 2) / Math.max(1, Math.floor(count / 2) - 1); // 0..1
      const y = (t - 0.5) * 2 * R * 0.9; // 竖直展开，|y| ≤ 0.9R
      const angle = t * 3 * TWO_PI + strand * Math.PI; // 3 圈，股间错开 π
      const r = R * 0.55;
      out[i * 3] = r * Math.cos(angle);
      out[i * 3 + 1] = y;
      out[i * 3 + 2] = r * Math.sin(angle);
    } else {
      // dna_helix：水平双螺旋——两股沿 x 轴缠绕，y/z 平面横截面为圆
      const strand = i % 2;
      const t = Math.floor(i / 2) / Math.max(1, Math.floor(count / 2) - 1); // 0..1
      const x = (t - 0.5) * 2 * R * 0.9; // 水平展开，|x| ≤ 0.9R
      const angle = t * 3 * TWO_PI + strand * Math.PI; // 3 圈，股间错开 π
      const r = R * 0.55;
      out[i * 3] = x;
      out[i * 3 + 1] = r * Math.sin(angle); // y 轴为上下分量
      out[i * 3 + 2] = r * Math.cos(angle); // z 轴为深度分量
    }
  }
  return out;
}

/** morphFactor 过渡状态机：0 = 自由流场，1 = 完全成形。 */
export interface MorphTransition {
  /** 开始向形状成形（目标 factor = 1）；从当前插值点出发，中途重定向无跳变。 */
  morphTo(now: number): void;
  /** 开始消散回自由流场（目标 factor = 0）。 */
  release(now: number): void;
  /** 强制重置为自由流（factor=0）并立即开始成形——用于形态间切换（A→B），避免瞬跳。 */
  resetAndMorphTo(now: number): void;
  /** 采样 now 时刻的 morphFactor（smoothstep 缓动，结束后保持目标值）。 */
  sample(now: number): number;
}

const smoothstep = (t: number): number => t * t * (3 - 2 * t);
const clamp01 = (t: number): number => Math.min(1, Math.max(0, t));

/**
 * 创建 morph 过渡状态机。
 * @param durationMs 过渡时长；低于 MORPH_MIN_MS（600ms）抛 RangeError（禁瞬跳）
 */
export function createMorphTransition(durationMs: number = MORPH_DEFAULT_MS): MorphTransition {
  if (!Number.isFinite(durationMs) || durationMs < MORPH_MIN_MS) {
    throw new RangeError(`morph 过渡时长必须 ≥${MORPH_MIN_MS}ms（禁瞬跳）: ${durationMs}`);
  }
  let factor = 0;
  let from = 0;
  let to = 0;
  let startAt = 0;
  let active = false;

  const begin = (target: number, now: number): void => {
    from = factor; // 从当前插值点出发，而非跳回端点
    to = target;
    startAt = now;
    active = true;
  };

  return {
    morphTo(now: number): void {
      begin(1, now);
    },
    release(now: number): void {
      begin(0, now);
    },
    resetAndMorphTo(now: number): void {
      factor = 0;
      from = 0;
      to = 1;
      startAt = now;
      active = true;
    },
    sample(now: number): number {
      if (!active) return factor;
      const t = (now - startAt) / durationMs;
      if (t >= 1) {
        factor = to;
        active = false;
        return factor;
      }
      factor = from + (to - from) * smoothstep(clamp01(t));
      return factor;
    },
  };
}
