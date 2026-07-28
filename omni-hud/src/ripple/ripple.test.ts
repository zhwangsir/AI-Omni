/**
 * 水波纹参数约束测试（M4.4）。
 * 用户明确要求：波纹从快速调慢、范围调大——这些要求落成导出常量的硬校验，
 * 防止后续迭代把波纹调回快而小。多层同心圆渐隐。
 */
import { describe, expect, it } from "vitest";

import {
  RIPPLE_DURATION_MS,
  RIPPLE_LAYER_STAGGER_MS,
  RIPPLE_LAYERS,
  RIPPLE_MAX_RADIUS,
  RIPPLE_MIN_DURATION_MS,
  RIPPLE_MIN_RADIUS,
  rippleLayerDelays,
} from "./ripple";

describe("水波纹参数约束（慢速、大范围）", () => {
  it("扩散时长不低于慢速下限 900ms", () => {
    expect(RIPPLE_MIN_DURATION_MS).toBeGreaterThanOrEqual(900);
    expect(RIPPLE_DURATION_MS).toBeGreaterThanOrEqual(RIPPLE_MIN_DURATION_MS);
  });

  it("扩散半径不低于大范围下限 240px", () => {
    expect(RIPPLE_MIN_RADIUS).toBeGreaterThanOrEqual(240);
    expect(RIPPLE_MAX_RADIUS).toBeGreaterThanOrEqual(RIPPLE_MIN_RADIUS);
  });

  it("多层同心圆：层数在 2..4 之间", () => {
    expect(RIPPLE_LAYERS).toBeGreaterThanOrEqual(2);
    expect(RIPPLE_LAYERS).toBeLessThanOrEqual(4);
  });

  it("层间错峰非负，且末层起步早于主波纹结束", () => {
    expect(RIPPLE_LAYER_STAGGER_MS).toBeGreaterThanOrEqual(0);
    expect(RIPPLE_LAYER_STAGGER_MS * (RIPPLE_LAYERS - 1)).toBeLessThan(RIPPLE_DURATION_MS);
  });

  it("rippleLayerDelays 返回逐层递增的延迟序列", () => {
    const delays = rippleLayerDelays();
    expect(delays).toHaveLength(RIPPLE_LAYERS);
    expect(delays[0]).toBe(0);
    for (let i = 1; i < delays.length; i++) {
      expect(delays[i]!).toBeGreaterThan(delays[i - 1]!);
    }
  });
});
