/**
 * bpm 节拍检测算法（M21.2，D21.1 能量峰值法）：
 *
 * 算法流程（纯函数链）：
 * 1. ``detectPeaks``：低频能量序列（逐帧 bass 值）→ 候选拍点索引
 *    （能量超自适应阈值 + 局部最大 + 最小间隔退火）；
 * 2. ``clusterBeats``：拍点时间戳 → 间隔（IOI）聚类，丢弃离群间隔；
 * 3. ``estimateBpm``：取间隔中位数 → BPM，置信度 = 有效拍点占比 × 间隔一致性。
 *
 * D21.1 决策：能量峰值法简单可靠，复杂算法（自相关 / onset detection）后续优化。
 *
 * 纯逻辑模块：输入输出全是 number[] / 时间戳序列，不依赖 WebAudio / DOM，
 * 可在 vitest 中以预构造能量序列断言（非镜像实现）。
 */

/** BPM 检测结果。 */
export interface BpmResult {
  /** 估算 BPM（beats per minute），无效时为 0。 */
  readonly bpm: number;
  /** 置信度 [0,1]：拍点密度 × 间隔一致性。 */
  readonly confidence: number;
  /** 拍点时间戳数组（秒）。 */
  readonly beatTimes: readonly number[];
}

/** 空结果：能量不足 / 拍点稀疏时返回。 */
export const ZERO_BPM_RESULT: BpmResult = {
  bpm: 0,
  confidence: 0,
  beatTimes: [],
};

/** 默认 BPM 检测参数。 */
export interface BpmDetectOptions {
  /** 能量阈值倍率：相对全局均值的倍数（默认 1.4，即超过均值 40%）。 */
  readonly thresholdRatio?: number;
  /** 绝对能量下限：低于此值不视为拍点（默认 0.15）。 */
  readonly minEnergy?: number;
  /** 最小拍点间隔（秒，默认 0.25s = 240 BPM 上限）。 */
  readonly minInterval?: number;
  /** 最大拍点间隔（秒，默认 2.0s = 30 BPM 下限）。 */
  readonly maxInterval?: number;
  /** 局部最大窗口大小（帧数，默认 5）。 */
  readonly localWindow?: number;
}

export const DEFAULT_BPM_OPTIONS: Required<BpmDetectOptions> = {
  thresholdRatio: 1.4,
  minEnergy: 0.15,
  minInterval: 0.25,
  maxInterval: 2.0,
  localWindow: 5,
};

/**
 * 1. 能量峰值检测：从逐帧低频能量序列中提取候选拍点索引。
 *
 * 判定规则（同时满足）：
 * - 能量 > max(全局均值 × thresholdRatio, minEnergy)；
 * - 在 localWindow 邻域内为局部最大；
 * - 距上一个拍点 ≥ minInterval（秒）。
 *
 * timestamps 为每帧对应的时间戳（秒，等间隔或不等间隔均可）；
 * energies 为对应的低频能量值（[0,1]）。两者长度必须一致。
 */
export function detectPeaks(
  energies: readonly number[],
  timestamps: readonly number[],
  options: BpmDetectOptions = {},
): number[] {
  if (energies.length !== timestamps.length) {
    throw new RangeError(`energies 与 timestamps 长度不一致: ${energies.length} vs ${timestamps.length}`);
  }
  if (energies.length === 0) return [];
  const opts = { ...DEFAULT_BPM_OPTIONS, ...options };
  const n = energies.length;
  // 全局均值（过滤 NaN / 非有限值）
  let sum = 0;
  let count = 0;
  for (let i = 0; i < n; i++) {
    const v = energies[i]!;
    if (Number.isFinite(v)) {
      sum += v;
      count++;
    }
  }
  if (count === 0) return [];
  const mean = sum / count;
  const threshold = Math.max(mean * opts.thresholdRatio, opts.minEnergy);

  const peaks: number[] = [];
  let lastPeakTs = Number.NEGATIVE_INFINITY;
  const halfWin = Math.floor(opts.localWindow / 2);
  for (let i = 0; i < n; i++) {
    const e = energies[i]!;
    if (!Number.isFinite(e) || e < threshold) continue;
    // 局部最大检查：[i-halfWin, i+halfWin] 范围内 e 最大
    let isLocalMax = true;
    const start = Math.max(0, i - halfWin);
    const end = Math.min(n - 1, i + halfWin);
    for (let j = start; j <= end; j++) {
      if (j === i) continue;
      const ej = energies[j]!;
      if (Number.isFinite(ej) && ej > e) {
        isLocalMax = false;
        break;
      }
    }
    if (!isLocalMax) continue;
    const ts = timestamps[i]!;
    if (!Number.isFinite(ts)) continue;
    // 最小间隔退火：距上一个拍点必须 ≥ minInterval
    if (ts - lastPeakTs < opts.minInterval) continue;
    peaks.push(i);
    lastPeakTs = ts;
  }
  return peaks;
}

