/**
 * fieldState 场语义状态机测试：
 * - resolveFieldState 八态 + null（不可用）全覆盖；
 * - reducedMotion 各态降级为静态稀疏场（无波纹/无轨道/无流线/无倾向/无闪烁/无辉光）；
 * - 边界硬钳制：dim ∈ [0,1]、brightnessLift ≤ 0.2、角速度有界、流线振幅有界、
 *   flickerIntensity ≤ 0.5、flickerSpeed ≤ 4、glowBoost ≤ 0.4、sphereScale ∈ [0.9, 1.25]；
 * - 所有态统一保持 sphere 形态（区别仅在亮度/闪烁/辉光/膨胀）。
 * 纯函数测试：不依赖 three / WebGL / React。
 */
import { describe, expect, it } from "vitest";

import type { VoicePipelineState } from "../data/sources";
import {
  FIELD_BRIGHTNESS_LIFT_MAX,
  FIELD_DIM_MAX,
  FIELD_DIM_MIN,
  FIELD_FLOWLINE_AMPLITUDE_MAX,
  FIELD_LISTENING_RIPPLE_DURATION_MS,
  FIELD_ORBIT_ANGULAR_VELOCITY_MAX,
  WELL_POSITION,
  type FieldParams,
  type ParticleShapeKind,
  resolveFieldState,
} from "./fieldState";

const ALL_STATES: readonly VoicePipelineState[] = [
  "idle",
  "wake_listening",
  "follow_up_listening",
  "recording",
  "transcribing",
  "thinking",
  "tool_using",
  "speaking",
];

/** 所有 FieldParams 恒满足的硬边界（任意态 + reducedMotion 均不得违反）。 */
function expectWithinHardBounds(params: FieldParams): void {
  expect(params.dimFactor).toBeGreaterThanOrEqual(FIELD_DIM_MIN);
  expect(params.dimFactor).toBeLessThanOrEqual(FIELD_DIM_MAX);
  expect(params.brightnessLift).toBeGreaterThanOrEqual(0);
  expect(params.brightnessLift).toBeLessThanOrEqual(FIELD_BRIGHTNESS_LIFT_MAX);
  if (params.orbit) {
    expect(Math.abs(params.orbit.angularVelocity)).toBeLessThanOrEqual(
      FIELD_ORBIT_ANGULAR_VELOCITY_MAX,
    );
  }
  if (params.flowline) {
    expect(params.flowline.amplitude).toBeGreaterThanOrEqual(0);
    expect(params.flowline.amplitude).toBeLessThanOrEqual(FIELD_FLOWLINE_AMPLITUDE_MAX);
  }
  if (params.attractor) {
    expect(params.attractor.strength).toBeGreaterThanOrEqual(0);
  }
  expect(params.pulseStrength).toBeGreaterThanOrEqual(0);
  expect(params.pulseStrength).toBeLessThanOrEqual(1);
  expect(params.helixRotSpeed).toBeGreaterThanOrEqual(0);
  expect(params.flickerIntensity).toBeGreaterThanOrEqual(0);
  expect(params.flickerIntensity).toBeLessThanOrEqual(0.5);
  expect(params.flickerSpeed).toBeGreaterThanOrEqual(0);
  expect(params.flickerSpeed).toBeLessThanOrEqual(4);
  expect(params.glowBoost).toBeGreaterThanOrEqual(0);
  expect(params.glowBoost).toBeLessThanOrEqual(0.4);
  expect(params.sphereScale).toBeGreaterThanOrEqual(0.9);
  expect(params.sphereScale).toBeLessThanOrEqual(1.25);
  const validShapes: ParticleShapeKind[] = ["sphere", "dna_helix"];
  if (params.particleShape !== null) {
    expect(validShapes).toContain(params.particleShape);
  }
}

