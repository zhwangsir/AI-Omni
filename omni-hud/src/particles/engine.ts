/**
 * 纯 TS 粒子引擎：与 canvas / DOM 完全解耦，构造注入画布尺寸与随机源，
 * step(dt) 推进一帧，getParticles() 返回当前粒子状态快照。
 * 这样设计是为了让引擎在 jsdom / node 里即可完整单测，不依赖 WebGL 或真实显示器。
 */
import {
  MAX_PARTICLES,
  MAX_SPEED,
  MIN_SPEED,
  PALETTE,
  clampParticleCount,
  validatePalette,
  validateParticleSpec,
} from "./constraints";

export interface ParticleSpec {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  color: string;
}

export interface ParticleEngineOptions {
  width: number;
  height: number;
  count: number;
  /** 尊重 prefers-reduced-motion：开启后 step 不移动粒子。 */
  reducedMotion?: boolean;
  /** 随机源注入，默认 Math.random，测试可注入确定性序列。 */
  random?: () => number;
  /** 直接注入初始粒子（会逐个过硬校验）；缺省时自动按约束生成。 */
  particles?: readonly ParticleSpec[];
  /** 自定义调色板（M4.4 主题换肤），1..MAX_COLORS 色；缺省用全局 PALETTE。 */
  palette?: readonly string[];
}

/** 单帧 dt 上限：防止后台标签页恢复时粒子瞬移爆炸。 */
const MAX_DT = 4;
const MIN_RADIUS = 0.6;
const RADIUS_SPAN = 1.2;

/**
 * 聚集模式（M4.4）：向吸引目标的转向加速度。比例增益小、单帧加速度有上限、
 * 速度始终钳制到 MAX_SPEED——聚集是"缓缓靠拢"的意象，不是粒子爆炸。
 */
const ATTRACT_GAIN = 0.02;
const ATTRACT_MAX_ACCEL = 0.09;
/** 目标附近的阻尼半径：进入后强阻尼让粒子悬停而不是绕目标乱转。 */
const ATTRACT_SETTLE_RADIUS = 48;
const ATTRACT_DAMPING_FAR = 0.99;
const ATTRACT_DAMPING_NEAR = 0.9;

export interface AttractorPoint {
  readonly x: number;
  readonly y: number;
}

export class ParticleEngine {
  private width: number;
  private height: number;
  private reducedMotion: boolean;
  private readonly random: () => number;
  private readonly palette: readonly string[];
  private particles: ParticleSpec[];
  private attractor: AttractorPoint | null = null;

  constructor(options: ParticleEngineOptions) {
    if (!Number.isFinite(options.width) || options.width <= 0) {
      throw new RangeError(`画布宽度非法: ${options.width}`);
    }
    if (!Number.isFinite(options.height) || options.height <= 0) {
      throw new RangeError(`画布高度非法: ${options.height}`);
    }
    this.width = options.width;
    this.height = options.height;
    this.random = options.random ?? Math.random;
    this.reducedMotion = options.reducedMotion ?? false;
    this.palette = options.palette ?? PALETTE;
    validatePalette(this.palette);
    this.particles = options.particles
      ? this.adopt(options.particles)
      : this.spawn(clampParticleCount(options.count));
  }

  /** 接收外部注入的粒子：数量与逐粒子约束都过硬校验。 */
  private adopt(specs: readonly ParticleSpec[]): ParticleSpec[] {
    if (specs.length > MAX_PARTICLES) {
      throw new RangeError(`注入粒子数 ${specs.length} 超过上限 ${MAX_PARTICLES}`);
    }
    return specs.map((spec) => {
      validateParticleSpec(spec, this.palette);
      return { ...spec };
    });
  }

