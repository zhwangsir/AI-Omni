/**
 * fieldState 场语义状态机：voice.state → 场语义参数集（FieldParams）。
 *
 * 纯函数映射，无副作用、无 three / WebGL 依赖——状态机的可测核心。
 * 桥接层（FieldStage）订阅 statusStore + hudStore，调 resolveFieldState 得参数，
 * 再经 Space.setField 注入 3D 引擎与流线 canvas。
 *
 * 态语义（球体为主形态，各态通过亮度/闪烁/辉光/膨胀区分）：
 * - idle / 不可用：完全透明（dimFactor=0）+ 粒子形态释放为自由流场——桌面待机时
 *   无任何可见占位，唤醒时粒子自然从四周汇聚成球（Space.morphTo 过渡 ≥600ms）
 * - wake_listening / recording（呼叫雪莉响应）：球体提亮至满亮 + 辉光增强 + 半径膨胀 ~12% + 极微波光
 * - follow_up_listening（续听态 M8）：球体柔和——无波纹、亮度 ×0.65、轻辉光、轻微井心倾向，等待感
 * - transcribing / thinking：球体保持，有节奏的柔和闪烁（~1.2Hz，强度克制），表达"思考中"
 * - tool_using：球体 + 中等闪烁（~1.8Hz）+ 辉光 + 井心轨道，表达"操作工具中"
 * - speaking（响应态）：球体保持，更明显的闪烁（~2.4Hz，强度更高）+ 轻辉光 + 底部流线
 *
 * 活跃态（非 idle）始终保持球体形态，不使用螺旋/环等变形——通过闪烁节奏、辉光、膨胀区分语义。
 * 过渡由引擎侧 smoothstep 缓动保证丝滑。
 *
 * 红线（CLAUDE.md §六）：粒子 high≤4000/medium≤2000/low≤800（引擎侧）；
 * 提亮 ≤20%；角速度有界；流线振幅有界；reducedMotion 静态稀疏场（无动效）。
 */
import type { VoicePipelineState } from "../data/sources";

export interface WellPosition {
  readonly x: number;
  readonly y: number;
  readonly z: number;
}

export const WELL_POSITION: WellPosition = { x: 0, y: -1.4, z: 0 };

export const FIELD_DIM_MIN = 0;
export const FIELD_DIM_MAX = 1;

export const FIELD_BRIGHTNESS_LIFT_MAX = 0.2;

export const FIELD_ORBIT_ANGULAR_VELOCITY_MAX = 0.3;

export const FIELD_FLOWLINE_AMPLITUDE_MAX = 0.5;

export const FIELD_LISTENING_RIPPLE_DURATION_MS = 2000;

const DORMANT_DIM_MULTIPLIER = 0.2;

const LISTENING_ATTRACTOR_STRENGTH = 0.3;

const FOLLOW_UP_ATTRACTOR_STRENGTH = 0.12;

const SPEAKING_FLOWLINE_AMPLITUDE = 0.3;

export type ParticleShapeKind = "sphere" | "dna_helix";

const FIELD_TOOL_USING_RIPPLE_DURATION_MS = 1200;

const FLICKER_INTENSITY_MAX = 0.5;
const FLICKER_SPEED_MAX = 4.0;
const GLOW_BOOST_MAX = 0.4;
const SPHERE_SCALE_MAX = 1.25;
const SPHERE_SCALE_MIN = 0.9;

export interface FieldAttractor {
  readonly position: WellPosition;
  readonly strength: number;
}

export interface FieldOrbit {
  readonly center: WellPosition;
  readonly angularVelocity: number;
}

export interface FieldFlowline {
  readonly amplitude: number;
}

export interface FieldRipple {
  readonly origin: WellPosition;
  readonly durationMs: number;
}

export interface FieldParams {
  readonly dimFactor: number;
  readonly brightnessLift: number;
  readonly attractor: FieldAttractor | null;
  readonly orbit: FieldOrbit | null;
  readonly flowline: FieldFlowline | null;
  readonly ripple: FieldRipple | null;
  readonly dormant: boolean;
  readonly particleShape: ParticleShapeKind | null;
  readonly pulseStrength: number;
  readonly helixRotSpeed: number;
  readonly flickerIntensity: number;
  readonly flickerSpeed: number;
  readonly glowBoost: number;
  readonly sphereScale: number;
}

export interface ResolveFieldStateOptions {
  readonly dormant?: boolean;
}

const IDLE_PARAMS: FieldParams = {
  // M32.31：idle 完全透明 + 释放形态——桌面待机时不占任何视野；
  // 唤醒后（wake_listening）粒子经 Space.morphTo 从四周汇聚成球。
  dimFactor: 0,
  brightnessLift: 0,
  attractor: null,
  orbit: null,
  flowline: null,
  ripple: null,
  dormant: false,
  particleShape: null,
  pulseStrength: 0,
  helixRotSpeed: 0,
  flickerIntensity: 0,
  flickerSpeed: 0,
  glowBoost: 0,
  sphereScale: 1.0,
};

function listeningParams(): FieldParams {
  return {
    dimFactor: 1,
    brightnessLift: FIELD_BRIGHTNESS_LIFT_MAX,
    attractor: { position: WELL_POSITION, strength: LISTENING_ATTRACTOR_STRENGTH },
    orbit: null,
    flowline: null,
    ripple: { origin: WELL_POSITION, durationMs: FIELD_LISTENING_RIPPLE_DURATION_MS },
    dormant: false,
    particleShape: "sphere",
    pulseStrength: 0.15,
    helixRotSpeed: 0,
    flickerIntensity: 0.08,
    flickerSpeed: 1.8,
    glowBoost: 0.35,
    sphereScale: 1.15,
  };
}

