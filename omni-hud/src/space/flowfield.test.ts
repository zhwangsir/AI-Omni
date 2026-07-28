/**
 * flowfield 测试（M5.2 TDD 红）：vertex shader 内伪 noise 流场位移。
 * 振幅常量有界（世界单位、呼吸感、禁快速抖动）；时间由 uniform 驱动，
 * reduced-motion 时外部冻结时间即静止。
 * 纯逻辑：断言常量边界与 GLSL chunk 的结构约束，不执行 WebGL。
 */
import { describe, expect, it } from "vitest";

import {
  FLOWFIELD_GLSL,
  FLOW_AMPLITUDE,
  FLOW_TIME_SCALE,
  FLOW_VELOCITY_MAX,
} from "./flowfield";

describe("flowfield 振幅常量边界", () => {
  it("流场振幅有界：呼吸感但不超过世界单位上限（M5 流速约束）", () => {
    expect(FLOW_AMPLITUDE).toBeGreaterThan(0);
    // 总位移上界 = 流场振幅 + 速度摆动上界，必须 ≤ 1.2（M4 速度约束的世界单位等价）
    expect(FLOW_AMPLITUDE + FLOW_VELOCITY_MAX).toBeLessThanOrEqual(1.2);
  });

  it("时间缩放低速（禁快速抖动/频闪）", () => {
    expect(FLOW_TIME_SCALE).toBeGreaterThan(0);
    expect(FLOW_TIME_SCALE).toBeLessThanOrEqual(0.5);
  });

  it("粒子漂移速度上限为正且有界", () => {
    expect(FLOW_VELOCITY_MAX).toBeGreaterThan(0);
    expect(FLOW_VELOCITY_MAX).toBeLessThanOrEqual(0.6);
  });
});

describe("FLOWFIELD_GLSL chunk 结构", () => {
  it("导出位移函数 omniFlowOffset（seed/velocity/phase/t 四参）", () => {
    expect(FLOWFIELD_GLSL).toContain("vec3 omniFlowOffset(");
    expect(FLOWFIELD_GLSL).toContain("vec3 seed");
    expect(FLOWFIELD_GLSL).toContain("vec3 velocity");
    expect(FLOWFIELD_GLSL).toContain("float phase");
    expect(FLOWFIELD_GLSL).toContain("float t");
  });

  it("位移由有界 sin/cos 复合构成（无 unbounded 线性时间项）", () => {
    expect(FLOWFIELD_GLSL).toMatch(/sin\(/);
    expect(FLOWFIELD_GLSL).toMatch(/cos\(/);
    // 禁止 t 直接线性乘到位移上（无界漂移会飞出视野）
    expect(FLOWFIELD_GLSL).not.toMatch(/return\s+.*\bt\s*\*/);
  });

  it("振幅常量内嵌进 GLSL（单一事实源，禁止双写漂移）", () => {
    expect(FLOWFIELD_GLSL).toContain(FLOW_AMPLITUDE.toString());
  });
});
