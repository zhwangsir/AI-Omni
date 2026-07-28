import { describe, expect, it } from "vitest";

import { MAX_PARTICLES, MAX_SPEED, PALETTE } from "../particles/constraints";
import { ParticleEngine } from "../particles/engine";

const SIZE = { width: 400, height: 300 };

describe("ParticleEngine 生成", () => {
  it("按指定数量生成粒子", () => {
    const engine = new ParticleEngine({ ...SIZE, count: 50 });
    expect(engine.getParticles()).toHaveLength(50);
  });

  it("请求数量超过 300 时钳制到上限", () => {
    const engine = new ParticleEngine({ ...SIZE, count: 999 });
    expect(engine.getParticles()).toHaveLength(MAX_PARTICLES);
  });

  it("生成的粒子速率全部不超过 1.2", () => {
    const engine = new ParticleEngine({ ...SIZE, count: 200 });
    for (const p of engine.getParticles()) {
      expect(Math.hypot(p.vx, p.vy)).toBeLessThanOrEqual(MAX_SPEED + 1e-9);
    }
  });

  it("生成的粒子颜色全部来自调色板", () => {
    const engine = new ParticleEngine({ ...SIZE, count: 200 });
    const palette = new Set<string>(PALETTE);
    for (const p of engine.getParticles()) {
      expect(palette.has(p.color)).toBe(true);
    }
  });

  it("生成的粒子初始位置在画布内", () => {
    const engine = new ParticleEngine({ ...SIZE, count: 100 });
    for (const p of engine.getParticles()) {
      expect(p.x).toBeGreaterThanOrEqual(0);
      expect(p.x).toBeLessThanOrEqual(SIZE.width);
      expect(p.y).toBeGreaterThanOrEqual(0);
      expect(p.y).toBeLessThanOrEqual(SIZE.height);
    }
  });

  it("画布尺寸非法时抛 RangeError", () => {
    expect(() => new ParticleEngine({ width: 0, height: 300, count: 10 })).toThrow(RangeError);
  });
});

describe("ParticleEngine 推进", () => {
  const seeded = (x: number, y: number, vx: number, vy: number) =>
    new ParticleEngine({
      ...SIZE,
      count: 1,
      particles: [{ x, y, vx, vy, radius: 1, color: PALETTE[0] }],
    });

  it("step(dt) 按速度推进位置", () => {
    const engine = seeded(100, 100, 1, 0.5);
    engine.step(2);
    const [p] = engine.getParticles();
    expect(p.x).toBeCloseTo(102);
    expect(p.y).toBeCloseTo(101);
  });

  it("粒子越出右界后从左侧回绕", () => {
    const engine = seeded(399, 150, MAX_SPEED, 0);
    engine.step(2);
    const [p] = engine.getParticles();
    expect(p.x).toBeLessThan(0);
  });

  it("粒子越出下界后从顶部回绕", () => {
    const engine = seeded(200, 299, 0, MAX_SPEED);
    engine.step(2);
    const [p] = engine.getParticles();
    expect(p.y).toBeLessThan(0);
  });

  it("dt 为 0 或负数时粒子不动", () => {
    const engine = seeded(100, 100, 1, 0.5);
    engine.step(0);
    engine.step(-5);
    const [p] = engine.getParticles();
    expect(p.x).toBe(100);
    expect(p.y).toBe(100);
  });

  it("reducedMotion 开启时 step 不移动粒子（尊重 prefers-reduced-motion）", () => {
    const engine = new ParticleEngine({
      ...SIZE,
      count: 1,
      reducedMotion: true,
      particles: [{ x: 100, y: 100, vx: 1, vy: 0.5, radius: 1, color: PALETTE[0] }],
    });
    engine.step(3);
    const [p] = engine.getParticles();
    expect(p.x).toBe(100);
    expect(p.y).toBe(100);
  });

  it("getParticles 返回副本：外部修改不污染引擎内部状态", () => {
    const engine = seeded(100, 100, 1, 0.5);
    const snapshot = engine.getParticles();
    snapshot[0]!.x = -999;
    expect(engine.getParticles()[0]!.x).toBe(100);
  });
});

describe("ParticleEngine 注入粒子硬校验", () => {
  it("拒绝超速粒子", () => {
    expect(
      () =>
        new ParticleEngine({
          ...SIZE,
          count: 1,
          particles: [{ x: 0, y: 0, vx: 5, vy: 0, radius: 1, color: PALETTE[0] }],
        }),
    ).toThrow(RangeError);
  });

  it("拒绝调色板外颜色", () => {
    expect(
      () =>
        new ParticleEngine({
          ...SIZE,
          count: 1,
          particles: [{ x: 0, y: 0, vx: 0.5, vy: 0, radius: 1, color: "#123456" }],
        }),
    ).toThrow(RangeError);
  });

  it("拒绝注入数量超过 300 的粒子集合", () => {
    const tooMany = Array.from({ length: MAX_PARTICLES + 1 }, () => ({
      x: 0,
      y: 0,
      vx: 0.5,
      vy: 0,
      radius: 1,
      color: PALETTE[0] as string,
    }));
    expect(() => new ParticleEngine({ ...SIZE, count: tooMany.length, particles: tooMany })).toThrow(
      RangeError,
    );
  });
});

