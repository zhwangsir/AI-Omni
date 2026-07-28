/**
 * shelf/layout 弧形卡片排列几何（M20.1 TDD 红）：
 * 纯逻辑模块——给定卡片数 / 弧半径 / 张角跨度，计算每张卡片的世界坐标、
 * 朝向（Y 轴旋转角，使卡片正面始终朝向圆心）、垂直抬升、入场偏移。
 *
 * 设计决策 D20.1：弧形排列以 XZ 平面圆周分布 + Y 轴旋转使正面朝向圆心；
 * 卡片不在严格圆周上，而是落在「圆心向外的射线」上，半径恒定，避免重叠。
 * 张角跨度有界（≤120°，CLAUDE.md §六 视觉约束：克制不爆炸）；
 * 卡片数为 0 时返回空数组；非法输入抛 RangeError。
 */
import { describe, expect, it } from "vitest";

import {
  ARC_MAX_SPAN_DEG,
  ARC_RADIUS_MAX,
  ARC_RADIUS_MIN,
  computeArcLayout,
} from "./layout";

describe("computeArcLayout 输入校验", () => {
  it("卡片数为 0 返回空数组（不抛错）", () => {
    expect(computeArcLayout(0)).toEqual([]);
  });

  it("卡片数为负抛 RangeError", () => {
    expect(() => computeArcLayout(-1)).toThrow(RangeError);
  });

  it("卡片数非整数抛 RangeError", () => {
    expect(() => computeArcLayout(2.5)).toThrow(RangeError);
  });

  it("弧半径低于下限抛 RangeError", () => {
    expect(() => computeArcLayout(3, { radius: ARC_RADIUS_MIN - 0.01 })).toThrow(RangeError);
  });

  it("弧半径高于上限抛 RangeError", () => {
    expect(() => computeArcLayout(3, { radius: ARC_RADIUS_MAX + 0.01 })).toThrow(RangeError);
  });

  it("张角跨度超过上限抛 RangeError", () => {
    expect(() => computeArcLayout(3, { spanDeg: ARC_MAX_SPAN_DEG + 1 })).toThrow(RangeError);
  });

  it("张角跨度非正抛 RangeError", () => {
    expect(() => computeArcLayout(3, { spanDeg: 0 })).toThrow(RangeError);
  });
});

describe("computeArcLayout 单卡布局", () => {
  it("单张卡片位于圆心正前方（z=radius, x=0, rotationY=0）", () => {
    const layout = computeArcLayout(1, { radius: 4 });
    expect(layout).toHaveLength(1);
    const card = layout[0]!;
    expect(card.index).toBe(0);
    expect(card.position.x).toBeCloseTo(0, 5);
    expect(card.position.y).toBeCloseTo(0, 5);
    expect(card.position.z).toBeCloseTo(4, 5);
    expect(card.rotationY).toBeCloseTo(0, 5);
  });
});

describe("computeArcLayout 多卡弧形", () => {
  it("三张卡片：中卡正前 / 左右对称（X 镜像 + Y 旋转镜像）", () => {
    const layout = computeArcLayout(3, { radius: 4, spanDeg: 90 });
    expect(layout).toHaveLength(3);
    const [left, mid, right] = layout;
    // 中卡正前
    expect(mid!.position.x).toBeCloseTo(0, 5);
    expect(mid!.position.z).toBeCloseTo(4, 5);
    expect(mid!.rotationY).toBeCloseTo(0, 5);
    // 左右对称
    expect(left!.position.x).toBeCloseTo(-right!.position.x, 5);
    expect(left!.position.y).toBeCloseTo(right!.position.y, 5);
    expect(left!.position.z).toBeCloseTo(right!.position.z, 5);
    expect(left!.rotationY).toBeCloseTo(-right!.rotationY, 5);
    // 旋转角使卡片正面朝向圆心（左侧 rotationY>0，右侧 <0）
    expect(left!.rotationY).toBeGreaterThan(0);
    expect(right!.rotationY).toBeLessThan(0);
  });

  it("所有卡片到圆心距离相等（=radius）", () => {
    const layout = computeArcLayout(7, { radius: 3.5, spanDeg: 100 });
    for (const card of layout) {
      const dist = Math.hypot(card.position.x, card.position.z);
      expect(dist).toBeCloseTo(3.5, 4);
    }
  });

  it("卡片按 index 顺序排列（角度从 -span/2 到 +span/2）", () => {
    const layout = computeArcLayout(5, { radius: 4, spanDeg: 80 });
    // 第一张角度最小（最负），最后一张最大
    expect(layout[0]!.angleDeg).toBeLessThan(layout[4]!.angleDeg);
    expect(layout[2]!.angleDeg).toBeCloseTo(0, 5); // 中间张角度为 0
  });

  it("垂直抬升可选（默认 0）；给定 lift 时 y 随 index 线性变化", () => {
    const flat = computeArcLayout(3, { radius: 4 });
    expect(flat[0]!.position.y).toBe(0);
    expect(flat[2]!.position.y).toBe(0);

    const lifted = computeArcLayout(3, { radius: 4, liftY: 0.2 });
    // 中间张 y=0，两端张 y 对称（左正右负 或 反向，按 index 线性）
    expect(lifted[1]!.position.y).toBeCloseTo(0, 5);
    expect(Math.abs(lifted[0]!.position.y)).toBeCloseTo(0.2, 5);
    expect(lifted[0]!.position.y).toBeCloseTo(-lifted[2]!.position.y, 5);
  });

  it("卡片数超过张角可容纳时不抛错（仅密集排列，角度跨度仍为 spanDeg）", () => {
    const layout = computeArcLayout(20, { radius: 4, spanDeg: 60 });
    expect(layout).toHaveLength(20);
    expect(layout[0]!.angleDeg).toBeCloseTo(-30, 5);
    expect(layout[19]!.angleDeg).toBeCloseTo(30, 5);
  });

  it("reducedMotion=true 时入场偏移归零（不偏移）", () => {
    const normal = computeArcLayout(3, { radius: 4 });
    const reduced = computeArcLayout(3, { radius: 4, reducedMotion: true });
    // 默认实现：入场偏移只在 z 方向（卡片从远处推进）
    expect(normal[0]!.enterOffset.z).not.toBe(0);
    expect(reduced[0]!.enterOffset.x).toBe(0);
    expect(reduced[0]!.enterOffset.y).toBe(0);
    expect(reduced[0]!.enterOffset.z).toBe(0);
  });
});
