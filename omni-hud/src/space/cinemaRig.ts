/**
 * cinemaRig 节奏电影镜头状态机（M21.4）：
 * 纯逻辑模块——根据 cinema mode + beat 事件产出相机偏移
 *（posX/posY/posZ/fovOffset/shakeX/shakeY/orbitAngle），
 * 由 createSpace 帧循环消费，叠加到基础视差 rig 之上。
 *
 * 模式（D21.2 预设模式）：
 * - off：零偏移，不干预基础 rig（默认）
 * - calm：轻微 dolly zoom（FOV ±2° 慢速呼吸），无环绕无摇晃
 * - standard：环绕（orbitAngle 随 beat 推进）+ 轻 dolly，无摇晃
 * - intense：摇晃（beat 触发指数衰减震动）+ 强环绕 + dolly zoom
 *
 * 红线（CLAUDE.md §六）：所有偏移有界、reduced-motion 恒零、
 * 无高频闪烁（呼吸频率 ≤ 0.5Hz，摇晃衰减时间常数 ≥ 0.3s）。
 *
 * 纯逻辑：无 three / WebGL / DOM 依赖，可独立单测。
 */

/** 电影镜头模式。off = 不启用（默认）。 */
export type CinemaMode = "off" | "calm" | "standard" | "intense";

const VALID_MODES: readonly CinemaMode[] = ["off", "calm", "standard", "intense"];

/** FOV 偏移硬上限（度）：克制，避免明显变形。 */
export const CINEMA_MAX_FOV_OFFSET = 2;
/** 环绕半径硬上限（世界单位）：克制，避免晕眩。 */
export const CINEMA_MAX_ORBIT_RADIUS = 0.6;
/** dolly z 偏移硬上限（世界单位）：推拉幅度有界。 */
export const CINEMA_MAX_DOLLY_Z = 0.4;
/** 摇晃幅度硬上限（世界单位）：避免光敏风险。 */
export const CINEMA_MAX_SHAKE = 0.12;

/** calm 模式 FOV 呼吸频率（Hz，~0.1Hz = 10s 周期，极慢呼吸）。 */
const CALM_BREATH_FREQ = 0.1;
/** standard 模式每 beat 推进的环绕角度（rad，~6°）。 */
const STANDARD_ORBIT_PER_BEAT = 0.105;
/** intense 模式每 beat 推进的环绕角度（rad，~11°）。 */
const INTENSE_ORBIT_PER_BEAT = 0.19;
/** intense 模式基础环绕角速度（rad/s，即使无 beat 也缓慢旋转）。 */
const INTENSE_ORBIT_DRIFT = 0.05;
/** standard 模式基础环绕角速度（rad/s，极慢漂移）。 */
const STANDARD_ORBIT_DRIFT = 0.02;
/** 摇晃衰减时间常数（秒，~300ms 落位，避免高频抖动）。 */
const SHAKE_DECAY = 0.3;
/** 摇晃频率（Hz，~12Hz 视为低频震动，不闪）。 */
const SHAKE_FREQ = 12;
/** dolly 呼吸频率（Hz，与 calm FOV 同步呼吸）。 */
const DOLLY_BREATH_FREQ = 0.1;
/** 状态切换平滑率（/s，~400ms 过渡，禁瞬跳）。 */
const MODE_TRANSITION_RATE = 2.5;
/** beat strength 钳制上限。 */
const BEAT_STRENGTH_MAX = 3;

export interface CinemaRigState {
  /** 相机 x 偏移（环绕 + 摇晃叠加，世界单位）。 */
  readonly posX: number;
  /** 相机 y 偏移（环绕 + 摇晃叠加，世界单位）。 */
  readonly posY: number;
  /** 相机 z 偏移（dolly 推拉，世界单位）。 */
  readonly posZ: number;
  /** FOV 偏移（度，dolly zoom 效果）。 */
  readonly fovOffset: number;
  /** 摇晃 x 分量（世界单位）。 */
  readonly shakeX: number;
  /** 摇晃 y 分量（世界单位）。 */
  readonly shakeY: number;
  /** 当前累积环绕角（rad，外部只读）。 */
  readonly orbitAngle: number;
}

export interface CinemaRigOptions {
  /** 初始模式（默认 off）。 */
  readonly initialMode?: CinemaMode;
  /** 初始 reduced-motion（默认 false）。 */
  readonly reducedMotion?: boolean;
}

