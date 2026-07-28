/**
 * shapes 测试（M5.2 TDD 红）：形状目标点云生成器（球壳 / 水平环 / 双螺旋）
 * 与 morphFactor 过渡状态机（≥600ms 缓动，禁瞬跳）。
 * 纯逻辑：不依赖 three / WebGL。
 */
import { describe, expect, it } from "vitest";

import {
  MORPH_DEFAULT_MS,
  MORPH_MIN_MS,
  SHAPE_KINDS,
  SHAPE_RADIUS,
  createMorphTransition,
  generateShapePoints,
  isShapeKind,
} from "./shapes";

const norm = (data: Float32Array, i: number): number =>
  Math.hypot(data[i * 3]!, data[i * 3 + 1]!, data[i * 3 + 2]!);

describe("generateShapePoints 契约", () => {
  it("四种形状各生成 count 个三维点（count*3 长度）", () => {
    for (const kind of SHAPE_KINDS) {
      const points = generateShapePoints(kind, 500);
      expect(points).toBeInstanceOf(Float32Array);
      expect(points.length).toBe(500 * 3);
      for (const value of points) expect(Number.isFinite(value)).toBe(true);
    }
  });

  it("至少提供 4 种形状（sphere/ring/helix/dna_helix）", () => {
    expect(SHAPE_KINDS.length).toBeGreaterThanOrEqual(4);
    expect(SHAPE_KINDS).toContain("sphere");
    expect(SHAPE_KINDS).toContain("ring");
    expect(SHAPE_KINDS).toContain("helix");
    expect(SHAPE_KINDS).toContain("dna_helix");
  });

  it("未知形状抛 RangeError；isShapeKind 类型守卫一致", () => {
    expect(() => generateShapePoints("cube" as never, 100)).toThrow(RangeError);
    expect(isShapeKind("sphere")).toBe(true);
    expect(isShapeKind("cube")).toBe(false);
  });

  it("非法 count（0 / 负数 / 非整数 / NaN）抛 RangeError", () => {
    expect(() => generateShapePoints("sphere", 0)).toThrow(RangeError);
    expect(() => generateShapePoints("sphere", -5)).toThrow(RangeError);
    expect(() => generateShapePoints("sphere", 2.5)).toThrow(RangeError);
    expect(() => generateShapePoints("sphere", Number.NaN)).toThrow(RangeError);
  });

  it("同参数生成结果确定（可复现，避免重建时形状抖动）", () => {
    const a = generateShapePoints("helix", 128);
    const b = generateShapePoints("helix", 128);
    expect(Array.from(a)).toEqual(Array.from(b));
  });
});

describe("generateShapePoints 几何分布", () => {
  it("sphere：全部点落在半径 ≈ SHAPE_RADIUS 的球壳上", () => {
    const points = generateShapePoints("sphere", 800);
    for (let i = 0; i < 800; i++) {
      expect(norm(points, i)).toBeCloseTo(SHAPE_RADIUS, 5);
    }
  });

  it("ring：点贴近水平面（|y| 小），水平半径 ≈ SHAPE_RADIUS", () => {
    const points = generateShapePoints("ring", 600);
    for (let i = 0; i < 600; i++) {
      const y = points[i * 3 + 1]!;
      const radial = Math.hypot(points[i * 3]!, points[i * 3 + 2]!);
      expect(Math.abs(y)).toBeLessThan(SHAPE_RADIUS * 0.2);
      expect(radial).toBeGreaterThan(SHAPE_RADIUS * 0.8);
      expect(radial).toBeLessThan(SHAPE_RADIUS * 1.2);
    }
  });

  it("helix：双螺旋——水平半径恒定，y 在 [-R, R] 内均匀铺开且两股相位错开", () => {
    const count = 400;
    const points = generateShapePoints("helix", count);
    let minY = Number.POSITIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;
    for (let i = 0; i < count; i++) {
      const y = points[i * 3 + 1]!;
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
      const radial = Math.hypot(points[i * 3]!, points[i * 3 + 2]!);
      expect(radial).toBeGreaterThan(SHAPE_RADIUS * 0.3);
      expect(radial).toBeLessThan(SHAPE_RADIUS * 0.9);
    }
    // y 轴向铺满（螺旋沿竖直轴展开）
    expect(maxY - minY).toBeGreaterThan(SHAPE_RADIUS * 1.5);
    expect(Math.abs(maxY)).toBeLessThanOrEqual(SHAPE_RADIUS + 1e-6);
    expect(Math.abs(minY)).toBeLessThanOrEqual(SHAPE_RADIUS + 1e-6);
    // 相邻两点（两股交替）水平夹角应显著错开，不是单股弹簧
    const angle0 = Math.atan2(points[2]!, points[0]!);
    const angle1 = Math.atan2(points[5]!, points[3]!);
    const gap = Math.abs(angle0 - angle1);
    expect(Math.min(gap, Math.PI * 2 - gap)).toBeGreaterThan(Math.PI / 2);
  });

  it("dna_helix：水平双螺旋——x 轴向铺满，zy 平面半径恒定（横截面为圆），两股相位错开 π", () => {
    const count = 400;
    const points = generateShapePoints("dna_helix", count);
    let minX = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    const expectedR = SHAPE_RADIUS * 0.55;
    for (let i = 0; i < count; i++) {
      const x = points[i * 3]!;
      const y = points[i * 3 + 1]!;
      const z = points[i * 3 + 2]!;
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      // zy 平面半径恒定（横截面为圆，半径 = R*0.55）
      const radial = Math.hypot(y, z);
      expect(radial).toBeGreaterThan(expectedR * 0.9);
      expect(radial).toBeLessThan(expectedR * 1.1);
    }
    // x 轴向铺满（螺旋沿水平轴展开）
    expect(maxX - minX).toBeGreaterThan(SHAPE_RADIUS * 1.5);
    expect(Math.abs(maxX)).toBeLessThanOrEqual(SHAPE_RADIUS * 0.9 + 1e-6);
    expect(Math.abs(minX)).toBeLessThanOrEqual(SHAPE_RADIUS * 0.9 + 1e-6);
    // 相邻两点（两股交替）zy 平面夹角应显著错开 π（双螺旋特征）
    const yzAngle0 = Math.atan2(points[1]!, points[2]!);
    const yzAngle1 = Math.atan2(points[4]!, points[5]!);
    const gap = Math.abs(yzAngle0 - yzAngle1);
    expect(Math.min(gap, Math.PI * 2 - gap)).toBeGreaterThan(Math.PI / 2);
  });
});

