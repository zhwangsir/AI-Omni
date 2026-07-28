/**
 * attractor 测试（M5.2 TDD 红）：指针吸引子——NDC unproject 到粒子层
 * 深度平面、位置平滑 lerp、强度钳制 [0, MAX]、近距强阻尼（防吸穿/爆粒）、
 * 无指针时强度归零（纯流场）、脉冲衰减。
 * 纯逻辑：不依赖 three / WebGL。
 */
import { describe, expect, it } from "vitest";

import {
  ATTRACTOR_BASE_STRENGTH,
  ATTRACTOR_MAX_STRENGTH,
  ATTRACTOR_NEAR_RADIUS,
  clampAttractorStrength,
  createAttractor,
  nearDamping,
  pointerToPlane,
} from "./attractor";

describe("pointerToPlane 反投影", () => {
  const view = { fovDeg: 42, aspect: 380 / 560, cameraZ: 8, planeZ: 0, originX: 0, originY: 0 };

  it("NDC(0,0) 落在相机原点正对的平面点上", () => {
    const p = pointerToPlane(0, 0, view);
    expect(p.x).toBeCloseTo(0, 6);
    expect(p.y).toBeCloseTo(0, 6);
    expect(p.z).toBe(0);
  });

  it("NDC(1,0) 落在平面右边缘：x = tan(fov/2)·距离·aspect", () => {
    const p = pointerToPlane(1, 0, view);
    const expected = Math.tan((42 / 2) * (Math.PI / 180)) * 8 * (380 / 560);
    expect(p.x).toBeCloseTo(expected, 6);
    expect(p.y).toBeCloseTo(0, 6);
  });

  it("NDC(0,-1) 落在平面下边缘（y 向下为负）", () => {
    const p = pointerToPlane(0, -1, view);
    expect(p.y).toBeCloseTo(-Math.tan((42 / 2) * (Math.PI / 180)) * 8, 6);
  });

  it("相机 rig 原点偏移会平移到世界坐标", () => {
    const p = pointerToPlane(0, 0, { ...view, originX: 0.5, originY: -0.3 });
    expect(p.x).toBeCloseTo(0.5, 6);
    expect(p.y).toBeCloseTo(-0.3, 6);
  });

  it("非法视口参数抛 RangeError", () => {
    expect(() => pointerToPlane(0, 0, { ...view, fovDeg: 0 })).toThrow(RangeError);
    expect(() => pointerToPlane(0, 0, { ...view, fovDeg: 180 })).toThrow(RangeError);
    expect(() => pointerToPlane(0, 0, { ...view, aspect: 0 })).toThrow(RangeError);
    expect(() => pointerToPlane(0, 0, { ...view, cameraZ: 0, planeZ: 0 })).toThrow(RangeError);
  });
});

describe("nearDamping 近距阻尼", () => {
  it("零距离阻尼为 0（粒子不被吸穿），达到近距半径后阻尼为 1", () => {
    expect(nearDamping(0)).toBe(0);
    expect(nearDamping(ATTRACTOR_NEAR_RADIUS)).toBeCloseTo(1, 5);
    expect(nearDamping(ATTRACTOR_NEAR_RADIUS * 3)).toBeCloseTo(1, 5);
  });

  it("阻尼在 (0, NEAR) 区间单调递增（smoothstep 平滑过渡）", () => {
    let prev = -1;
    for (let i = 0; i <= 20; i++) {
      const d = (ATTRACTOR_NEAR_RADIUS * i) / 20;
      const value = nearDamping(d);
      expect(value).toBeGreaterThanOrEqual(prev);
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThanOrEqual(1);
      prev = value;
    }
    // 中点 smoothstep ≈ 0.5（非线性硬切换）
    expect(nearDamping(ATTRACTOR_NEAR_RADIUS / 2)).toBeCloseTo(0.5, 5);
  });

  it("负距离按 0 处理（钳制）", () => {
    expect(nearDamping(-0.5)).toBe(0);
  });
});