/** 间隔（IOI, inter-onset interval）聚类结果。 */
export interface BeatCluster {
  /** 该聚类的代表间隔（秒，中位数）。 */
  readonly interval: number;
  /** 该聚类包含的间隔数量。 */
  readonly count: number;
}

/**
 * 2. 拍点间隔聚类：把 IOI 序列按相似性分组，丢弃离群间隔。
 *
 * 算法：相邻 IOI 差异 < tolerance（秒）归为同一聚类；保留 count 最大的聚类
 * 作为"主导节拍"。tolerance 默认 0.05s（即 50ms 容差，对应 ~5% BPM 抖动）。
 *
 * 返回所有聚类（按 count 降序），调用方可取 [0] 为主聚类。
 */
export function clusterBeats(
  beatTimes: readonly number[],
  tolerance: number = 0.05,
): BeatCluster[] {
  if (beatTimes.length < 2) return [];
  if (!Number.isFinite(tolerance) || tolerance <= 0) {
    throw new RangeError(`非法容差: ${tolerance}`);
  }
  // 计算 IOI 序列
  const iois: number[] = [];
  for (let i = 1; i < beatTimes.length; i++) {
    const ioi = beatTimes[i]! - beatTimes[i - 1]!;
    if (Number.isFinite(ioi) && ioi > 0) iois.push(ioi);
  }
  if (iois.length === 0) return [];

  // 排序后聚类：相邻 ioi 差异 < tolerance 归同组
  const sorted = [...iois].sort((a, b) => a - b);
  const clusters: BeatCluster[] = [];
  let currentInterval = sorted[0]!;
  let currentCount = 1;
  for (let i = 1; i < sorted.length; i++) {
    const ioi = sorted[i]!;
    if (ioi - currentInterval < tolerance) {
      currentCount++;
    } else {
      clusters.push({ interval: currentInterval, count: currentCount });
      currentInterval = ioi;
      currentCount = 1;
    }
  }
  clusters.push({ interval: currentInterval, count: currentCount });

  // 按 count 降序
  clusters.sort((a, b) => b.count - a.count);
  return clusters;
}

/**
 * 3. BPM 估算：从拍点时间戳推算 BPM 与置信度。
 *
 * 算法：
 * - 拍点 < 4 个：置信度低，返回 ZERO_BPM_RESULT；
 * - 主聚类间隔 → BPM = 60 / interval；
 * - 置信度 = 主聚类 count / 总拍点数（间隔一致性）。
 *
 * BPM 钳制到 [30, 240]（人耳可识别的音乐节拍范围），超界返回 0。
 */
export function estimateBpm(
  beatTimes: readonly number[],
  options: BpmDetectOptions = {},
): BpmResult {
  const opts = { ...DEFAULT_BPM_OPTIONS, ...options };
  if (beatTimes.length < 4) return { ...ZERO_BPM_RESULT, beatTimes };
  const clusters = clusterBeats(beatTimes);
  if (clusters.length === 0) return { ...ZERO_BPM_RESULT, beatTimes };
  const main = clusters[0]!;
  if (main.count < 2) return { ...ZERO_BPM_RESULT, beatTimes };

  const interval = main.interval;
  if (!Number.isFinite(interval) || interval <= 0) return { ...ZERO_BPM_RESULT, beatTimes };
  if (interval < opts.minInterval || interval > opts.maxInterval) {
    return { ...ZERO_BPM_RESULT, beatTimes };
  }
  const bpm = 60 / interval;
  // BPM 钳制 [30, 240]
  if (bpm < 30 || bpm > 240) return { ...ZERO_BPM_RESULT, beatTimes };

  // 置信度：主聚类占比 × (拍点密度因子)
  // 拍点密度因子：实际拍点数 / 理论拍点数（按主 interval 期望）
  const span = beatTimes[beatTimes.length - 1]! - beatTimes[0]!;
  const expectedBeats = span > 0 && interval > 0 ? span / interval + 1 : beatTimes.length;
  const density = expectedBeats > 0 ? Math.min(1, beatTimes.length / expectedBeats) : 0;
  const consistency = main.count / Math.max(1, clusters.reduce((s, c) => s + c.count, 0));
  const confidence = Math.min(1, density * consistency);

  return { bpm, confidence, beatTimes };
}

/**
 * 在线节拍跟踪器（M21.3 粒子系统消费）：维护滑动窗口的能量序列，
 * 逐帧喂入 bass 值，内部检测强拍并触发回调。
 *
 * 算法：缓存最近 N 秒的能量 + 时间戳，超过阈值且距上一拍 ≥ minInterval 时
 * 触发 ``onBeat(strength, timestamp)`` 回调。strength = 当前能量 / 阈值（[1, 3]）。
 *
 * 工厂函数：返回控制器对象，纯逻辑无副作用（不依赖 WebAudio / DOM）。
 */