function thinkingParams(): FieldParams {
  return {
    dimFactor: 1,
    brightnessLift: 0.05,
    attractor: null,
    orbit: null,
    flowline: null,
    ripple: null,
    dormant: false,
    particleShape: "sphere",
    pulseStrength: 0,
    helixRotSpeed: 0,
    flickerIntensity: 0.28,
    flickerSpeed: 1.4,
    glowBoost: 0.1,
    sphereScale: 1.0,
  };
}

function followUpListeningParams(): FieldParams {
  return {
    dimFactor: 0.75,
    brightnessLift: 0,
    attractor: { position: WELL_POSITION, strength: FOLLOW_UP_ATTRACTOR_STRENGTH },
    orbit: null,
    flowline: null,
    ripple: null,
    dormant: false,
    particleShape: "sphere",
    pulseStrength: 0,
    helixRotSpeed: 0,
    flickerIntensity: 0,
    flickerSpeed: 0,
    glowBoost: 0.08,
    sphereScale: 1.0,
  };
}

function toolUsingParams(): FieldParams {
  return {
    dimFactor: 1,
    brightnessLift: 0.12,
    attractor: null,
    orbit: null,
    flowline: null,
    ripple: { origin: WELL_POSITION, durationMs: FIELD_TOOL_USING_RIPPLE_DURATION_MS },
    dormant: false,
    particleShape: "sphere",
    pulseStrength: 0.15,
    helixRotSpeed: 0,
    flickerIntensity: 0.38,
    flickerSpeed: 2.2,
    glowBoost: 0.28,
    sphereScale: 1.08,
  };
}

const SPEAKING_PARAMS: FieldParams = {
  dimFactor: 1,
  brightnessLift: 0.1,
  attractor: null,
  orbit: null,
  flowline: { amplitude: SPEAKING_FLOWLINE_AMPLITUDE },
  ripple: null,
  dormant: false,
  particleShape: "sphere",
  pulseStrength: 0.2,
  helixRotSpeed: 0,
  flickerIntensity: 0.45,
  flickerSpeed: 2.8,
  glowBoost: 0.18,
  sphereScale: 1.03,
};

export function resolveFieldState(
  voiceState: VoicePipelineState | null | undefined,
  reducedMotion: boolean,
  options: ResolveFieldStateOptions = {},
): FieldParams {
  const dormant = options.dormant ?? false;

  let base: FieldParams;
  if (voiceState === null || voiceState === undefined) {
    base = IDLE_PARAMS;
  } else {
    switch (voiceState) {
      case "idle":
        base = IDLE_PARAMS;
        break;
      case "wake_listening":
      case "recording":
        base = listeningParams();
        break;
      case "follow_up_listening":
        base = followUpListeningParams();
        break;
      case "transcribing":
      case "thinking":
        base = thinkingParams();
        break;
      case "tool_using":
        base = toolUsingParams();
        break;
      case "speaking":
        base = SPEAKING_PARAMS;
        break;
      default:
        base = IDLE_PARAMS;
    }
  }

  const dynamic = reducedMotion
    ? {
        brightnessLift: 0,
        attractor: null as FieldAttractor | null,
        orbit: null as FieldOrbit | null,
        flowline: null as FieldFlowline | null,
        ripple: null as FieldRipple | null,
        particleShape: "sphere" as ParticleShapeKind | null,
        pulseStrength: 0,
        helixRotSpeed: 0,
        flickerIntensity: 0,
        flickerSpeed: 0,
        glowBoost: 0,
        sphereScale: 1.0,
      }
    : {
        brightnessLift: Math.min(FIELD_BRIGHTNESS_LIFT_MAX, Math.max(0, base.brightnessLift)),
        attractor: base.attractor,
        orbit: base.orbit,
        flowline: base.flowline,
        ripple: base.ripple,
        particleShape: base.particleShape,
        pulseStrength: Math.min(1, Math.max(0, base.pulseStrength)),
        helixRotSpeed: Math.max(0, base.helixRotSpeed),
        flickerIntensity: Math.min(FLICKER_INTENSITY_MAX, Math.max(0, base.flickerIntensity)),
        flickerSpeed: Math.min(FLICKER_SPEED_MAX, Math.max(0, base.flickerSpeed)),
        glowBoost: Math.min(GLOW_BOOST_MAX, Math.max(0, base.glowBoost)),
        sphereScale: Math.min(SPHERE_SCALE_MAX, Math.max(SPHERE_SCALE_MIN, base.sphereScale)),
      };

  const dimFactor = dormant ? base.dimFactor * DORMANT_DIM_MULTIPLIER : base.dimFactor;

  return {
    dimFactor,
    brightnessLift: dynamic.brightnessLift,
    attractor: dynamic.attractor,
    orbit: dynamic.orbit,
    flowline: dynamic.flowline,
    ripple: dynamic.ripple,
    dormant,
    particleShape: dynamic.particleShape,
    pulseStrength: dynamic.pulseStrength,
    helixRotSpeed: dynamic.helixRotSpeed,
    flickerIntensity: dynamic.flickerIntensity,
    flickerSpeed: dynamic.flickerSpeed,
    glowBoost: dynamic.glowBoost,
    sphereScale: dynamic.sphereScale,
  };
}
