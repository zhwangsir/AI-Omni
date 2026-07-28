/**
 * flowfield 流场位移（M5.2）：vertex shader 内 hash/sine 复合伪 noise，
 * 零 CPU 逐帧成本。振幅常量有界（世界单位，呼吸感——禁止快速抖动）；
 * 时间经 uniform 驱动（uFlowTime），reduced-motion 时外部冻结时间即全场静止。
 * 纯逻辑模块：常量与 GLSL chunk 单一事实源，可独立单测。
 */

/** 流场主振幅（世界单位）：位移主项上限。 */
export const FLOW_AMPLITUDE = 0.5;
/** 时间缩放：慢速呼吸（禁频闪 / 快速抖动）。 */
export const FLOW_TIME_SCALE = 0.18;
/** 粒子漂移速度上限（世界单位 / 摆动周期），实例属性构建器共用此界。 */
export const FLOW_VELOCITY_MAX = 0.3;

/**
 * 流场位移 GLSL chunk：omniFlowOffset(seed, velocity, phase, t) → vec3。
 * 全部由有界 sin/cos 复合构成——t 不直接线性进入位移（无界漂移会飞出视野）。
 * 总位移上界 = FLOW_AMPLITUDE + |velocity| ≤ 1.2（M5 流速约束的世界单位等价）。
 */
export const FLOWFIELD_GLSL = /* glsl */ `
  vec3 omniFlowOffset(vec3 seed, vec3 velocity, float phase, float t) {
    float tt = t * ${FLOW_TIME_SCALE};
    // 大尺度流场：三个轴向的异频正弦叠加（伪 curl 感），振幅有界
    vec3 field = vec3(
      sin(tt + seed.y * 0.7 + phase),
      cos(tt * 0.8 + seed.z * 0.9 + phase * 1.3),
      sin(tt * 0.6 + seed.x * 0.5 + phase * 0.7)
    ) * ${FLOW_AMPLITUDE};
    // 个体漂移：速度向量经正弦摆动转化为有界振荡（不随时间线性累积）
    vec3 drift = velocity * sin(tt * 0.9 + phase * 2.0);
    return field + drift;
  }
`;