export interface BeatTracker {
  /** 喂入一帧低频能量。返回是否触发拍点（true 时 onBeat 已被调用）。 */
  push(bassLevel: number, timestampSec: number): boolean;
  /** 获取最近一次拍点时间戳（秒），无拍点时 null。 */
  getLastBeatTime(): number | null;
  /** 获取最近估算的 BPM（滑动窗口），无效时 0。 */
  getBpm(): number;
  /** 获取当前拍点强度（[0,3]，0 = 拍点间隔外）。 */
  getBeatStrength(nowSec: number): number;
  /** 重置内部状态。 */
  reset(): void;
}

export interface BeatTrackerOptions {
  /** 滑动窗口长度（秒，默认 5s）。 */
  readonly windowSec?: number;
  /** 拍点触发阈值倍率（默认 1.4）。 */
  readonly thresholdRatio?: number;
  /** 最小拍点间隔（秒，默认 0.25）。 */
  readonly minInterval?: number;
  /** 拍点强度衰减时间常数（秒，默认 0.15）。 */
  readonly beatDecay?: number;
  /** 拍点回调。 */
  readonly onBeat?: (strength: number, timestampSec: number) => void;
}

export function createBeatTracker(options: BeatTrackerOptions = {}): BeatTracker {
  const windowSec = options.windowSec ?? 5;
  const thresholdRatio = options.thresholdRatio ?? 1.4;
  const minInterval = options.minInterval ?? 0.25;
  const beatDecay = options.beatDecay ?? 0.15;
  const onBeat = options.onBeat;

  const energies: number[] = [];
  const timestamps: number[] = [];
  /** 仅拍点时间戳（用于 BPM 估算，区别于全帧 timestamps）。 */
  const beatTimestamps: number[] = [];
  let lastBeatTs: number | null = null;
  let lastBeatStrength = 0;
  let cachedBpm = 0;
  let bpmCacheDirty = true;

  const pruneWindow = (nowSec: number): void => {
    const cutoff = nowSec - windowSec;
    while (timestamps.length > 0 && timestamps[0]! < cutoff) {
      timestamps.shift();
      energies.shift();
    }
    while (beatTimestamps.length > 0 && beatTimestamps[0]! < cutoff) {
      beatTimestamps.shift();
    }
  };

  const computeThreshold = (): number => {
    if (energies.length === 0) return Infinity;
    let sum = 0;
    for (const e of energies) sum += e;
    const mean = sum / energies.length;
    return mean * thresholdRatio;
  };

  return {
    push(bassLevel: number, timestampSec: number): boolean {
      if (!Number.isFinite(bassLevel) || !Number.isFinite(timestampSec)) return false;
      pruneWindow(timestampSec);
      energies.push(bassLevel);
      timestamps.push(timestampSec);
      const threshold = computeThreshold();
      if (bassLevel < threshold) {
        bpmCacheDirty = true;
        return false;
      }
      if (lastBeatTs !== null && timestampSec - lastBeatTs < minInterval) {
        bpmCacheDirty = true;
        return false;
      }
      lastBeatTs = timestampSec;
      beatTimestamps.push(timestampSec);
      const strength = Math.min(3, bassLevel / Math.max(0.01, threshold));
      lastBeatStrength = strength;
      onBeat?.(strength, timestampSec);
      bpmCacheDirty = true;
      return true;
    },

    getLastBeatTime(): number | null {
      return lastBeatTs;
    },

    getBpm(): number {
      if (!bpmCacheDirty) return cachedBpm;
      bpmCacheDirty = false;
      if (beatTimestamps.length < 4) {
        cachedBpm = 0;
        return 0;
      }
      const result = estimateBpm([...beatTimestamps]);
      cachedBpm = result.bpm;
      return cachedBpm;
    },

    getBeatStrength(nowSec: number): number {
      if (lastBeatTs === null) return 0;
      const dt = nowSec - lastBeatTs;
      if (dt < 0) return 0;
      // 完全衰减阈值：5 个时间常数后视为 0（exp(-5) ≈ 0.0067，可忽略）
      if (dt > beatDecay * 5) return 0;
      // 指数衰减：strength × exp(-dt / beatDecay)
      return lastBeatStrength * Math.exp(-dt / beatDecay);
    },

    reset(): void {
      energies.length = 0;
      timestamps.length = 0;
      beatTimestamps.length = 0;
      lastBeatTs = null;
      lastBeatStrength = 0;
      cachedBpm = 0;
      bpmCacheDirty = true;
    },
  };
}
