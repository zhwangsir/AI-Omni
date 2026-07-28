/**
 * attractor 指针吸引子（M5.2）：指针 NDC 反投影到粒子层深度平面 →
 * 吸引子世界坐标（位置平滑 lerp 跟随）；强度钳制 [0, MAX]、近距强阻尼
 * （smoothstep 衰减，粒子不被吸穿 / 不爆粒）；无指针时强度归零（纯流场）。
 * GLSL chunk 供 particles vertex shader 内联，位移上限 ATTRACTOR_REACH 硬封顶。
 * 纯逻辑模块：不依赖 three / WebGL，可独立单测。
 */

/** 吸引子强度上限：超过即钳制（防爆粒红线）。 */
export const ATTRACTOR_MAX_STRENGTH = 1.6;
/** 指针悬停时的基础聚集强度（克制，只是轻微聚拢而非黑洞）。 */
export const ATTRACTOR_BASE_STRENGTH = 0.35;
/** 脉冲默认强度（点击瞬间，仍 ≤ MAX）。 */
export const ATTRACTOR_PULSE_STRENGTH = 1.2;
/** 近距阻尼半径：小于此距离的粒子拉力平滑归零（不被吸穿）。 */
export const ATTRACTOR_NEAR_RADIUS = 0.9;
/** 远距指数衰减系数：拉力随距离 e^{-d·k} 衰减。 */
export const ATTRACTOR_FALLOFF = 0.22;
/** 单片位移上限（世界单位）：无论强度多大，位移硬封顶。 */
export const ATTRACTOR_REACH = 1.1;
/** 吸引子位置跟随 lerp 系数（平滑跟随，不瞬移）。 */
export const ATTRACTOR_POS_LERP = 0.08;
/** 脉冲指数衰减率（/s）：约 1.5s 内回到基础强度。 */
const PULSE_DECAY_RATE = 2.2;
/** 激活 / 失活强度淡入淡出率（/s）。 */
const ACTIVE_FADE_RATE = 4;

/**
 * 近距阻尼：d < NEAR 时 smoothstep 从 0 升到 1——
 * 距离为 0 时拉力为 0（粒子停在吸引子附近的轨道上，不穿入中心）。
 */
export function nearDamping(distance: number): number {
  const t = Math.min(1, Math.max(0, distance / ATTRACTOR_NEAR_RADIUS));
  return t * t * (3 - 2 * t);
}

/** 强度钳制到 [0, ATTRACTOR_MAX_STRENGTH]；NaN 按 0 处理，±Infinity 自然钳到端点。 */
export function clampAttractorStrength(strength: number): number {
  if (Number.isNaN(strength)) return 0;
  return Math.min(ATTRACTOR_MAX_STRENGTH, Math.max(0, strength));
}

/** 透视相机视口参数（反投影用；相机近似直视 -z，rig 偏移量小可忽略倾斜）。 */
export interface PlaneView {
  readonly fovDeg: number;
  readonly aspect: number;
  readonly cameraZ: number;
  /** 粒子层深度平面（世界 z 坐标）。 */
  readonly planeZ: number;
  /** 相机 rig 当前原点偏移。 */
  readonly originX: number;
  readonly originY: number;
}

export interface WorldPoint {
  readonly x: number;
  readonly y: number;
  readonly z: number;
}

/** 指针 NDC([-1,1]) 反投影到粒子层深度平面，返回世界坐标。非法视口抛 RangeError。 */
export function pointerToPlane(ndcX: number, ndcY: number, view: PlaneView): WorldPoint {
  if (!(view.fovDeg > 0 && view.fovDeg < 180)) {
    throw new RangeError(`非法视场角: ${view.fovDeg}`);
  }
  if (!(view.aspect > 0) || !Number.isFinite(view.aspect)) {
    throw new RangeError(`非法宽高比: ${view.aspect}`);
  }
  const depth = view.cameraZ - view.planeZ;
  if (!(depth > 0)) {
    throw new RangeError(`相机必须位于粒子层平面之前: cameraZ=${view.cameraZ}, planeZ=${view.planeZ}`);
  }
  const halfH = Math.tan((view.fovDeg / 2) * (Math.PI / 180)) * depth;
  return {
    x: view.originX + ndcX * halfH * view.aspect,
    y: view.originY + ndcY * halfH,
    z: view.planeZ,
  };
}

