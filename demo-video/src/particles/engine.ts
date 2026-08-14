/**
 * 粒子引擎（M46）：纯函数式、帧驱动、确定性 Canvas 2D 粒子内核。
 *
 * Remotion 渲染约束：帧在多个无头页面间并行/乱序 seek，
 * 因此粒子状态必须是「帧号的纯函数」——禁止增量模拟、
 * 禁止非种子随机与墙钟。每个粒子由 (seed, index) 派生
 * 固定参数组，行为函数（behaviors.ts）按 env.frame 闭式求值。
 *
 * 预算红线（用户硬性约束）：同屏 ≤300 粒子、环境漂移 ≤1.2 px/帧、
 * 内容色 ≤6、呼吸振幅/周期双约束防频闪、标题安全区粒子衰减为零。
 */

/* ── 预算常量（测试锁定，勿随意放宽） ── */
export const MAX_PARTICLES = 300; // 同屏粒子上限
export const SPEED_LIMIT = 1.2; // 环境漂移速度上限（px/帧）
export const CONNECTION_MAX_DIST = 140; // 粒子连线最大距离（px）
export const TWINKLE_AMPLITUDE = 0.08; // 呼吸振幅上限（防频闪）
export const TWINKLE_PERIOD_FRAMES = 54; // 呼吸周期（帧，≈1.8s@30fps）

/** Film Atelier 暗房调色板：琥珀为主锚点，青灰为对比，共 5 色（≤6） */
export const PARTICLE_PALETTE = {
  amber: "#d4a96a",
  amberWarm: "#e0bf8a",
  teal: "#6fa89e",
  tealDim: "#4d7a72",
  ember: "#b87d4b",
} as const;

export type PaletteKey = keyof typeof PARTICLE_PALETTE;

/** 景深层：0=远（大而柔暗，散景） 1=中 2=近（小而亮，带内核） */
export const LAYER_OPACITY = [0.3, 0.55, 0.85] as const;
export const LAYER_SIZE = [1.0, 1.6, 2.6] as const;

/** mulberry32 种子 RNG：同种子同序列，跨渲染进程逐位一致 */
export const mulberry32 = (seed: number): (() => number) => {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
};

export const clamp01 = (v: number): number => Math.min(1, Math.max(0, v));
export const clamp = (v: number, lo: number, hi: number): number =>
  Math.min(hi, Math.max(lo, v));

/** ease-out cubic：快速起步、柔和对位，物理感缓动 */
export const easeOutCubic = (t: number): number => 1 - Math.pow(1 - t, 3);
/** ease-out quad：更轻的缓出（弥散用） */
export const easeOutQuad = (t: number): number => 1 - (1 - t) * (1 - t);

/** 单粒子确定性参数组：从 (seed, index) 一次性派生，调用顺序固定 */
export interface ParticleSeed {
  angle: number; // 初始方位角
  radius: number; // 归一半径/距离系数 [0,1)
  size: number; // 基础尺寸
  speed: number; // 个性化速度系数 [0.6,1.0)
  phase: number; // 呼吸相位
  delay: number; // 入场延迟（帧）
  colorKey: PaletteKey;
  layer: 0 | 1 | 2;
  lane: number; // 轨道/涟漪环带序号 [0,5)
  star: boolean; // 明星粒子（十字光斑，近层少量）
}

export const seedParticle = (seed: number, index: number): ParticleSeed => {
  const rng = mulberry32(seed * 7919 + index * 104729);
  const layerRoll = rng();
  const layer: 0 | 1 | 2 = layerRoll < 0.45 ? 0 : layerRoll < 0.8 ? 1 : 2;
  const colorRoll = rng();
  const colorKey: PaletteKey =
    colorRoll < 0.55
      ? "amber"
      : colorRoll < 0.75
        ? "teal"
        : colorRoll < 0.87
          ? "amberWarm"
          : colorRoll < 0.95
            ? "tealDim"
            : "ember";
  const angle = rng() * Math.PI * 2;
  const radius = rng();
  const size = 0.8 + rng() * 2.4;
  const speed = 0.6 + rng() * 0.4;
  const phase = rng() * Math.PI * 2;
  const delay = rng() * 36;
  const lane = Math.floor(rng() * 5);
  const star = layer === 2 && rng() < 0.1;
  return { angle, radius, size, speed, phase, delay, colorKey, layer, lane, star };
};

/** 粒子单帧状态（行为函数输出） */
export interface ParticleState {
  x: number;
  y: number;
  r: number; // 内核半径（px）
  opacity: number;
  colorKey: PaletteKey;
  layer: 0 | 1 | 2;
  star: boolean;
}

/** 文字安全区：圆心 + 清零半径 + 衰减过渡带 */
export interface SafeZone {
  x: number;
  y: number;
  radius: number; // 此距离内粒子 opacity → 0
  falloff: number; // 从 radius 到 radius+falloff 线性恢复
}

/** 行为函数执行环境（由 ParticleCanvas 按帧构造） */
export interface BehaviorEnv {
  frame: number; // 场景内本地帧（≥0）
  fps: number;
  width: number;
  height: number;
  cx: number; // 焦点（px）
  cy: number;
  progress: number; // 场景进度 [0,1]
  safeZones: SafeZone[];
}

/** 文字安全区衰减：所有区域取最小系数 */
export const safeZoneFade = (
  x: number,
  y: number,
  zones: SafeZone[],
): number => {
  let f = 1;
  for (const z of zones) {
    const d = Math.hypot(x - z.x, y - z.y);
    f = Math.min(f, clamp01((d - z.radius) / z.falloff));
  }
  return f;
};

