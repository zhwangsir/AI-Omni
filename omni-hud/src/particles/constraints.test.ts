import { describe, expect, it } from "vitest";

import {
  MAX_PARTICLES,
  MAX_SPEED,
  PALETTE,
  clampParticleCount,
  validateParticleSpec,
} from "../particles/constraints";

describe("粒子硬约束常量（CLAUDE.md 第六节）", () => {
  it("同屏粒子上限为 300", () => {
    expect(MAX_PARTICLES).toBe(300);
  });

  it("速度上限为 1.2", () => {
    expect(MAX_SPEED).toBe(1.2);
  });

  it("调色板不超过 5 色且无重复色", () => {
    expect(PALETTE.length).toBeLessThanOrEqual(5);
    expect(PALETTE.length).toBeGreaterThan(0);
    expect(new Set(PALETTE).size).toBe(PALETTE.length);
  });
});

describe("clampParticleCount", () => {
  it("超过上限时钳制到 300", () => {
    expect(clampParticleCount(999)).toBe(300);
  });

  it("正常值向下取整", () => {
    expect(clampParticleCount(50.7)).toBe(50);
  });

  it("负数与非法值归零", () => {
    expect(clampParticleCount(-3)).toBe(0);
    expect(clampParticleCount(Number.NaN)).toBe(0);
  });
});

describe("validateParticleSpec 硬校验", () => {
  const valid = { vx: 0.6, vy: 0.6, radius: 1.2, color: PALETTE[0] };

  it("合法粒子不抛错", () => {
    expect(() => validateParticleSpec(valid)).not.toThrow();
  });

  it("速率超过 1.2 抛 RangeError", () => {
    expect(() => validateParticleSpec({ ...valid, vx: 1.5, vy: 0 })).toThrow(RangeError);
  });

  it("调色板外颜色抛 RangeError", () => {
    expect(() => validateParticleSpec({ ...valid, color: "#ffffff" })).toThrow(RangeError);
  });

  it("非正半径抛 RangeError", () => {
    expect(() => validateParticleSpec({ ...valid, radius: 0 })).toThrow(RangeError);
  });
});
