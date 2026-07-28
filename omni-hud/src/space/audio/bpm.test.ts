/**
 * bpm 节拍检测算法测试（M21.2 TDD 红）：
 * - detectPeaks：能量阈值 + 局部最大 + 最小间隔退火
 * - clusterBeats：IOI 聚类 + 容差 + 主聚类提取
 * - estimateBpm：BPM 钳制 [30,240] + 置信度计算
 * - createBeatTracker：在线节拍跟踪 + 强度衰减 + BPM 缓存
 * 纯逻辑测试：预构造能量序列（已知 BPM 60/120/140），断言还原结果。
 * 算法镜像断言红线：不复制实现逻辑，仅断言"已知输入 → 已知 BPM"端到端语义。
 */
import { describe, expect, it, vi } from "vitest";

import {
  clusterBeats,
  createBeatTracker,
  DEFAULT_BPM_OPTIONS,
  detectPeaks,
  estimateBpm,
  ZERO_BPM_RESULT,
} from "./bpm";

/** 构造已知 BPM 的能量序列：每拍点处 bass 突增，其余帧低能量。
 * 返回 { energies, timestamps, beatTimes }（timestamps 等间隔 60fps）。
 * beatTimes 包含 t=0 首拍（与 detectPeaks 行为对齐）。 */
function buildEnergySeries(
  bpm: number,
  durationSec: number,
  frameRate: number = 60,
  beatPeak: number = 0.8,
  baseline: number = 0.1,
): { energies: number[]; timestamps: number[]; beatTimes: number[] } {
  const interval = 60 / bpm; // 秒/拍
  const frameCount = Math.floor(durationSec * frameRate);
  const energies: number[] = [];
  const timestamps: number[] = [];
  const beatTimes: number[] = [];
  for (let i = 0; i < frameCount; i++) {
    const t = i / frameRate;
    timestamps.push(t);
    // 距最近拍点的时间差
    const nearestBeat = Math.round(t / interval) * interval;
    const dt = Math.abs(t - nearestBeat);
    if (dt < 1 / frameRate / 2) {
      // 拍点帧：高能量
      energies.push(beatPeak);
      beatTimes.push(t); // 包含 t=0
    } else {
      // 拍点间：低能量
      energies.push(baseline);
    }
  }
  return { energies, timestamps, beatTimes };
}

describe("detectPeaks 能量峰值检测", () => {
  it("空序列返回空数组", () => {
    expect(detectPeaks([], [])).toEqual([]);
  });

  it("长度不一致抛 RangeError", () => {
    expect(() => detectPeaks([0.5, 0.6], [0.1])).toThrow(RangeError);
  });

  it("BPM 60 序列：检测到的拍点数 ≈ duration × bpm/60", () => {
    const { energies, timestamps, beatTimes } = buildEnergySeries(60, 5);
    const peaks = detectPeaks(energies, timestamps);
    // 5s × 1beat/s = ~5 拍（首拍 t=0 可能被跳过）
    expect(peaks.length).toBeGreaterThanOrEqual(4);
    expect(peaks.length).toBeLessThanOrEqual(6);
    // 拍点时间戳应与 beatTimes 大致对齐
    for (const peakIdx of peaks) {
      const ts = timestamps[peakIdx]!;
      const isNearBeat = beatTimes.some((bt) => Math.abs(bt - ts) < 0.05);
      expect(isNearBeat).toBe(true);
    }
  });

  it("BPM 120 序列：拍点间隔约 0.5s", () => {
    const { energies, timestamps } = buildEnergySeries(120, 4);
    const peaks = detectPeaks(energies, timestamps);
    expect(peaks.length).toBeGreaterThanOrEqual(6);
    // 相邻拍点间隔
    for (let i = 1; i < peaks.length; i++) {
      const dt = timestamps[peaks[i]!]! - timestamps[peaks[i - 1]!]!;
      expect(dt).toBeGreaterThanOrEqual(0.4);
      expect(dt).toBeLessThanOrEqual(0.6);
    }
  });

  it("全部相同能量（无峰值）返回空数组", () => {
    const energies = [0.5, 0.5, 0.5, 0.5, 0.5];
    const timestamps = [0, 0.1, 0.2, 0.3, 0.4];
    const peaks = detectPeaks(energies, timestamps);
    expect(peaks).toEqual([]);
  });

  it("minInterval 退火：相邻拍点间隔不小于阈值", () => {
    // 能量递增序列确保有局部最大：[0.5, 0.9, 0.5, 0.9, ...] 每 0.2s 一拍
    const energies = [0.9, 0.1, 0.1, 0.1, 0.9, 0.1, 0.1, 0.1, 0.9, 0.1];
    const timestamps = [0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45];
    const peaks = detectPeaks(energies, timestamps, { minInterval: 0.15, thresholdRatio: 1.0 });
    // 第一拍 t=0，第二拍应 ≥ 0.15s 后
    expect(peaks.length).toBeGreaterThanOrEqual(2);
    for (let i = 1; i < peaks.length; i++) {
      const dt = timestamps[peaks[i]!]! - timestamps[peaks[i - 1]!]!;
      expect(dt).toBeGreaterThanOrEqual(0.15 - 1e-9);
    }
  });

  it("minEnergy 下限：低于阈值的能量不视为拍点", () => {
    const energies = [0.2, 0.3, 0.2, 0.3, 0.2];
    const timestamps = [0, 0.5, 1.0, 1.5, 2.0];
    const peaks = detectPeaks(energies, timestamps, { minEnergy: 0.5 });
    expect(peaks).toEqual([]);
  });
});