export interface CinemaRig {
  /** 喂一帧 dt（秒）+ now（秒），返回当前帧的相机偏移。 */
  step(dt: number, now: number): CinemaRigState;
  /** 设置模式；幂等同值不重复过渡。未知模式抛 RangeError。 */
  setMode(mode: CinemaMode): void;
  /** 当前模式。 */
  getMode(): CinemaMode;
  /** beat 事件：strength ∈ [0,3]，推进环绕 + 触发摇晃（intense）。 */
  onBeat(strength: number, now: number): void;
  /** reduced-motion 开关；true 时立即归零所有偏移。 */
  setReducedMotion(on: boolean): void;
  /** 释放（停止镜头干预）；后续 step 返回全零。幂等。 */
  dispose(): void;
}

const clamp = (v: number, max: number): number => {
  if (!Number.isFinite(v)) return 0;
  return Math.min(max, Math.max(-max, v));
};

const clamp01 = (v: number): number => {
  if (!Number.isFinite(v)) return 0;
  return Math.min(1, Math.max(0, v));
};

const clampBeat = (v: number): number => {
  if (!Number.isFinite(v)) return 0;
  return Math.min(BEAT_STRENGTH_MAX, Math.max(0, v));
};

export function createCinemaRig(options: CinemaRigOptions = {}): CinemaRig {
  let mode: CinemaMode = options.initialMode ?? "off";
  let reduced = options.reducedMotion ?? false;
  let disposed = false;

  // 模式权重过渡：0=off, 1=calm, 2=standard, 3=intense
  // 实际偏移 = 权重 × 模式效果，切换时权重缓动 → 无瞬跳
  let modeWeight = mode === "off" ? 0 : mode === "calm" ? 1 : mode === "standard" ? 2 : 3;
  let targetWeight = modeWeight;

  let orbitAngle = 0;
  let shakeStrength = 0;
  let shakePhase = 0;
  let breathPhase = 0;
  let dollyPhase = 0;

  const modeIndex = (m: CinemaMode): number =>
    m === "off" ? 0 : m === "calm" ? 1 : m === "standard" ? 2 : 3;

  const step: CinemaRig["step"] = (dt, _now) => {
    if (disposed) {
      return { posX: 0, posY: 0, posZ: 0, fovOffset: 0, shakeX: 0, shakeY: 0, orbitAngle: 0 };
    }
    const safeDt = Math.max(0, Math.min(0.1, dt));

    // 权重缓动到目标（模式切换平滑）
    const weightDelta = targetWeight - modeWeight;
    if (Math.abs(weightDelta) < 0.001) {
      modeWeight = targetWeight;
    } else {
      modeWeight += weightDelta * Math.min(1, safeDt * MODE_TRANSITION_RATE);
    }

    // reduced-motion：权重强制归零（无任何镜头干预）
    const effectiveWeight = reduced ? 0 : modeWeight;

    if (effectiveWeight < 0.001) {
      // 全部归零，但 orbitAngle / phase 不重置（切回时连续）
      return { posX: 0, posY: 0, posZ: 0, fovOffset: 0, shakeX: 0, shakeY: 0, orbitAngle };
    }

    // 呼吸相位推进（calm/intense 共用，慢速）
    breathPhase += safeDt * CALM_BREATH_FREQ * Math.PI * 2;
    dollyPhase += safeDt * DOLLY_BREATH_FREQ * Math.PI * 2;

    // 环绕角自然漂移（standard/intense 均有）
    const drift = mode === "intense" ? INTENSE_ORBIT_DRIFT : STANDARD_ORBIT_DRIFT;
    if (mode === "standard" || mode === "intense") {
      orbitAngle += safeDt * drift;
    }

    // 摇晃衰减
    if (shakeStrength > 0) {
      shakeStrength *= Math.exp(-safeDt / SHAKE_DECAY);
      if (shakeStrength < 0.001) shakeStrength = 0;
      shakePhase += safeDt * SHAKE_FREQ * Math.PI * 2;
    }

    // === 计算各模式原始偏移 ===

    // calm：FOV 呼吸（正弦 ±MAX_FOV_OFFSET），dolly z 同步呼吸
    const calmWeight = clamp01(effectiveWeight - 0); // calm 起始权重 0
    const calmFov = Math.sin(breathPhase) * CINEMA_MAX_FOV_OFFSET * 0.5;
    const calmDollyZ = Math.sin(dollyPhase) * CINEMA_MAX_DOLLY_Z * 0.3;

    // standard：环绕（orbitAngle → posX/posY）+ 轻 dolly
    const standardWeight = clamp01(effectiveWeight - 1);
    const standardRadius = CINEMA_MAX_ORBIT_RADIUS * 0.6;
    const standardPosX = Math.cos(orbitAngle) * standardRadius;
    const standardPosY = Math.sin(orbitAngle) * standardRadius * 0.5; // 椭圆轨道
    const standardDollyZ = Math.sin(dollyPhase) * CINEMA_MAX_DOLLY_Z * 0.2;

    // intense：强环绕 + 摇晃 + dolly zoom
    const intenseWeight = clamp01(effectiveWeight - 2);
    const intenseRadius = CINEMA_MAX_ORBIT_RADIUS;
    const intensePosX = Math.cos(orbitAngle) * intenseRadius;
    const intensePosY = Math.sin(orbitAngle) * intenseRadius * 0.6;
    const intenseFov = Math.sin(breathPhase) * CINEMA_MAX_FOV_OFFSET;
    const intenseDollyZ = Math.sin(dollyPhase) * CINEMA_MAX_DOLLY_Z;
    const shakeX = shakeStrength > 0 ? Math.sin(shakePhase) * CINEMA_MAX_SHAKE * shakeStrength : 0;
    const shakeY =
      shakeStrength > 0 ? Math.cos(shakePhase * 1.3) * CINEMA_MAX_SHAKE * shakeStrength : 0;

    // === 按权重混合 ===
    // effectiveWeight ∈ [0,3]：0=off, [0,1]=calm 渐入, [1,2]=standard 叠加, [2,3]=intense 叠加
    const fovOffset =
      calmFov * calmWeight * (1 - intenseWeight * 0.3) + intenseFov * intenseWeight;
    const dollyZ = calmDollyZ * calmWeight + standardDollyZ * standardWeight + intenseDollyZ * intenseWeight;
    const orbitPosX = standardPosX * standardWeight + intensePosX * intenseWeight;
    const orbitPosY = standardPosY * standardWeight + intensePosY * intenseWeight;
    const posX = orbitPosX + shakeX * intenseWeight;
    const posY = orbitPosY + shakeY * intenseWeight;

    return {
      posX: clamp(posX, CINEMA_MAX_ORBIT_RADIUS + CINEMA_MAX_SHAKE),
      posY: clamp(posY, CINEMA_MAX_ORBIT_RADIUS + CINEMA_MAX_SHAKE),
      posZ: clamp(dollyZ, CINEMA_MAX_DOLLY_Z),
      fovOffset: clamp(fovOffset, CINEMA_MAX_FOV_OFFSET),
      shakeX: clamp(shakeX * intenseWeight, CINEMA_MAX_SHAKE),
      shakeY: clamp(shakeY * intenseWeight, CINEMA_MAX_SHAKE),
      orbitAngle,
    };
  };

  const setMode: CinemaRig["setMode"] = (next) => {
    if (!VALID_MODES.includes(next)) {
      throw new RangeError(`未知 cinema mode: ${String(next)}`);
    }
    if (mode === next) return;
    mode = next;
    targetWeight = modeIndex(next);
    // off = 用户显式停用电影镜头：立即归零权重与摇晃（硬停止）
    // 其他模式间切换走权重缓动（无瞬跳）
    if (next === "off") {
      modeWeight = 0;
      shakeStrength = 0;
    }
    // orbitAngle / phase 不重置：切回时从当前位置连续
  };

  const onBeat: CinemaRig["onBeat"] = (strength, _now) => {
    if (disposed || reduced) return;
    const s = clampBeat(strength);
    if (s === 0) return;
    // standard / intense：beat 推进环绕角
    if (mode === "standard") {
      orbitAngle += STANDARD_ORBIT_PER_BEAT * (0.5 + s * 0.5);
    } else if (mode === "intense") {
      orbitAngle += INTENSE_ORBIT_PER_BEAT * (0.5 + s * 0.5);
      // intense：beat 触发摇晃（取较大值，不覆盖更强进行中震动）
      if (s > shakeStrength) shakeStrength = s / BEAT_STRENGTH_MAX;
    }
  };

  const setReducedMotion: CinemaRig["setReducedMotion"] = (on) => {
    reduced = on;
    if (on) {
      shakeStrength = 0;
    }
  };

  const dispose: CinemaRig["dispose"] = () => {
    disposed = true;
    shakeStrength = 0;
  };

  return {
    step,
    setMode,
    getMode: () => mode,
    onBeat,
    setReducedMotion,
    dispose,
  };
}