/**
 * 慢呼吸系数：输出 ∈ [1-2·amplitude, 1]，周期 ≥ TWINKLE_PERIOD_FRAMES。
 * 振幅与周期双约束 —— 杜绝频闪（光敏红线）。
 */
export const breath = (
  frame: number,
  phase: number,
  amplitude: number = TWINKLE_AMPLITUDE,
  period: number = TWINKLE_PERIOD_FRAMES,
): number =>
  1 - amplitude + amplitude * Math.sin((frame / period) * Math.PI * 2 + phase);

/** 行为函数签名：纯函数，同 (seed, env) 必同输出 */
export type BehaviorFn = (p: ParticleSeed, env: BehaviorEnv) => ParticleState;

/** 逐帧计算全部粒子状态：f(frame)，无任何跨帧可变状态 */
export const computeParticles = (
  fn: BehaviorFn,
  env: BehaviorEnv,
  count: number,
  seed: number,
): ParticleState[] => {
  const n = Math.min(count, MAX_PARTICLES);
  const states: ParticleState[] = new Array(n);
  for (let i = 0; i < n; i++) {
    states[i] = fn(seedParticle(seed, i), env);
  }
  return states;
};

/**
 * 精灵缓存：每色预渲染一张径向渐变光晕到离屏 canvas，
 * 逐帧 drawImage 取代逐粒子 createRadialGradient 填充（快一个数量级）。
 */
export class SpriteCache {
  private sprites = new Map<PaletteKey, HTMLCanvasElement>();

  constructor(private size = 64) {}

  get(colorKey: PaletteKey): HTMLCanvasElement {
    let sprite = this.sprites.get(colorKey);
    if (sprite) return sprite;
    sprite = document.createElement("canvas");
    sprite.width = this.size;
    sprite.height = this.size;
    const ctx = sprite.getContext("2d");
    if (!ctx) return sprite;
    const half = this.size / 2;
    const color = PARTICLE_PALETTE[colorKey];
    const g = ctx.createRadialGradient(half, half, 0, half, half, half);
    g.addColorStop(0, color);
    g.addColorStop(0.32, `${color}a6`);
    g.addColorStop(0.68, `${color}2e`);
    g.addColorStop(1, `${color}00`);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, this.size, this.size);
    this.sprites.set(colorKey, sprite);
    return sprite;
  }
}

/** 景深层绘制参数：远层大而柔（散景），近层小而亮（带内核） */
const LAYER_HALO_SCALE = [4.2, 3.0, 2.2] as const;
const LAYER_CORE = [false, false, true] as const;

export interface DrawOptions {
  width: number;
  height: number;
  connections?: boolean; // 远/中层邻近连线（暗房星图感）
  connectionOpacity?: number;
}

/** 单帧绘制：clearRect → lighter 叠加 → 连线 → 三层精灵 → 明星光斑 */
export const drawParticles = (
  ctx: CanvasRenderingContext2D,
  states: ParticleState[],
  sprites: SpriteCache,
  options: DrawOptions,
): void => {
  const { width, height } = options;
  ctx.clearRect(0, 0, width, height);
  ctx.globalCompositeOperation = "lighter";

  // 连线层（最底）：仅远/中层、距离有界、线细而淡
  if (options.connections) {
    const maxOp = options.connectionOpacity ?? 0.16;
    ctx.lineWidth = 0.6;
    for (let i = 0; i < states.length; i++) {
      const a = states[i];
      if (a.layer > 1 || a.opacity < 0.05) continue;
      for (let j = i + 1; j < states.length; j++) {
        const b = states[j];
        if (b.layer > 1 || b.opacity < 0.05) continue;
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        if (d >= CONNECTION_MAX_DIST || d < 8) continue;
        const op =
          Math.min(a.opacity, b.opacity) *
          maxOp *
          (1 - d / CONNECTION_MAX_DIST);
        if (op < 0.008) continue;
        ctx.globalAlpha = op;
        ctx.strokeStyle = PARTICLE_PALETTE[a.colorKey];
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }
    }
  }

  // 粒子层：远 → 近顺序叠加
  for (let layer = 0; layer < 3; layer++) {
    const haloScale = LAYER_HALO_SCALE[layer];
    for (const p of states) {
      if (p.layer !== layer || p.opacity <= 0.004) continue;
      const halo = p.r * haloScale * 2;
      ctx.globalAlpha = p.opacity;
      ctx.drawImage(
        sprites.get(p.colorKey),
        p.x - halo / 2,
        p.y - halo / 2,
        halo,
        halo,
      );
      if (LAYER_CORE[layer]) {
        ctx.globalAlpha = Math.min(1, p.opacity * 1.15);
        ctx.fillStyle = PARTICLE_PALETTE[p.colorKey];
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
      }
      // 明星粒子十字光斑（仅近层、足够亮时）
      if (p.star && p.opacity > 0.3) {
        const flare = p.r * 4.5;
        ctx.globalAlpha = p.opacity * 0.32;
        ctx.strokeStyle = PARTICLE_PALETTE[p.colorKey];
        ctx.lineWidth = 0.8;
        ctx.beginPath();
        ctx.moveTo(p.x - flare, p.y);
        ctx.lineTo(p.x + flare, p.y);
        ctx.moveTo(p.x, p.y - flare);
        ctx.lineTo(p.x, p.y + flare);
        ctx.stroke();
      }
    }
  }

  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = "source-over";
};
