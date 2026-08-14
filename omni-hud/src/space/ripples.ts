/**
 * ripples 3D 水波纹队列（M5.3）：点击 → ripple {origin, t0} 入队，
 * vertex shader 径向位移（慢速大范围扩散，波前高斯轻推、内侧回落、随生命周期衰减）。
 * 审美红线硬编码：生命周期 ≥1200ms（慢速）、扩散半径覆盖全粒子体积（大范围）、
 * 位移幅度 ≤0.8 世界单位（轻推非爆散）、并发 ≤4（不叠加糊屏）。
 * 纯逻辑模块：常量 / 波形采样 / 队列 / GLSL chunk 单一事实源，不依赖 three，可独立单测。
 */

/** 并发上限：多于 4 条同屏波纹会糊成一片（克制红线）。 */
export const RIPPLE_MAX_CONCURRENT = 4;
/** 生命周期下限（ms）：低于此值的波纹扩散过快，违反"慢速"红线。 */
export const RIPPLE_MIN_DURATION_MS = 1200;
/** 默认生命周期（ms）：~2s，慢速扩散至全场后淡出。 */
export const RIPPLE_DEFAULT_DURATION_MS = 2000;
/** 扩散半径（世界单位）：覆盖粒子体积最大对角半径（√(7.5²+4.8²+5²)≈10.2）并留出边缘余量。 */
export const RIPPLE_TRAVEL_RADIUS = 11;
/** 单片位移上限（世界单位）：高斯波前峰值，轻推而非爆散。 */
export const RIPPLE_MAX_PUSH = 0.55;
/** 波前高斯带宽 σ（世界单位）：窄带波前，内侧快速回落不拖尾。 */
export const RIPPLE_FRONT_SIGMA = 0.5;

/** 波形采样结果。 */
export interface RippleWaveSample {
  /** 波前当前半径（世界单位，随时长线性匀速推进）。 */
  readonly front: number;
  /** 该距离处的径向位移量（世界单位，≥0，沿远离原点方向轻推）。 */
  readonly displacement: number;
  /** 生命周期衰减系数 [0, 1]：1 = 新生，0 = 寿终。 */
  readonly fade: number;
}

/**
 * 采样 age 时刻、distance 距离处的波纹位移。
 * 波前 front = RADIUS × age/duration 匀速推进；位移 = MAX_PUSH × fade × 高斯带。
 * distance/age 为负、duration 非正或任意入参非有限值 → RangeError。
 */
export function sampleRippleWave(distance: number, age: number, duration: number): RippleWaveSample {
  if (!Number.isFinite(distance) || distance < 0) {
    throw new RangeError(`非法距离: ${distance}`);
  }
  if (!Number.isFinite(age) || age < 0) {
    throw new RangeError(`非法波纹年龄: ${age}`);
  }
  if (!Number.isFinite(duration) || duration <= 0) {
    throw new RangeError(`非法生命周期: ${duration}`);
  }
  const t = age / duration;
  const front = RIPPLE_TRAVEL_RADIUS * t;
  const fade = Math.max(0, 1 - t);
  const band = (distance - front) / RIPPLE_FRONT_SIGMA;
  const displacement = fade === 0 ? 0 : RIPPLE_MAX_PUSH * fade * Math.exp(-0.5 * band * band);
  return { front, displacement, fade };
}

/** 一条在册波纹（毫秒制时间，writeUniforms 时转秒上传）。 */
export interface Ripple {
  readonly x: number;
  readonly y: number;
  readonly z: number;
  /** 入队时刻（ms，宿主时钟——performance.now 同基）。 */
  readonly startedAt: number;
  /** 生命周期（ms，缺省 RIPPLE_DEFAULT_DURATION_MS，≥ MIN 硬校验）。 */
  readonly durationMs?: number;
}

export interface RippleQueue {
  /** 入队：并发满返回 false（不挤掉旧波纹）；非法入参抛 RangeError。 */
  add(ripple: Ripple): boolean;
  /** 清理 now 时刻已过期的波纹。 */
  prune(now: number): void;
  size(): number;
  /**
   * 写入 uniform 数组：origins = vec3 × MAX，times = vec2 × MAX
   * （x = 入队时刻秒，y = 生命周期秒；空闲槽位生命周期写 0，shader 跳过）。
   * 顺手按 now 清理过期槽位；数组长度不匹配抛 RangeError。
   */
  writeUniforms(origins: Float32Array, times: Float32Array, now: number): void;
}