/** 吸引子一帧状态（位置 + 强度），供 uniform 上传。 */
export interface AttractorState {
  readonly x: number;
  readonly y: number;
  readonly z: number;
  readonly strength: number;
}

export interface Attractor {
  /** 设置跟随目标（世界坐标）；非有限值抛 RangeError。 */
  setTarget(x: number, y: number, z: number): void;
  /** 指针是否在场：false 时强度淡出归零（纯流场）。 */
  setActive(on: boolean): void;
  /** 点击脉冲：强度瞬时抬升后指数衰减回基础值；入参钳制到 [0, MAX]。 */
  pulse(strength?: number): void;
  /** 推进一帧：位置 lerp 跟随 + 强度合成（基础 × 激活淡入 + 脉冲，钳制 MAX）。 */
  step(dt: number): AttractorState;
  getState(): AttractorState;
}

export function createAttractor(): Attractor {
  let target = { x: 0, y: 0, z: 0 };
  let pos = { x: 0, y: 0, z: 0 };
  let active = false;
  let activeFade = 0; // 0..1 激活淡入
  let impulse = 0; // 脉冲残余强度

  const compose = (): AttractorState => ({
    x: pos.x,
    y: pos.y,
    z: pos.z,
    strength: clampAttractorStrength(ATTRACTOR_BASE_STRENGTH * activeFade + impulse),
  });

  return {
    setTarget(x: number, y: number, z: number): void {
      if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) {
        throw new RangeError(`吸引子目标坐标非法: (${x}, ${y}, ${z})`);
      }
      target = { x, y, z };
    },

    setActive(on: boolean): void {
      active = on;
      if (on) activeFade = 1; // 指针出现：基础强度即到位（空间位置仍 lerp 平滑跟随）
    },

    pulse(strength: number = ATTRACTOR_PULSE_STRENGTH): void {
      impulse = clampAttractorStrength(strength);
    },

    step(dt: number): AttractorState {
      const step = Math.min(0.1, Math.max(0, dt));
      pos.x += (target.x - pos.x) * ATTRACTOR_POS_LERP;
      pos.y += (target.y - pos.y) * ATTRACTOR_POS_LERP;
      pos.z += (target.z - pos.z) * ATTRACTOR_POS_LERP;
      activeFade = Math.min(1, Math.max(0, activeFade + (active ? 1 : -1) * ACTIVE_FADE_RATE * step));
      impulse *= Math.exp(-PULSE_DECAY_RATE * step);
      if (impulse < 1e-4) impulse = 0;
      return compose();
    },

    getState(): AttractorState {
      return compose();
    },
  };
}

/**
 * vertex shader 内联 chunk：近距阻尼 + 远距衰减 + 位移硬封顶。
 * 常量与 TS 侧单一事实源（模板注入，禁止双写漂移）。
 */
export const ATTRACTOR_GLSL = /* glsl */ `
  vec3 omniAttractOffset(vec3 pos, vec3 attractor, float strength) {
    vec3 toA = attractor - pos;
    float d = length(toA);
    // 近距强阻尼：d → 0 时拉力平滑归零，粒子不被吸穿
    float damp = smoothstep(0.0, ${ATTRACTOR_NEAR_RADIUS}, d);
    float pull = strength * damp * exp(-d * ${ATTRACTOR_FALLOFF});
    pull = min(pull, ${ATTRACTOR_REACH}); // 位移硬封顶，防爆粒
    return (toA / max(d, 1e-4)) * pull;
  }
`;