  /** 按约束自动生成粒子：位置铺满画布，速率 ∈ [MIN_SPEED, MAX_SPEED]，颜色取自调色板。 */
  private spawn(count: number): ParticleSpec[] {
    const list: ParticleSpec[] = [];
    for (let i = 0; i < count; i++) {
      const angle = this.random() * Math.PI * 2;
      const speed = MIN_SPEED + this.random() * (MAX_SPEED - MIN_SPEED);
      list.push({
        x: this.random() * this.width,
        y: this.random() * this.height,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        radius: MIN_RADIUS + this.random() * RADIUS_SPAN,
        color: this.palette[Math.floor(this.random() * this.palette.length)] ?? this.palette[0]!,
      });
    }
    return list;
  }

  /**
   * 设置 / 清除聚集目标（M4.4）：鼠标悬停交互元素或点击内容区时，
   * 粒子向该点缓缓聚集；传 null 释放回自由漂移。非法坐标抛 RangeError。
   */
  setAttractor(point: AttractorPoint | null): void {
    if (point !== null && (!Number.isFinite(point.x) || !Number.isFinite(point.y))) {
      throw new RangeError(`聚集目标坐标非法: (${point.x}, ${point.y})`);
    }
    this.attractor = point === null ? null : { x: point.x, y: point.y };
  }

  /**
   * 推进一帧。dt 以"帧"为单位（1 ≈ 16.7ms）；dt ≤ 0 或非法时忽略；
   * dt 超过 MAX_DT 时钳制，避免长时间挂起后粒子瞬移。
   * 聚集目标存在时先施加转向加速度（速度仍钳制到 MAX_SPEED 硬约束）。
   */
  step(dt: number): void {
    if (!Number.isFinite(dt) || dt <= 0) return;
    if (this.reducedMotion) return;
    const frame = Math.min(dt, MAX_DT);
    for (const p of this.particles) {
      if (this.attractor) this.steerToward(p, this.attractor, frame);
      p.x += p.vx * frame;
      p.y += p.vy * frame;
      // 出界从对侧回绕：粒子缓慢漂移穿过屏幕，而不是堆积或反弹。
      if (p.x < -p.radius) p.x = this.width + p.radius;
      else if (p.x > this.width + p.radius) p.x = -p.radius;
      if (p.y < -p.radius) p.y = this.height + p.radius;
      else if (p.y > this.height + p.radius) p.y = -p.radius;
    }
  }

  /**
   * 向目标点转向：比例增益随距离增大（远快近慢），单帧加速度封顶，
   * 目标附近强阻尼悬停；最终速率永远钳制在 MAX_SPEED 内。
   */
  private steerToward(p: ParticleSpec, target: AttractorPoint, frame: number): void {
    const dx = target.x - p.x;
    const dy = target.y - p.y;
    const dist = Math.hypot(dx, dy);
    if (dist < 1e-6) return;
    const accel = Math.min(ATTRACT_GAIN * dist, ATTRACT_MAX_ACCEL);
    p.vx += (dx / dist) * accel * frame;
    p.vy += (dy / dist) * accel * frame;
    const damping = dist < ATTRACT_SETTLE_RADIUS ? ATTRACT_DAMPING_NEAR : ATTRACT_DAMPING_FAR;
    p.vx *= damping;
    p.vy *= damping;
    const speed = Math.hypot(p.vx, p.vy);
    if (speed > MAX_SPEED) {
      p.vx = (p.vx / speed) * MAX_SPEED;
      p.vy = (p.vy / speed) * MAX_SPEED;
    }
  }

  /** 当前粒子状态快照（副本，外部修改不会污染引擎）。 */
  getParticles(): ParticleSpec[] {
    return this.particles.map((p) => ({ ...p }));
  }

  setReducedMotion(flag: boolean): void {
    this.reducedMotion = flag;
  }

  resize(width: number, height: number): void {
    if (!Number.isFinite(width) || width <= 0) {
      throw new RangeError(`画布宽度非法: ${width}`);
    }
    if (!Number.isFinite(height) || height <= 0) {
      throw new RangeError(`画布高度非法: ${height}`);
    }
    this.width = width;
    this.height = height;
  }
}
