/**
 * ripples 3D 水波纹队列测试（M5.3 TDD 红）：
 * - 参数硬约束：生命周期下限 ≥1200ms（慢速）、扩散半径覆盖全粒子场（大范围）、
 *   位移幅度克制（禁爆散）；
 * - 波形：波前高斯轻推、内侧快速回落、随生命周期衰减、过期归零；
 * - 队列：并发 ≤4、过期自动出队、槽位复用、入参与时长硬校验、uniform array 上传。
 * 纯逻辑测试：不依赖 three / WebGL。
 */
import { describe, expect, it } from "vitest";

import {
  createRippleQueue,
  sampleRippleWave,
  RIPPLE_DEFAULT_DURATION_MS,
  RIPPLE_FRONT_SIGMA,
  RIPPLE_GLSL,
  RIPPLE_MAX_CONCURRENT,
  RIPPLE_MAX_PUSH,
  RIPPLE_MIN_DURATION_MS,
  RIPPLE_TRAVEL_RADIUS,
} from "./ripples";
import { VOLUME_EXTENT } from "./particles";

describe("ripples 参数硬约束（审美红线：慢速大范围、禁爆散）", () => {
  it("默认生命周期 ~2s 且不低于 1200ms 慢速下限", () => {
    expect(RIPPLE_MIN_DURATION_MS).toBeGreaterThanOrEqual(1200);
    expect(RIPPLE_DEFAULT_DURATION_MS).toBeGreaterThanOrEqual(RIPPLE_MIN_DURATION_MS);
    expect(RIPPLE_DEFAULT_DURATION_MS).toBeLessThanOrEqual(2500);
  });

  it("扩散半径覆盖整个粒子体积分布（大范围）", () => {
    const maxExtent = Math.max(VOLUME_EXTENT.x, VOLUME_EXTENT.y, VOLUME_EXTENT.z);
    expect(RIPPLE_TRAVEL_RADIUS).toBeGreaterThan(maxExtent);
  });

  it("位移幅度克制（轻推非爆散，硬上限 0.8 世界单位）", () => {
    expect(RIPPLE_MAX_PUSH).toBeGreaterThan(0);
    expect(RIPPLE_MAX_PUSH).toBeLessThanOrEqual(0.8);
  });

  it("并发上限为 4", () => {
    expect(RIPPLE_MAX_CONCURRENT).toBe(4);
  });
});

describe("sampleRippleWave 波形（轻推后回落）", () => {
  const LIFE = 2; // 秒

  it("波前随时长线性匀速推进（慢速扩散）", () => {
    expect(sampleRippleWave(0, LIFE / 2, LIFE).front).toBeCloseTo(RIPPLE_TRAVEL_RADIUS / 2, 5);
    expect(sampleRippleWave(0, LIFE / 4, LIFE).front).toBeCloseTo(RIPPLE_TRAVEL_RADIUS / 4, 5);
  });

  it("波前处位移最大且不超幅度上限；前沿之外几乎不受影响", () => {
    const age = LIFE / 2;
    const front = RIPPLE_TRAVEL_RADIUS * (age / LIFE);
    const atFront = sampleRippleWave(front, age, LIFE).displacement;
    const farAhead = sampleRippleWave(front + RIPPLE_FRONT_SIGMA * 4, age, LIFE).displacement;
    expect(atFront).toBeGreaterThan(0);
    expect(atFront).toBeLessThanOrEqual(RIPPLE_MAX_PUSH);
    expect(farAhead).toBeLessThan(atFront * 0.1);
  });

  it("前沿内侧粒子已回落（轻推后归位，不拖尾爆散）", () => {
    const age = LIFE / 2;
    const front = RIPPLE_TRAVEL_RADIUS * (age / LIFE);
    const atFront = sampleRippleWave(front, age, LIFE).displacement;
    const behind = sampleRippleWave(front - RIPPLE_FRONT_SIGMA * 2, age, LIFE).displacement;
    expect(behind).toBeGreaterThanOrEqual(0);
    expect(behind).toBeLessThan(atFront * 0.5);
  });

  it("位移随生命周期衰减（fade 单调不增）", () => {
    const distance = RIPPLE_TRAVEL_RADIUS * 0.25;
    const early = sampleRippleWave(distance, LIFE * 0.25, LIFE).displacement;
    const late = sampleRippleWave(distance, LIFE * 0.9, LIFE).displacement;
    expect(early).toBeGreaterThan(late);
  });

  it("生命周期结束瞬间及之后位移与衰减归零", () => {
    expect(sampleRippleWave(1, LIFE, LIFE).displacement).toBe(0);
    expect(sampleRippleWave(1, LIFE + 0.1, LIFE).fade).toBe(0);
  });

  it("非法输入抛 RangeError", () => {
    expect(() => sampleRippleWave(-1, 1, LIFE)).toThrow(RangeError);
    expect(() => sampleRippleWave(1, -1, LIFE)).toThrow(RangeError);
    expect(() => sampleRippleWave(1, 1, 0)).toThrow(RangeError);
    expect(() => sampleRippleWave(Number.NaN, 1, LIFE)).toThrow(RangeError);
  });
});