describe("clusterBeats IOI 聚类", () => {
  it("拍点 < 2 返回空", () => {
    expect(clusterBeats([])).toEqual([]);
    expect(clusterBeats([1.0])).toEqual([]);
  });

  it("等间隔拍点（BPM 120）→ 单一聚类 interval≈0.5", () => {
    const beatTimes = [0, 0.5, 1.0, 1.5, 2.0, 2.5];
    const clusters = clusterBeats(beatTimes);
    expect(clusters.length).toBeGreaterThanOrEqual(1);
    expect(clusters[0]!.count).toBe(5); // 5 个 IOI
    expect(clusters[0]!.interval).toBeCloseTo(0.5, 2);
  });

  it("离群间隔分离到不同聚类", () => {
    // 4 个 0.5s 间隔 + 1 个 2.0s 离群
    const beatTimes = [0, 0.5, 1.0, 1.5, 2.0, 4.0];
    const clusters = clusterBeats(beatTimes);
    expect(clusters.length).toBe(2);
    // 主聚类是 0.5s（count=5，包含前 4 个 + 后 1 个），离群 2.0s（count=1）
    expect(clusters[0]!.interval).toBeCloseTo(0.5, 2);
    expect(clusters[0]!.count).toBeGreaterThan(clusters[1]!.count);
  });

  it("非法容差抛 RangeError", () => {
    expect(() => clusterBeats([0, 1], 0)).toThrow(RangeError);
    expect(() => clusterBeats([0, 1], -1)).toThrow(RangeError);
  });

  it("按 count 降序排序", () => {
    // 三个 0.4 间隔 + 一个 0.8 间隔
    const beatTimes = [0, 0.4, 0.8, 1.2, 2.0];
    const clusters = clusterBeats(beatTimes);
    expect(clusters[0]!.count).toBeGreaterThanOrEqual(clusters[clusters.length - 1]!.count);
  });
});

describe("estimateBpm BPM 估算", () => {
  it("拍点 < 4 返回 ZERO_BPM_RESULT（保留 beatTimes）", () => {
    const result = estimateBpm([0, 0.5, 1.0]);
    expect(result.bpm).toBe(0);
    expect(result.confidence).toBe(0);
    expect(result.beatTimes).toEqual([0, 0.5, 1.0]);
  });

  it("BPM 60 序列 → 估算 60 ± 1", () => {
    const { beatTimes } = buildEnergySeries(60, 6);
    const result = estimateBpm(beatTimes);
    expect(result.bpm).toBeGreaterThan(58);
    expect(result.bpm).toBeLessThan(62);
    expect(result.confidence).toBeGreaterThan(0.3);
  });

  it("BPM 120 序列 → 估算 120 ± 2", () => {
    const { beatTimes } = buildEnergySeries(120, 6);
    const result = estimateBpm(beatTimes);
    expect(result.bpm).toBeGreaterThan(118);
    expect(result.bpm).toBeLessThan(122);
  });

  it("BPM 140 序列 → 估算 140 ± 5（帧量化误差容差）", () => {
    // BPM 140 interval=0.4286s，60fps 量化后实际间隔可能为 0.4167s（25 帧）→ 144 BPM
    // 容差 ±5 覆盖帧量化误差
    const { beatTimes } = buildEnergySeries(140, 6);
    const result = estimateBpm(beatTimes);
    expect(result.bpm).toBeGreaterThan(135);
    expect(result.bpm).toBeLessThan(145);
  });

  it("间隔超 [minInterval, maxInterval] 返回 0", () => {
    // 间隔 3s = 20 BPM，低于 30 下限
    const beatTimes = [0, 3, 6, 9, 12];
    const result = estimateBpm(beatTimes);
    expect(result.bpm).toBe(0);
  });

  it("置信度 ∈ [0,1]", () => {
    const { beatTimes } = buildEnergySeries(100, 5);
    const result = estimateBpm(beatTimes);
    expect(result.confidence).toBeGreaterThanOrEqual(0);
    expect(result.confidence).toBeLessThanOrEqual(1);
  });

  it("ZERO_BPM_RESULT 常量", () => {
    expect(ZERO_BPM_RESULT.bpm).toBe(0);
    expect(ZERO_BPM_RESULT.confidence).toBe(0);
    expect(ZERO_BPM_RESULT.beatTimes).toEqual([]);
  });

  it("DEFAULT_BPM_OPTIONS 合理默认值", () => {
    expect(DEFAULT_BPM_OPTIONS.thresholdRatio).toBeGreaterThan(1);
    expect(DEFAULT_BPM_OPTIONS.minInterval).toBeGreaterThan(0);
    expect(DEFAULT_BPM_OPTIONS.maxInterval).toBeGreaterThan(DEFAULT_BPM_OPTIONS.minInterval);
  });
});