describe("clampAttractorStrength 强度钳制", () => {
  it("钳制到 [0, MAX]", () => {
    expect(clampAttractorStrength(0.4)).toBe(0.4);
    expect(clampAttractorStrength(-1)).toBe(0);
    expect(clampAttractorStrength(ATTRACTOR_MAX_STRENGTH * 3)).toBe(ATTRACTOR_MAX_STRENGTH);
    expect(clampAttractorStrength(Number.POSITIVE_INFINITY)).toBe(ATTRACTOR_MAX_STRENGTH);
  });
});

describe("createAttractor 状态机", () => {
  it("无指针（未激活）时强度归零——纯流场", () => {
    const a = createAttractor();
    const s = a.step(1 / 60);
    expect(s.strength).toBe(0);
  });

  it("激活后强度为基础强度；setTarget 后位置逐帧 lerp 逼近目标", () => {
    const a = createAttractor();
    a.setActive(true);
    a.setTarget(2, 1, 0);
    let s = a.step(1 / 60);
    expect(s.strength).toBeCloseTo(ATTRACTOR_BASE_STRENGTH, 5);
    expect(Math.abs(s.x - 2)).toBeGreaterThan(0.1); // 第一帧没瞬移到位
    for (let i = 0; i < 300; i++) s = a.step(1 / 60);
    expect(s.x).toBeCloseTo(2, 2);
    expect(s.y).toBeCloseTo(1, 2);
    expect(s.z).toBeCloseTo(0, 2);
  });

  it("pulse 后强度瞬时升高并随时间衰减回基础强度", () => {
    const a = createAttractor();
    a.setActive(true);
    a.setTarget(0, 0, 0);
    a.step(1 / 60);
    a.pulse();
    const boosted = a.step(1 / 60);
    expect(boosted.strength).toBeGreaterThan(ATTRACTOR_BASE_STRENGTH + 0.2);
    let s = boosted;
    for (let i = 0; i < 600; i++) s = a.step(1 / 60); // 10s 后脉冲基本消散
    expect(s.strength).toBeCloseTo(ATTRACTOR_BASE_STRENGTH, 2);
  });

  it("pulse 强度被钳制：不会超过 MAX（防爆粒）", () => {
    const a = createAttractor();
    a.setActive(true);
    a.setTarget(0, 0, 0);
    a.pulse(ATTRACTOR_MAX_STRENGTH * 10);
    const s = a.step(1 / 60);
    expect(s.strength).toBeLessThanOrEqual(ATTRACTOR_MAX_STRENGTH);
  });

  it("pulse 参数非法（负 / NaN / Infinity）按 0 或钳制处理，不抛错不爆", () => {
    const a = createAttractor();
    a.setActive(true);
    a.pulse(Number.NaN);
    expect(a.step(1 / 60).strength).toBeLessThanOrEqual(ATTRACTOR_MAX_STRENGTH);
    a.pulse(-5);
    expect(a.step(1 / 60).strength).toBeLessThanOrEqual(ATTRACTOR_MAX_STRENGTH);
  });

  it("setTarget 非法坐标抛 RangeError", () => {
    const a = createAttractor();
    expect(() => a.setTarget(Number.NaN, 0, 0)).toThrow(RangeError);
    expect(() => a.setTarget(0, Number.POSITIVE_INFINITY, 0)).toThrow(RangeError);
  });

  it("取消激活后强度衰减回 0（指针离开 → 纯流场）", () => {
    const a = createAttractor();
    a.setActive(true);
    a.setTarget(1, 0, 0);
    a.step(1 / 60);
    a.setActive(false);
    let s = a.step(1 / 60);
    for (let i = 0; i < 300; i++) s = a.step(1 / 60);
    expect(s.strength).toBeCloseTo(0, 3);
  });
});