describe("createMorphTransition 过渡", () => {
  it("默认时长 ≥ 600ms 下限（禁瞬跳）", () => {
    expect(MORPH_DEFAULT_MS).toBeGreaterThanOrEqual(MORPH_MIN_MS);
    expect(MORPH_MIN_MS).toBeGreaterThanOrEqual(600);
  });

  it("时长低于 600ms 下限抛 RangeError", () => {
    expect(() => createMorphTransition(300)).toThrow(RangeError);
    expect(() => createMorphTransition(0)).toThrow(RangeError);
  });

  it("morphTo：factor 从 0 缓动到 1，中间值严格单调且非瞬跳", () => {
    const morph = createMorphTransition();
    expect(morph.sample(0)).toBe(0);
    morph.morphTo(1000);
    expect(morph.sample(1000)).toBeCloseTo(0, 5);
    const mid = morph.sample(1000 + MORPH_DEFAULT_MS / 2);
    expect(mid).toBeGreaterThan(0.1);
    expect(mid).toBeLessThan(0.9);
    expect(morph.sample(1000 + MORPH_DEFAULT_MS)).toBeCloseTo(1, 5);
    // 结束后再采样保持 1
    expect(morph.sample(1000 + MORPH_DEFAULT_MS * 3)).toBeCloseTo(1, 5);
  });

  it("release：从成形状态缓动回 0（消散也是过渡而非瞬跳）", () => {
    const morph = createMorphTransition();
    morph.morphTo(0);
    morph.sample(MORPH_DEFAULT_MS); // 走完成形
    morph.release(5000);
    expect(morph.sample(5000)).toBeCloseTo(1, 5);
    const mid = morph.sample(5000 + MORPH_DEFAULT_MS / 2);
    expect(mid).toBeGreaterThan(0.1);
    expect(mid).toBeLessThan(0.9);
    expect(morph.sample(5000 + MORPH_DEFAULT_MS)).toBeCloseTo(0, 5);
  });

  it("中途重定向无跳变：半途中 morphTo 从当前 factor 继续", () => {
    const morph = createMorphTransition();
    morph.morphTo(0);
    const half = morph.sample(MORPH_DEFAULT_MS / 2);
    morph.morphTo(10_000); // 中途再次触发
    // 从当前插值点出发，不得跳回 0 或跳到 1
    expect(morph.sample(10_000)).toBeCloseTo(half, 5);
  });

  it("resetAndMorphTo：强制从 factor=0 重新成形（形态间切换不瞬跳）", () => {
    const morph = createMorphTransition();
    morph.morphTo(0);
    morph.sample(MORPH_DEFAULT_MS); // 完全成形（factor=1）
    // 调用 resetAndMorphTo：必须立即从 0 开始，而非从 1 继续（那会导致瞬跳）
    morph.resetAndMorphTo(5000);
    expect(morph.sample(5000)).toBeCloseTo(0, 5); // 起始为 0
    const mid = morph.sample(5000 + MORPH_DEFAULT_MS / 2);
    expect(mid).toBeGreaterThan(0.1);
    expect(mid).toBeLessThan(0.9);
    expect(morph.sample(5000 + MORPH_DEFAULT_MS)).toBeCloseTo(1, 5);
  });
});
