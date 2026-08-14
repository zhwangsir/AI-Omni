/**
 * 粒子行为全集（M46）：五种闭式行为，全部是 (seed, env) 的纯函数。
 *
 * - nebula   环境星云：慢速漂移 + 边缘回绕 + 呼吸（背景氛围层）
 * - converge 汇聚：从画外螺旋汇聚到焦点，easeOutCubic + 末段 overshoot，聚后缓慢自转
 * - orbit    轨道球：多条倾角轨道绕焦点公转，深度投影明暗（outro 主视觉）
 * - ripple   涟漪：环带自中心向外扩散（错峰 lane），正弦包络生灭（过场用）
 * - scatter  弥散：柔和离心漂移 + 淡出（缓出曲线，非爆炸 —— 用户红线）
 *
 * 所有行为共享引擎约束：速度/振幅/安全区/呼吸，见 engine.ts。
 */

import {
  LAYER_OPACITY,
  LAYER_SIZE,
  SPEED_LIMIT,
  breath,
  clamp,
  clamp01,
  easeOutCubic,
  easeOutQuad,
  safeZoneFade,
} from "./engine";
import type { BehaviorFn, ParticleSeed, ParticleState } from "./engine";

/** 焦点构图：intro 汇聚球位于画面右上方（左下留标题安全区） */
const ELLIPSE_Y = 0.78; // 垂直压扁系数（椭圆构图）

const baseState = (p: ParticleSeed, x: number, y: number): ParticleState => ({
  x,
  y,
  r: p.size * LAYER_SIZE[p.layer] * (p.star ? 1.9 : 1),
  opacity: 0,
  colorKey: p.colorKey,
  layer: p.layer,
  star: p.star,
});

/** 边缘回绕：飘出边界后从对侧回场，避免凭空消失 */
const wrap = (v: number, lo: number, hi: number): number => {
  const span = hi - lo;
  return ((((v - lo) % span) + span) % span) + lo;
};

/**
 * 环境星云：全场慢漂背景层。
 * 漂移速度显式钳制在 ±SPEED_LIMIT（px/帧）内 —— 防高频抖动的硬性约束。
 */
export const nebula: BehaviorFn = (p, env) => {
  const vx = clamp(Math.cos(p.angle) * 0.18 * p.speed, -SPEED_LIMIT, SPEED_LIMIT);
  const vy = clamp(Math.sin(p.angle) * 0.12 * p.speed, -SPEED_LIMIT, SPEED_LIMIT);
  const range = Math.max(env.width, env.height) * 0.6;
  const homeX = env.cx + Math.cos(p.angle * 3 + p.lane * 1.3) * p.radius * range;
  const homeY =
    env.cy + Math.sin(p.angle * 3 + p.lane * 1.3) * p.radius * range * 0.62;
  const x = wrap(homeX + vx * env.frame, -80, env.width + 80);
  const y = wrap(homeY + vy * env.frame, -60, env.height + 60);

  const s = baseState(p, x, y);
  // 尺寸呼吸（慢，振幅 15%）
  s.r *= 1 + 0.15 * Math.sin(env.frame / 70 + p.phase);
  // 边缘淡入淡出（回绕接缝不可见）
  const edge = Math.min(x, env.width - x, y, env.height - y);
  const edgeFade = clamp01(edge / 90);
  s.opacity =
    LAYER_OPACITY[p.layer] *
    breath(env.frame, p.phase) *
    edgeFade *
    safeZoneFade(x, y, env.safeZones) *
    0.8;
  return s;
};

/**
 * 汇聚：粒子从画外螺旋收拢到焦点成球。
 * easeOutCubic 缓动 + 末段 5% overshoot 回落（物理惯性）；
 * 汇聚完成后球体缓慢自转（非静止死球）。
 */
export const converge: BehaviorFn = (p, env) => {
  const rawP = clamp01((env.frame - p.delay) / 72);
  const e = easeOutCubic(rawP);
  const overshoot =
    rawP > 0.92 ? Math.sin(((rawP - 0.92) / 0.08) * Math.PI) * 0.05 : 0;

  const layerStartScale = p.layer === 0 ? 1.05 : p.layer === 1 ? 0.9 : 0.75;
  const startR =
    (0.55 + p.radius * 0.5) *
    Math.max(env.width, env.height) *
    layerStartScale;
  const endR = 16 + p.radius * 150 + p.lane * 12;
  const breatheOffset = Math.sin(env.frame / 28 + p.phase) * 2.5 * e;
  const r = startR + (endR - startR) * (e + overshoot) + breatheOffset;

  // 螺旋汇聚：方位角随进度扭转；汇聚完成后球体缓慢自转
  const swirl = (p.lane % 2 === 0 ? 1 : -1) * e * 0.9;
  const settledSpin = rawP >= 1 ? (env.frame - p.delay - 72) * 0.004 : 0;
  const angle = p.angle + swirl + settledSpin;

  const x = env.cx + Math.cos(angle) * r;
  const y = env.cy + Math.sin(angle) * r * ELLIPSE_Y;

  const s = baseState(p, x, y);
  const appear = clamp01((env.frame - p.delay) / 18);
  s.opacity =
    LAYER_OPACITY[p.layer] *
    appear *
    breath(env.frame, p.phase) *
    safeZoneFade(x, y, env.safeZones);
  return s;
};

