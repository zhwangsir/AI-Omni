/**
 * 鼠标跟随 lerp 逻辑测试（M4.4）。
 * 柔和跟随 = 低幅度 lerp 缓动（呼吸感），禁止生硬直线追踪（factor=1 一帧到位）。
 */
import { describe, expect, it } from "vitest";

import { FOLLOW_LERP, lerpPoint, lerpValue } from "./follow";

describe("lerp 缓动跟随", () => {
  it("FOLLOW_LERP 是低幅度系数（< 0.2，保证柔和而非追踪）", () => {
    expect(FOLLOW_LERP).toBeGreaterThan(0);
    expect(FOLLOW_LERP).toBeLessThan(0.2);
  });

  it("lerpValue 向目标收敛且不越过目标", () => {
    let current = 0;
    const target = 100;
    const seen: number[] = [];
    for (let i = 0; i < 200; i++) {
      current = lerpValue(current, target, FOLLOW_LERP);
      seen.push(current);
    }
    expect(current).toBeGreaterThan(99);
    // 单调递增且从未超过目标（无 overshoot）
    for (let i = 1; i < seen.length; i++) {
      expect(seen[i]!).toBeGreaterThanOrEqual(seen[i - 1]!);
      expect(seen[i]!).toBeLessThanOrEqual(target);
    }
  });

  it("lerpValue 第一步只走一小段（非生硬到位）", () => {
    const next = lerpValue(0, 100, FOLLOW_LERP);
    expect(next).toBeGreaterThan(0);
    expect(next).toBeLessThan(20);
  });

  it("factor=1 时一帧到位；非法 factor 抛 RangeError", () => {
    expect(lerpValue(0, 100, 1)).toBe(100);
    expect(() => lerpValue(0, 100, 0)).toThrow(RangeError);
    expect(() => lerpValue(0, 100, 1.5)).toThrow(RangeError);
    expect(() => lerpValue(0, 100, Number.NaN)).toThrow(RangeError);
  });

  it("lerpPoint 双轴同时缓动", () => {
    const next = lerpPoint({ x: 0, y: 0 }, { x: 100, y: 50 }, 0.1);
    expect(next.x).toBeCloseTo(10);
    expect(next.y).toBeCloseTo(5);
  });

  it("已在目标点时保持不动", () => {
    const next = lerpPoint({ x: 7, y: 9 }, { x: 7, y: 9 }, FOLLOW_LERP);
    expect(next.x).toBe(7);
    expect(next.y).toBe(9);
  });
});