describe("ParticleEngine 聚集模式（M4.4 attract）", () => {
  const seeded = (x: number, y: number, vx: number, vy: number) =>
    new ParticleEngine({
      ...SIZE,
      count: 1,
      particles: [{ x, y, vx, vy, radius: 1, color: PALETTE[0] }],
    });

  it("设置吸引目标后粒子逐步靠近目标点", () => {
    const engine = seeded(50, 50, 0, 0);
    engine.setAttractor({ x: 300, y: 200 });
    const before = engine.getParticles()[0]!;
    const distBefore = Math.hypot(300 - before.x, 200 - before.y);
    for (let i = 0; i < 30; i++) engine.step(1);
    const after = engine.getParticles()[0]!;
    const distAfter = Math.hypot(300 - after.x, 200 - after.y);
    expect(distAfter).toBeLessThan(distBefore);
  });

  it("聚集过程中速率始终不超过 1.2 硬约束", () => {
    const engine = new ParticleEngine({ ...SIZE, count: 120 });
    engine.setAttractor({ x: 200, y: 150 });
    for (let i = 0; i < 200; i++) {
      engine.step(1);
      for (const p of engine.getParticles()) {
        expect(Math.hypot(p.vx, p.vy)).toBeLessThanOrEqual(MAX_SPEED + 1e-9);
      }
    }
  });

  it("聚集不增殖粒子：数量保持 ≤ 300", () => {
    const engine = new ParticleEngine({ ...SIZE, count: 200 });
    engine.setAttractor({ x: 200, y: 150 });
    for (let i = 0; i < 60; i++) engine.step(1);
    expect(engine.getParticles().length).toBe(200);
  });

  it("清除吸引目标后恢复漂移（位置继续变化）", () => {
    const engine = seeded(100, 100, 0.5, 0.3);
    engine.setAttractor({ x: 200, y: 200 });
    engine.step(1);
    engine.setAttractor(null);
    const before = engine.getParticles()[0]!;
    engine.step(2);
    const after = engine.getParticles()[0]!;
    expect(after.x).not.toBe(before.x);
  });

  it("非法吸引目标坐标抛 RangeError", () => {
    const engine = seeded(100, 100, 0.5, 0);
    expect(() => engine.setAttractor({ x: Number.NaN, y: 0 })).toThrow(RangeError);
    expect(() => engine.setAttractor({ x: 0, y: Number.POSITIVE_INFINITY })).toThrow(RangeError);
  });

  it("reducedMotion 下即使设置吸引目标粒子也不动", () => {
    const engine = new ParticleEngine({
      ...SIZE,
      count: 1,
      reducedMotion: true,
      particles: [{ x: 50, y: 50, vx: 0.5, vy: 0, radius: 1, color: PALETTE[0] }],
    });
    engine.setAttractor({ x: 300, y: 200 });
    engine.step(3);
    const [p] = engine.getParticles();
    expect(p.x).toBe(50);
    expect(p.y).toBe(50);
  });
});

describe("ParticleEngine 主题调色板注入（M4.4）", () => {
  const THEME_PALETTE = ["#a8b2c1", "#6f7a8c"] as const;

  it("生成粒子颜色取自注入的主题调色板", () => {
    const engine = new ParticleEngine({ ...SIZE, count: 100, palette: THEME_PALETTE });
    const allowed = new Set<string>(THEME_PALETTE);
    for (const p of engine.getParticles()) {
      expect(allowed.has(p.color)).toBe(true);
    }
  });

  it("注入粒子按主题调色板校验颜色", () => {
    expect(
      () =>
        new ParticleEngine({
          ...SIZE,
          count: 1,
          palette: THEME_PALETTE,
          particles: [{ x: 0, y: 0, vx: 0.5, vy: 0, radius: 1, color: PALETTE[0] }],
        }),
    ).toThrow(RangeError);
  });

  it("调色板超过 5 色抛 RangeError", () => {
    expect(
      () =>
        new ParticleEngine({
          ...SIZE,
          count: 1,
          palette: ["#111111", "#222222", "#333333", "#444444", "#555555", "#666666"],
        }),
    ).toThrow(RangeError);
  });

  it("空调色板抛 RangeError", () => {
    expect(() => new ParticleEngine({ ...SIZE, count: 1, palette: [] })).toThrow(RangeError);
  });

  it("未注入时仍用默认 PALETTE", () => {
    const engine = new ParticleEngine({ ...SIZE, count: 100 });
    const allowed = new Set<string>(PALETTE);
    for (const p of engine.getParticles()) {
      expect(allowed.has(p.color)).toBe(true);
    }
  });
});