interface RippleEntry {
  readonly x: number;
  readonly y: number;
  readonly z: number;
  readonly startedAt: number;
  readonly durationMs: number;
}

export function createRippleQueue(): RippleQueue {
  let entries: RippleEntry[] = [];

  const expired = (entry: RippleEntry, now: number): boolean =>
    now >= entry.startedAt + entry.durationMs;

  const prune = (now: number): void => {
    entries = entries.filter((entry) => !expired(entry, now));
  };

  return {
    add(ripple: Ripple): boolean {
      const { x, y, z, startedAt } = ripple;
      if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) {
        throw new RangeError(`非法波纹原点: (${x}, ${y}, ${z})`);
      }
      if (!Number.isFinite(startedAt)) {
        throw new RangeError(`非法入队时刻: ${startedAt}`);
      }
      const durationMs = ripple.durationMs ?? RIPPLE_DEFAULT_DURATION_MS;
      if (!Number.isFinite(durationMs) || durationMs < RIPPLE_MIN_DURATION_MS) {
        throw new RangeError(
          `波纹生命周期 ${durationMs}ms 低于慢速下限 ${RIPPLE_MIN_DURATION_MS}ms`,
        );
      }
      prune(startedAt); // 以新波纹时刻为基准顺手清过期，腾槽位
      if (entries.length >= RIPPLE_MAX_CONCURRENT) return false;
      entries.push({ x, y, z, startedAt, durationMs });
      return true;
    },

    prune,

    size(): number {
      return entries.length;
    },

    writeUniforms(origins: Float32Array, times: Float32Array, now: number): void {
      if (
        origins.length !== RIPPLE_MAX_CONCURRENT * 3 ||
        times.length !== RIPPLE_MAX_CONCURRENT * 2
      ) {
        throw new RangeError(
          `uniform 数组长度必须为 ${RIPPLE_MAX_CONCURRENT * 3}/${RIPPLE_MAX_CONCURRENT * 2}: ` +
            `${origins.length}/${times.length}`,
        );
      }
      prune(now);
      for (let i = 0; i < RIPPLE_MAX_CONCURRENT; i++) {
        const entry = entries[i];
        if (entry) {
          origins[i * 3] = entry.x;
          origins[i * 3 + 1] = entry.y;
          origins[i * 3 + 2] = entry.z;
          times[i * 2] = entry.startedAt / 1000;
          times[i * 2 + 1] = entry.durationMs / 1000;
        } else {
          origins[i * 3] = 0;
          origins[i * 3 + 1] = 0;
          origins[i * 3 + 2] = 0;
          times[i * 2] = 0;
          times[i * 2 + 1] = 0; // 生命周期 0 = 空闲槽位，shader 跳过
        }
      }
    },
  };
}

/** GLSL 浮点字面量：整数补 .0（WebGL1 GLSL ES 1.0 不允许 int/float 混算）。 */
const f = (n: number): string => (Number.isInteger(n) ? `${n}.0` : String(n));

/**
 * vertex shader 内联 chunk：径向高斯波前轻推（沿远离原点方向），
 * 内侧经高斯带自然回落、随生命周期线性衰减；常量与 TS 侧单一事实源（模板注入）。
 */
export const RIPPLE_GLSL = /* glsl */ `
  uniform vec3 uRippleOrigins[${RIPPLE_MAX_CONCURRENT}];
  uniform vec2 uRippleTimes[${RIPPLE_MAX_CONCURRENT}]; // x: 入队时刻(秒), y: 生命周期(秒, 0 = 空闲)
  uniform float uNowSec;

  vec3 omniRippleOffset(vec3 pos) {
    vec3 offset = vec3(0.0);
    for (int i = 0; i < ${RIPPLE_MAX_CONCURRENT}; i++) {
      float duration = uRippleTimes[i].y;
      if (duration <= 0.0) continue;
      float age = uNowSec - uRippleTimes[i].x;
      if (age < 0.0 || age >= duration) continue;
      float front = ${f(RIPPLE_TRAVEL_RADIUS)} * (age / duration);
      vec3 fromOrigin = pos - uRippleOrigins[i];
      float dist = length(fromOrigin);
      float fade = 1.0 - age / duration;
      float band = (dist - front) / ${f(RIPPLE_FRONT_SIGMA)};
      float push = ${f(RIPPLE_MAX_PUSH)} * fade * exp(-0.5 * band * band);
      offset += (fromOrigin / max(dist, 1e-4)) * push;
    }
    return offset;
  }
`;