describe("createBeatTracker 在线节拍跟踪", () => {
  it("push 触发拍点时调用 onBeat 回调", () => {
    const onBeat = vi.fn();
    const tracker = createBeatTracker({ onBeat, thresholdRatio: 1.5 });
    // 先喂几个低能量帧建立基线
    for (let i = 0; i < 10; i++) {
      tracker.push(0.1, i * 0.05);
    }
    // 高能量帧（超过均值 × 1.5）
    const triggered = tracker.push(0.9, 0.5);
    expect(triggered).toBe(true);
    expect(onBeat).toHaveBeenCalledTimes(1);
    expect(onBeat.mock.calls[0]![1]).toBe(0.5); // 时间戳透传
    expect(onBeat.mock.calls[0]![0]).toBeGreaterThan(1); // strength > 1
  });

  it("minInterval 内的连续高能量不重复触发", () => {
    const onBeat = vi.fn();
    const tracker = createBeatTracker({ onBeat, minInterval: 0.3, thresholdRatio: 1.2 });
    for (let i = 0; i < 10; i++) tracker.push(0.1, i * 0.05);
    tracker.push(0.9, 0.5); // 触发
    const second = tracker.push(0.9, 0.55); // 间隔 0.05s < 0.3
    expect(second).toBe(false);
    expect(onBeat).toHaveBeenCalledTimes(1);
  });

  it("getBeatStrength 指数衰减", () => {
    const tracker = createBeatTracker({ thresholdRatio: 1.2, beatDecay: 0.1 });
    for (let i = 0; i < 10; i++) tracker.push(0.1, i * 0.05);
    tracker.push(0.9, 0.5); // 触发
    const s0 = tracker.getBeatStrength(0.5);
    const s1 = tracker.getBeatStrength(0.6); // 0.1s 后（1 个时间常数）
    const s2 = tracker.getBeatStrength(0.9); // 0.4s 后（4 个时间常数，接近完全衰减）
    expect(s0).toBeGreaterThan(0);
    expect(s1).toBeLessThan(s0);
    expect(s1).toBeGreaterThan(0);
    // 4 个时间常数后 strength < 0.1（exp(-4) ≈ 0.018，乘以 strength≤3 → < 0.06）
    expect(s2).toBeLessThan(0.1);
  });

  it("getBpm 从滑动窗口估算", () => {
    const tracker = createBeatTracker({ thresholdRatio: 1.2, windowSec: 5 });
    // BPM 120 = 0.5s 间隔
    for (let i = 0; i < 30; i++) {
      const t = i * 0.1;
      const isBeat = i % 5 === 0; // 每 0.5s 一拍
      tracker.push(isBeat ? 0.9 : 0.1, t);
    }
    const bpm = tracker.getBpm();
    expect(bpm).toBeGreaterThan(115);
    expect(bpm).toBeLessThan(125);
  });

  it("拍点不足时 getBpm 返回 0", () => {
    const tracker = createBeatTracker();
    tracker.push(0.5, 0);
    expect(tracker.getBpm()).toBe(0);
  });

  it("getLastBeatTime 初始为 null", () => {
    const tracker = createBeatTracker();
    expect(tracker.getLastBeatTime()).toBeNull();
  });

  it("reset 清空状态", () => {
    const tracker = createBeatTracker({ thresholdRatio: 1.2 });
    for (let i = 0; i < 10; i++) tracker.push(0.1, i * 0.05);
    tracker.push(0.9, 0.5);
    expect(tracker.getLastBeatTime()).toBe(0.5);
    tracker.reset();
    expect(tracker.getLastBeatTime()).toBeNull();
    expect(tracker.getBpm()).toBe(0);
    expect(tracker.getBeatStrength(0.6)).toBe(0);
  });

  it("滑动窗口裁剪：旧帧被丢弃", () => {
    const onBeat = vi.fn();
    const tracker = createBeatTracker({
      onBeat,
      windowSec: 1,
      thresholdRatio: 1.0,
      minInterval: 0.1,
    });
    // 灌入 5s 数据，前 4s 应被裁剪
    for (let i = 0; i < 100; i++) {
      tracker.push(i % 10 === 0 ? 0.8 : 0.1, i * 0.05);
    }
    // 只保留最后 1s 的数据，但 onBeat 仍应被调用过
    expect(onBeat).toHaveBeenCalled();
  });

  it("非有限输入容错返回 false", () => {
    const tracker = createBeatTracker();
    expect(tracker.push(Number.NaN, 0.5)).toBe(false);
    expect(tracker.push(0.5, Number.NaN)).toBe(false);
    expect(tracker.push(Number.POSITIVE_INFINITY, 0.5)).toBe(false);
  });
});