/**
 * 轨道球：5 条不同倾角（tilt）的轨道环绕焦点公转，构成球面层次。
 * 绕 X 轴旋转投影：深度 z 驱动明暗/大小变化（前亮后暗）。
 */
export const orbit: BehaviorFn = (p, env) => {
  const orbitR = 90 + p.lane * 46 + p.radius * 60;
  const tilt = (p.lane / 5) * Math.PI - Math.PI / 2; // 轨道倾角 ∈ [-π/2, π/2)
  const dir = p.lane % 2 === 0 ? 1 : -1;
  const period = 260 + p.lane * 60; // 公转周期（帧，8.7s–16.7s）
  const theta = p.angle + dir * ((env.frame * 2 * Math.PI) / period);

  // 轨道面内坐标 → 绕 X 轴倾角旋转 → 正交投影
  const ox = Math.cos(theta) * orbitR;
  const oz = Math.sin(theta) * orbitR;
  const py = -oz * Math.sin(tilt);
  const pz = oz * Math.cos(tilt);

  // 入场：从略大半径收缩入轨（前 50 帧）
  const enter = easeOutCubic(clamp01((env.frame - p.delay) / 50));
  const rr = orbitR * (1.35 - 0.35 * enter);
  const scale = rr / orbitR;

  const x = env.cx + ox * scale;
  const y = env.cy + py * scale * ELLIPSE_Y;

  // 深度明暗：前方（pz>0）更亮更大
  const depth = 0.45 + 0.55 * ((pz / orbitR + 1) / 2);

  const s = baseState(p, x, y);
  s.r *= 0.75 + 0.5 * depth;
  s.opacity =
    LAYER_OPACITY[p.layer] *
    depth *
    enter *
    breath(env.frame, p.phase) *
    safeZoneFade(x, y, env.safeZones);
  return s;
};

/**
 * 涟漪：环带自中心向外缓慢扩散（过场显影）。
 * 粒子锚定方位角，半径按 lane 错峰推进；正弦包络 0→1→0，
 * 到 maxR 自然消隐 —— 扩散自中心向外，范围大、速度慢。
 */
export const ripple: BehaviorFn = (p, env) => {
  const maxR = Math.hypot(env.width, env.height) * 0.62; // 大范围覆盖全场
  // 每条环带错峰出发（lane 相位），带内粒子轻微延迟差
  const phase = env.progress * 1.4 - p.lane * 0.16 - p.delay * 0.004;
  const pr = clamp01(phase);
  const r = easeOutQuad(pr) * maxR;

  // 环带厚度：同 lane 粒子沿径向微散开，避免细线感
  const bandR = r + (p.radius - 0.5) * 56;
  const angle = p.angle + Math.sin(env.frame / 90 + p.phase) * 0.02; // 极慢角漂移

  const x = env.cx + Math.cos(angle) * bandR;
  const y = env.cy + Math.sin(angle) * bandR * ELLIPSE_Y;

  const s = baseState(p, x, y);
  // 生灭包络：出发即亮、抵边即隐
  const envelope = Math.sin(pr * Math.PI);
  s.opacity =
    LAYER_OPACITY[p.layer] *
    envelope *
    0.6 *
    breath(env.frame, p.phase) *
    safeZoneFade(x, y, env.safeZones);
  return s;
};

/**
 * 弥散：粒子自焦点附近柔和离心漂移并淡出（场景收束用）。
 * easeOutCubic 缓出 + 线性淡出 —— 克制弥散，禁止爆炸感。
 */
export const scatter: BehaviorFn = (p, env) => {
  const pr = easeOutCubic(clamp01((env.frame - p.delay * 0.5) / 90));
  const startR = 60 + p.radius * 140 + p.lane * 20;
  const r = startR + pr * (300 + p.lane * 110);
  const angle = p.angle + pr * 0.35 * (p.lane % 2 === 0 ? 1 : -1);

  const x = env.cx + Math.cos(angle) * r;
  const y = env.cy + Math.sin(angle) * r * ELLIPSE_Y;

  const s = baseState(p, x, y);
  s.opacity =
    LAYER_OPACITY[p.layer] *
    (1 - pr) *
    breath(env.frame, p.phase) *
    safeZoneFade(x, y, env.safeZones);
  return s;
};

/** 行为注册表：ParticleCanvas 按名查找 */
export const BEHAVIORS = {
  nebula,
  converge,
  orbit,
  ripple,
  scatter,
} as const;

export type BehaviorName = keyof typeof BEHAVIORS;