describe("WELL_POSITION 声井位置常量", () => {
  it("导出为底部居中（x=0, z=0，y 为负值位于粒子体积下沿）", () => {
    expect(WELL_POSITION.x).toBe(0);
    expect(WELL_POSITION.z).toBe(0);
    expect(WELL_POSITION.y).toBeLessThan(0);
    expect(WELL_POSITION.y).toBeGreaterThan(-2.6);
    expect(WELL_POSITION.y).toBeLessThanOrEqual(-1);
  });
});

describe("resolveFieldState 全态 + 不可用 + reducedMotion 全覆盖", () => {
  it("所有状态全部返回合法 FieldParams（边界硬钳制），且 particleShape 统一为 sphere", () => {
    for (const state of ALL_STATES) {
      const params = resolveFieldState(state, false);
      expect(params, state).toBeDefined();
      expect(params.particleShape, state).toBe("sphere");
      expectWithinHardBounds(params);
    }
  });

  it("null / undefined（源不可用）= idle 等价：凝聚球体 dim=0.8，柔和呼吸微光", () => {
    const expected = resolveFieldState("idle", false);
    const nullParams = resolveFieldState(null, false);
    const undefParams = resolveFieldState(undefined, false);
    expect(nullParams).toEqual(expected);
    expect(undefParams).toEqual(expected);
    expect(expected.dimFactor).toBe(0.8);
    expect(expected.attractor).toBeNull();
    expect(expected.orbit).toBeNull();
    expect(expected.flowline).toBeNull();
    expect(expected.ripple).toBeNull();
    expect(expected.brightnessLift).toBe(0.03);
    expect(expected.particleShape).toBe("sphere");
    expect(expected.pulseStrength).toBe(0.08);
    expect(expected.helixRotSpeed).toBe(0);
    expect(expected.flickerIntensity).toBe(0.12);
    expect(expected.flickerSpeed).toBe(0.8);
    expect(expected.glowBoost).toBe(0.05);
    expect(expected.sphereScale).toBe(1);
  });

  it("idle：dim=0.8 柔和球体、轻柔呼吸闪烁、微辉光、半径 1.0", () => {
    const params = resolveFieldState("idle", false);
    expect(params.dimFactor).toBe(0.8);
    expect(params.attractor).toBeNull();
    expect(params.orbit).toBeNull();
    expect(params.flowline).toBeNull();
    expect(params.ripple).toBeNull();
    expect(params.particleShape).toBe("sphere");
    expect(params.pulseStrength).toBe(0.08);
    expect(params.helixRotSpeed).toBe(0);
    expect(params.flickerIntensity).toBe(0.12);
    expect(params.flickerSpeed).toBe(0.8);
    expect(params.glowBoost).toBe(0.05);
    expect(params.sphereScale).toBe(1);
  });

  it("wake_listening / recording（呼叫雪莉）：球体提亮满亮 + 强辉光 + 半径膨胀 ~15% + 轻微脉动 + 极微闪烁 + 声井波纹+倾向", () => {
    for (const state of ["wake_listening", "recording"] as const) {
      const params = resolveFieldState(state, false);
      expect(params.particleShape, state).toBe("sphere");
      expect(params.dimFactor, state).toBe(1);
      expect(params.brightnessLift, state).toBeGreaterThan(0.15);
      expect(params.brightnessLift, state).toBeLessThanOrEqual(FIELD_BRIGHTNESS_LIFT_MAX);
      expect(params.pulseStrength, state).toBeGreaterThan(0);
      expect(params.glowBoost, state).toBeGreaterThanOrEqual(0.25);
      expect(params.sphereScale, state).toBeGreaterThan(1.1);
      expect(params.sphereScale, state).toBeLessThan(1.2);
      expect(params.flickerIntensity, state).toBeLessThan(0.15);
      expect(params.ripple, state).not.toBeNull();
      expect(params.ripple!.origin).toEqual(WELL_POSITION);
      expect(params.ripple!.durationMs).toBeGreaterThanOrEqual(FIELD_LISTENING_RIPPLE_DURATION_MS);
      expect(params.attractor, state).not.toBeNull();
      expect(params.helixRotSpeed, state).toBe(0);
    }
  });

  it("transcribing / thinking（思考态）：球体保持，有节奏柔和闪烁（~1.4Hz，强度克制 0.25~0.3），轻辉光，无倾向/轨道/波纹", () => {
    for (const state of ["transcribing", "thinking"] as const) {
      const params = resolveFieldState(state, false);
      expect(params.particleShape, state).toBe("sphere");
      expect(params.dimFactor, state).toBe(1);
      expect(params.flickerIntensity, state).toBeGreaterThan(0.24);
      expect(params.flickerIntensity, state).toBeLessThanOrEqual(0.3);
      expect(params.flickerSpeed, state).toBeGreaterThan(1.0);
      expect(params.flickerSpeed, state).toBeLessThan(1.8);
      expect(params.glowBoost, state).toBeGreaterThan(0.05);
      expect(params.glowBoost, state).toBeLessThan(0.15);
      expect(params.sphereScale, state).toBe(1);
      expect(params.pulseStrength, state).toBe(0);
      expect(params.helixRotSpeed, state).toBe(0);
      expect(params.attractor, state).toBeNull();
      expect(params.orbit, state).toBeNull();
      expect(params.ripple, state).toBeNull();
      expect(params.flowline, state).toBeNull();
    }
  });

  it("speaking（响应态）：球体保持，更明显闪烁（~2.8Hz，强度更高 0.4~0.5）+ 轻辉光 + 底部流线 + 轻脉动", () => {
    const params = resolveFieldState("speaking", false);
    expect(params.particleShape).toBe("sphere");
    expect(params.dimFactor).toBe(1);
    expect(params.brightnessLift).toBeGreaterThan(0.05);
    expect(params.pulseStrength).toBeGreaterThan(0.1);
    expect(params.pulseStrength).toBeLessThanOrEqual(1);
    expect(params.flickerIntensity).toBeGreaterThan(0.4);
    expect(params.flickerIntensity).toBeLessThanOrEqual(0.5);
    expect(params.flickerSpeed).toBeGreaterThan(2.4);
    expect(params.flickerSpeed).toBeLessThanOrEqual(4);
    expect(params.glowBoost).toBeGreaterThan(0.12);
    expect(params.glowBoost).toBeLessThan(0.25);
    expect(params.sphereScale).toBeGreaterThan(1);
    expect(params.sphereScale).toBeLessThan(1.08);
    expect(params.helixRotSpeed).toBe(0);
    expect(params.flowline).not.toBeNull();
    expect(params.flowline!.amplitude).toBeGreaterThan(0);
    expect(params.flowline!.amplitude).toBeLessThanOrEqual(FIELD_FLOWLINE_AMPLITUDE_MAX);
    expect(params.attractor).toBeNull();
    expect(params.orbit).toBeNull();
    expect(params.ripple).toBeNull();
  });

  it("tool_using（工具调用态）：球体 + 中等闪烁 + 辉光 + 井心波纹+提亮，表达操作工具中（无轨道无吸引偏移）", () => {
    const params = resolveFieldState("tool_using", false);
    expect(params.particleShape).toBe("sphere");
    expect(params.dimFactor).toBeGreaterThan(0.9);
    expect(params.brightnessLift).toBeGreaterThan(0.1);
    expect(params.flickerIntensity).toBeGreaterThan(0.3);
    expect(params.flickerIntensity).toBeLessThan(0.42);
    expect(params.flickerSpeed).toBeGreaterThan(1.8);
    expect(params.flickerSpeed).toBeLessThan(2.6);
    expect(params.glowBoost).toBeGreaterThan(0.2);
    expect(params.glowBoost).toBeLessThan(0.35);
    expect(params.sphereScale).toBeGreaterThan(1.04);
    expect(params.sphereScale).toBeLessThan(1.12);
    expect(params.pulseStrength).toBeGreaterThan(0);
    expect(params.helixRotSpeed).toBe(0);
    expect(params.attractor).toBeNull();
    expect(params.orbit).toBeNull();
    expect(params.ripple).not.toBeNull();
  });

  it("follow_up_listening（续听态）：球体柔和 dim≈0.75，无波纹、轻辉光、轻微井心倾向，等待感", () => {
    const params = resolveFieldState("follow_up_listening", false);
    expect(params.dimFactor).toBeGreaterThan(0.6);
    expect(params.dimFactor).toBeLessThanOrEqual(0.8);
    expect(params.particleShape).toBe("sphere");
    expect(params.flickerIntensity).toBe(0);
    expect(params.flickerSpeed).toBe(0);
    expect(params.glowBoost).toBeGreaterThan(0);
    expect(params.glowBoost).toBeLessThan(0.12);
    expect(params.sphereScale).toBe(1);
    expect(params.pulseStrength).toBe(0);
    expect(params.attractor).not.toBeNull();
    expect(params.attractor!.strength).toBeLessThan(0.2);
    expect(params.ripple).toBeNull();
    expect(params.dormant).toBe(false);
  });

  it("dormant 休眠标志默认为 false（参数位预留）", () => {
    for (const state of ALL_STATES) {
      expect(resolveFieldState(state, false).dormant).toBe(false);
    }
    expect(resolveFieldState(null, false).dormant).toBe(false);
  });
});

