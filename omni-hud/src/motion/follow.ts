/**
 * 鼠标柔和跟随（M4.4）：低幅度 lerp 缓动，呼吸感；
 * 禁止生硬直线追踪——由 FOLLOW_LERP 低系数保证每帧只逼近一小段。
 */

/** 跟随系数：每帧逼近剩余距离的 6%，低幅度才有呼吸感。 */
export const FOLLOW_LERP = 0.06;

/** 单轴 lerp：current 向 target 逼近 factor 比例。factor ∈ (0, 1]，非法抛 RangeError。 */
export function lerpValue(current: number, target: number, factor: number): number {
  if (!Number.isFinite(factor) || factor <= 0 || factor > 1) {
    throw new RangeError(`lerp 系数非法: ${factor}`);
  }
  return current + (target - current) * factor;
}

export interface Point {
  readonly x: number;
  readonly y: number;
}

/** 双轴 lerp。 */
export function lerpPoint(current: Point, target: Point, factor: number): Point {
  return {
    x: lerpValue(current.x, target.x, factor),
    y: lerpValue(current.y, target.y, factor),
  };
}