describe("createRippleQueue 并发与过期", () => {
  it("并发上限 4：第 5 条入队被拒绝且不挤掉旧波纹", () => {
    const queue = createRippleQueue();
    for (let i = 0; i < RIPPLE_MAX_CONCURRENT; i++) {
      expect(queue.add({ x: i, y: 0, z: 0, startedAt: 1000 })).toBe(true);
    }
    expect(queue.add({ x: 9, y: 9, z: 0, startedAt: 1000 })).toBe(false);
    expect(queue.size()).toBe(RIPPLE_MAX_CONCURRENT);
  });

  it("过期波纹自动出队，槽位可复用", () => {
    const queue = createRippleQueue();
    expect(queue.add({ x: 0, y: 0, z: 0, startedAt: 1000, durationMs: 2000 })).toBe(true);
    queue.prune(2999); // 生命期内
    expect(queue.size()).toBe(1);
    queue.prune(3001); // 已过期（1000 + 2000）
    expect(queue.size()).toBe(0);
    expect(queue.add({ x: 1, y: 1, z: 0, startedAt: 3001 })).toBe(true);
  });

  it("生命周期下限硬校验：低于 1200ms 抛 RangeError", () => {
    const queue = createRippleQueue();
    expect(() => queue.add({ x: 0, y: 0, z: 0, startedAt: 0, durationMs: 1199 })).toThrow(
      RangeError,
    );
    expect(() =>
      queue.add({ x: 0, y: 0, z: 0, startedAt: 0, durationMs: RIPPLE_MIN_DURATION_MS }),
    ).not.toThrow();
  });

  it("非法坐标 / 入队时刻抛 RangeError", () => {
    const queue = createRippleQueue();
    expect(() => queue.add({ x: Number.NaN, y: 0, z: 0, startedAt: 0 })).toThrow(RangeError);
    expect(() => queue.add({ x: 0, y: Number.POSITIVE_INFINITY, z: 0, startedAt: 0 })).toThrow(
      RangeError,
    );
    expect(() => queue.add({ x: 0, y: 0, z: 0, startedAt: Number.NaN })).toThrow(RangeError);
  });

  it("writeUniforms 上传 origin(vec3) 与秒制时间；空槽位生命周期写 0", () => {
    const queue = createRippleQueue();
    queue.add({ x: 1, y: 2, z: 3, startedAt: 1500 });
    const origins = new Float32Array(RIPPLE_MAX_CONCURRENT * 3);
    const times = new Float32Array(RIPPLE_MAX_CONCURRENT * 2);
    queue.writeUniforms(origins, times, 1600);
    expect(origins[0]).toBe(1);
    expect(origins[1]).toBe(2);
    expect(origins[2]).toBe(3);
    expect(times[0]).toBeCloseTo(1.5, 5);
    expect(times[1]).toBeCloseTo(RIPPLE_DEFAULT_DURATION_MS / 1000, 5);
    // 槽位 1 空闲：生命周期为 0（shader 跳过）
    expect(times[3]).toBe(0);
  });

  it("writeUniforms 顺手清理过期槽位（过期出队契约）", () => {
    const queue = createRippleQueue();
    queue.add({ x: 0, y: 0, z: 0, startedAt: 0, durationMs: RIPPLE_MIN_DURATION_MS });
    const origins = new Float32Array(RIPPLE_MAX_CONCURRENT * 3);
    const times = new Float32Array(RIPPLE_MAX_CONCURRENT * 2);
    queue.writeUniforms(origins, times, RIPPLE_MIN_DURATION_MS + 1);
    expect(times[1]).toBe(0);
    expect(queue.size()).toBe(0);
  });

  it("uniform 数组长度不匹配抛 RangeError", () => {
    const queue = createRippleQueue();
    expect(() =>
      queue.writeUniforms(new Float32Array(3), new Float32Array(2), 0),
    ).toThrow(RangeError);
  });

  it("GLSL chunk 含径向位移函数与并发槽位常量（单一事实源）", () => {
    expect(RIPPLE_GLSL).toContain("omniRippleOffset");
    expect(RIPPLE_GLSL).toContain(`uRippleOrigins[${RIPPLE_MAX_CONCURRENT}]`);
    expect(RIPPLE_GLSL).toContain("uNowSec");
  });
});