describe("resolveFieldState reducedMotion 降级（静态稀疏场）", () => {
  it("全态 + null 在 reducedMotion 下均退化为静态：无波纹/轨道/流线/倾向/闪烁/辉光动画，恒球体，scale=1", () => {
    for (const state of [...ALL_STATES, null] as const) {
      const params = resolveFieldState(state, true);
      expect(params.ripple, String(state)).toBeNull();
      expect(params.orbit, String(state)).toBeNull();
      expect(params.flowline, String(state)).toBeNull();
      expect(params.attractor, String(state)).toBeNull();
      expect(params.brightnessLift, String(state)).toBe(0);
      expect(params.pulseStrength, String(state)).toBe(0);
      expect(params.helixRotSpeed, String(state)).toBe(0);
      expect(params.flickerIntensity, String(state)).toBe(0);
      expect(params.flickerSpeed, String(state)).toBe(0);
      expect(params.glowBoost, String(state)).toBe(0);
      expect(params.sphereScale, String(state)).toBe(1);
      expect(params.particleShape, String(state)).toBe("sphere");
      expectWithinHardBounds(params);
    }
  });

  it("reducedMotion 下 idle/null 仍为 dim=0.8（不暗到 0，保留隐约在场）", () => {
    expect(resolveFieldState("idle", true).dimFactor).toBe(0.8);
    expect(resolveFieldState(null, true).dimFactor).toBe(0.8);
  });

  it("reducedMotion 下 speaking 仍 dim=1（场保持可见，让位由 UI 层处理）", () => {
    expect(resolveFieldState("speaking", true).dimFactor).toBe(1);
  });

  it("reducedMotion 下 wake_listening 不触发波纹（无动效红线）", () => {
    expect(resolveFieldState("wake_listening", true).ripple).toBeNull();
    expect(resolveFieldState("recording", true).ripple).toBeNull();
  });
});

describe("resolveFieldState 纯函数稳定性", () => {
  it("同入参同输出（引用相等性——纯函数应返回结构相等的值）", () => {
    const a = resolveFieldState("speaking", false);
    const b = resolveFieldState("speaking", false);
    expect(a).toEqual(b);
  });

  it("dormant 标志为 true 时 idle 再 ×0.2（休眠参数位预留，仅断言乘法语义）", () => {
    const dormantParams = resolveFieldState("idle", false, { dormant: true });
    expect(dormantParams.dimFactor).toBeCloseTo(0.16, 6);
    expect(dormantParams.dormant).toBe(true);
  });
});
