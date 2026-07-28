/**
 * shelf/animation 卡片架动画状态机（M20.5 TDD 红）：
 * - stagger 入场：每张卡片延迟 STAGGER_MS（50ms）启动入场动画；
 * - 入场进度 ease-out（smoothstep，Film Atelier 风格克制有物理感）；
 * - 收缩消散：触发 exit 后所有卡片同步淡出（透明度 + scale 收敛到 0）；
 * - reducedMotion：stagger 归零（所有卡片同步直挂），easing 退化为阶跃；
 * - 纯逻辑模块：不依赖 three / React / DOM，可独立单测。
 */
import { describe, expect, it } from "vitest";

import {
  ENTER_DURATION_MS,
  EXIT_DURATION_MS,
  STAGGER_MS,
  createShelfAnimation,
  easeOutSmoothstep,
} from "./animation";

describe("easeOutSmoothstep 缓动函数", () => {
  it("t=0 返回 0", () => {
    expect(easeOutSmoothstep(0)).toBe(0);
  });

  it("t=1 返回 1", () => {
    expect(easeOutSmoothstep(1)).toBe(1);
  });

  it("t=0.5 返回 0.5（smoothstep 对称）", () => {
    expect(easeOutSmoothstep(0.5)).toBeCloseTo(0.5, 5);
  });

  it("t 在 (0, 1) 内返回值在 (0, 1) 内（单调递增）", () => {
    let prev = 0;
    for (let i = 1; i <= 100; i++) {
      const t = i / 100;
      const v = easeOutSmoothstep(t);
      expect(v).toBeGreaterThan(prev);
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(1);
      prev = v;
    }
  });

  it("t 越界钳制（<0 → 0，>1 → 1）", () => {
    expect(easeOutSmoothstep(-1)).toBe(0);
    expect(easeOutSmoothstep(2)).toBe(1);
  });
});

describe("ShelfAnimation 入场 stagger", () => {
  it("初始状态所有卡片 progress=0", () => {
    const anim = createShelfAnimation(3);
    expect(anim.getState(0).enterProgress).toBe(0);
    expect(anim.getState(2).enterProgress).toBe(0);
  });

  it("触发 enter 后第 0 张立即开始（progress>0），第 2 张延迟 2*STAGGER_MS", () => {
    const anim = createShelfAnimation(3);
    anim.enter(0);
    // 推进 1ms：第 0 张已开始（progress>0），第 1/2 张尚未到延迟
    anim.step(1);
    expect(anim.getState(0).enterProgress).toBeGreaterThan(0);
    expect(anim.getState(1).enterProgress).toBe(0);
    expect(anim.getState(2).enterProgress).toBe(0);
    // 推进到 STAGGER_MS 后第 1 张开始
    anim.step(STAGGER_MS);
    expect(anim.getState(1).enterProgress).toBeGreaterThan(0);
    expect(anim.getState(2).enterProgress).toBe(0);
    // 推进到 2*STAGGER_MS 后第 2 张开始
    anim.step(STAGGER_MS);
    expect(anim.getState(2).enterProgress).toBeGreaterThan(0);
  });

  it("推进足够长时间后所有卡片 progress=1（入场完成）", () => {
    const anim = createShelfAnimation(5);
    anim.enter(0);
    // 总时长 = ENTER_DURATION_MS + (5-1)*STAGGER_MS
    const totalMs = ENTER_DURATION_MS + 4 * STAGGER_MS + 100;
    anim.step(totalMs);
    for (let i = 0; i < 5; i++) {
      expect(anim.getState(i).enterProgress).toBeCloseTo(1, 5);
    }
  });

  it("reducedMotion=true 时所有卡片同步直挂（progress=1，无 stagger）", () => {
    const anim = createShelfAnimation(3, { reducedMotion: true });
    anim.enter(0);
    anim.step(0);
    for (let i = 0; i < 3; i++) {
      expect(anim.getState(i).enterProgress).toBe(1);
    }
  });
});

describe("ShelfAnimation 收缩消散", () => {
  it("初始 exitProgress=1（完全可见）", () => {
    const anim = createShelfAnimation(3);
    expect(anim.getState(0).exitProgress).toBe(1);
  });

  it("触发 exit 后 exitProgress 从 1 收敛到 0", () => {
    const anim = createShelfAnimation(3);
    anim.enter(0);
    anim.step(ENTER_DURATION_MS + 4 * STAGGER_MS);
    // 入场完成
    expect(anim.getState(0).exitProgress).toBe(1);
    // 触发收缩
    anim.exit(0);
    anim.step(EXIT_DURATION_MS + 100);
    expect(anim.getState(0).exitProgress).toBeCloseTo(0, 5);
  });

  it("exit 期间所有卡片同步收缩（无 stagger）", () => {
    const anim = createShelfAnimation(5);
    anim.enter(0);
    anim.step(ENTER_DURATION_MS + 4 * STAGGER_MS);
    anim.exit(0);
    // 推进少量时间，所有卡片 exitProgress 应同步下降
    anim.step(EXIT_DURATION_MS / 2);
    const p0 = anim.getState(0).exitProgress;
    const p4 = anim.getState(4).exitProgress;
    expect(p0).toBeCloseTo(p4, 5);
    expect(p0).toBeLessThan(1);
    expect(p0).toBeGreaterThan(0);
  });

  it("reducedMotion=true 时 exit 瞬时完成（exitProgress=0）", () => {
    const anim = createShelfAnimation(3, { reducedMotion: true });
    anim.exit(0);
    anim.step(0);
    expect(anim.getState(0).exitProgress).toBe(0);
  });
});

describe("ShelfAnimation 重置", () => {
  it("reset 把所有卡片 enterProgress=0 / exitProgress=1", () => {
    const anim = createShelfAnimation(3);
    anim.enter(0);
    anim.step(100);
    anim.reset();
    for (let i = 0; i < 3; i++) {
      expect(anim.getState(i).enterProgress).toBe(0);
      expect(anim.getState(i).exitProgress).toBe(1);
    }
  });
});

describe("ShelfAnimation 卡片数变化", () => {
  it("setCardCount 扩展新卡片初始 enterProgress=0", () => {
    const anim = createShelfAnimation(2);
    anim.enter(0);
    anim.step(ENTER_DURATION_MS);
    // 扩展到 4 张
    anim.setCardCount(4);
    // 旧卡片保持入场完成
    expect(anim.getState(0).enterProgress).toBeCloseTo(1, 5);
    // 新卡片未入场
    expect(anim.getState(2).enterProgress).toBe(0);
    expect(anim.getState(3).enterProgress).toBe(0);
  });

  it("setCardCount 缩减保留前 N 张状态", () => {
    const anim = createShelfAnimation(4);
    anim.enter(0);
    anim.step(ENTER_DURATION_MS);
    anim.setCardCount(2);
    expect(anim.getState(0).enterProgress).toBeCloseTo(1, 5);
    expect(() => anim.getState(2)).toThrow(); // 越界
  });
});
