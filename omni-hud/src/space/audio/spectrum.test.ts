/**
 * spectrum 频谱分段纯函数测试（M21.1 TDD 红）：
 * - binFrequency / frequencyToBin 互逆 + 边界
 * - computeBandLevels 三段切分 + 峰值 + 空数据降级
 * - smoothBandValue attack/decay 分段平滑
 * - smoothBandLevels 整体平滑
 * 纯逻辑测试：预构造频谱数据，不依赖 WebAudio / DOM。
 */
import { describe, expect, it } from "vitest";

import {
  binFrequency,
  computeBandLevels,
  DEFAULT_BANDS,
  DEFAULT_FFT_SIZE,
  DEFAULT_SMOOTHER,
  frequencyToBin,
  smoothBandLevels,
  smoothBandValue,
  ZERO_BAND_LEVELS,
} from "./spectrum";

const SAMPLE_RATE = 44100;

describe("binFrequency / frequencyToBin", () => {
  it("bin 0 = 0Hz，bin 1 = sampleRate/fftSize Hz", () => {
    expect(binFrequency(0, SAMPLE_RATE)).toBe(0);
    expect(binFrequency(1, SAMPLE_RATE)).toBeCloseTo(SAMPLE_RATE / DEFAULT_FFT_SIZE, 5);
  });

  it("互逆：freq → bin → freq 近似还原（向下取整误差）", () => {
    const freq = 440;
    const bin = frequencyToBin(freq, SAMPLE_RATE);
    const back = binFrequency(bin, SAMPLE_RATE);
    // 误差 < 一个 bin 的频率间隔
    expect(Math.abs(back - freq)).toBeLessThan(SAMPLE_RATE / DEFAULT_FFT_SIZE);
  });

  it("频率超 Nyquist 钳制到最后一个 bin", () => {
    const nyquist = SAMPLE_RATE / 2;
    const lastBin = frequencyToBin(nyquist + 1000, SAMPLE_RATE);
    expect(lastBin).toBe(DEFAULT_FFT_SIZE / 2 - 1);
  });

  it("非法输入抛 RangeError", () => {
    expect(() => binFrequency(-1, SAMPLE_RATE)).toThrow(RangeError);
    expect(() => binFrequency(0, 0)).toThrow(RangeError);
    expect(() => binFrequency(0, -1)).toThrow(RangeError);
    expect(() => frequencyToBin(-1, SAMPLE_RATE)).toThrow(RangeError);
    expect(() => frequencyToBin(100, 0)).toThrow(RangeError);
  });
});

describe("computeBandLevels", () => {
  it("空数据 / null 返回 ZERO_BAND_LEVELS", () => {
    expect(computeBandLevels(null, SAMPLE_RATE)).toEqual(ZERO_BAND_LEVELS);
    expect(computeBandLevels(new Float32Array(0), SAMPLE_RATE)).toEqual(ZERO_BAND_LEVELS);
    expect(computeBandLevels(undefined, SAMPLE_RATE)).toEqual(ZERO_BAND_LEVELS);
  });

  it("非法采样率降级返回 ZERO_BAND_LEVELS（不抛）", () => {
    const data = new Float32Array(1024).fill(0.5);
    expect(computeBandLevels(data, 0)).toEqual(ZERO_BAND_LEVELS);
    expect(computeBandLevels(data, -1)).toEqual(ZERO_BAND_LEVELS);
    expect(computeBandLevels(data, Number.NaN)).toEqual(ZERO_BAND_LEVELS);
  });

  it("仅低频 bin 有能量时 bass 高、mid/treble 接近 0", () => {
    const data = new Float32Array(DEFAULT_FFT_SIZE / 2);
    const bassEndBin = Math.floor((DEFAULT_BANDS.bassMax * DEFAULT_FFT_SIZE) / SAMPLE_RATE) + 1;
    for (let i = 0; i < bassEndBin; i++) data[i] = 0.8;
    const levels = computeBandLevels(data, SAMPLE_RATE);
    expect(levels.bass).toBeGreaterThan(0.7);
    expect(levels.mid).toBeLessThan(0.05);
    expect(levels.treble).toBeLessThan(0.05);
    expect(levels.peak).toBeCloseTo(0.8, 2);
  });

  it("仅中频 bin 有能量时 mid 高、bass/treble 接近 0", () => {
    const data = new Float32Array(DEFAULT_FFT_SIZE / 2);
    const bassEndBin = Math.floor((DEFAULT_BANDS.bassMax * DEFAULT_FFT_SIZE) / SAMPLE_RATE) + 1;
    const midEndBin = Math.floor((DEFAULT_BANDS.midMax * DEFAULT_FFT_SIZE) / SAMPLE_RATE) + 1;
    for (let i = bassEndBin; i < midEndBin; i++) data[i] = 0.6;
    const levels = computeBandLevels(data, SAMPLE_RATE);
    expect(levels.mid).toBeGreaterThan(0.5);
    expect(levels.bass).toBeLessThan(0.05);
    expect(levels.treble).toBeLessThan(0.05);
  });

  it("仅高频 bin 有能量时 treble 高、bass/mid 接近 0", () => {
    const data = new Float32Array(DEFAULT_FFT_SIZE / 2);
    const midEndBin = Math.floor((DEFAULT_BANDS.midMax * DEFAULT_FFT_SIZE) / SAMPLE_RATE) + 1;
    const trebleEndBin = Math.min(
      data.length,
      Math.floor((DEFAULT_BANDS.trebleMax * DEFAULT_FFT_SIZE) / SAMPLE_RATE) + 1,
    );
    for (let i = midEndBin; i < trebleEndBin; i++) data[i] = 0.4;
    const levels = computeBandLevels(data, SAMPLE_RATE);
    expect(levels.treble).toBeGreaterThan(0.3);
    expect(levels.bass).toBeLessThan(0.05);
    expect(levels.mid).toBeLessThan(0.05);
  });

  it("峰值取全频段最大值（非段均值）", () => {
    const data = new Float32Array(DEFAULT_FFT_SIZE / 2).fill(0.1);
    data[100] = 0.95; // 一个突出峰值
    const levels = computeBandLevels(data, SAMPLE_RATE);
    expect(levels.peak).toBeCloseTo(0.95, 2);
  });

  it("所有值钳制到 [0,1]（dB 模式负值或 >1 异常均截断）", () => {
    const data = new Float32Array(DEFAULT_FFT_SIZE / 2).fill(-0.5);
    const levels = computeBandLevels(data, SAMPLE_RATE);
    expect(levels.bass).toBe(0);
    expect(levels.mid).toBe(0);
    expect(levels.treble).toBe(0);
    expect(levels.peak).toBe(0);
  });

  it("自定义频段边界生效", () => {
    const data = new Float32Array(DEFAULT_FFT_SIZE / 2);
    // 自定义边界：bassMax=500 Hz，让 bass 段覆盖更广
    const bands = { bassMax: 500, midMax: 4000, trebleMax: 16000 };
    const bassEndBin = Math.floor((500 * DEFAULT_FFT_SIZE) / SAMPLE_RATE) + 1;
    for (let i = 0; i < bassEndBin; i++) data[i] = 0.7;
    const levels = computeBandLevels(data, SAMPLE_RATE, bands);
    expect(levels.bass).toBeGreaterThan(0.6);
  });
});

describe("smoothBandValue", () => {
  it("next > prev 时走 attack（快冲顶）", () => {
    const params = { attack: 0.03, decay: 0.2 };
    // dt=10ms，attack=30ms → alpha = 1 - exp(-10/30) ≈ 0.283
    const result = smoothBandValue(0.2, 1.0, 0.01, params);
    expect(result).toBeGreaterThan(0.2);
    expect(result).toBeLessThan(1.0);
    // attack 比 decay 快：相同 dt 下冲顶幅度大于跌落幅度
    const decayResult = smoothBandValue(1.0, 0.2, 0.01, params);
    const attackDelta = result - 0.2;
    const decayDelta = 1.0 - decayResult;
    expect(attackDelta).toBeGreaterThan(decayDelta);
  });

  it("next < prev 时走 decay（慢跌落）", () => {
    const params = { attack: 0.03, decay: 0.2 };
    const result = smoothBandValue(1.0, 0.2, 0.01, params);
    expect(result).toBeLessThan(1.0);
    expect(result).toBeGreaterThan(0.2);
  });

  it("dt=0 或非法时返回 prev（无变化）", () => {
    expect(smoothBandValue(0.5, 0.9, 0)).toBe(0.5);
    expect(smoothBandValue(0.5, 0.9, -1)).toBe(0.5);
  });

  it("attack=0 时立即冲顶到 next", () => {
    const params = { attack: 0, decay: 0.2 };
    expect(smoothBandValue(0.2, 1.0, 0.01, params)).toBe(1.0);
  });

  it("非有限 prev/next 容错为 0", () => {
    expect(smoothBandValue(Number.NaN, 0.5, 0.01)).toBeGreaterThan(0);
    expect(smoothBandValue(0.5, Number.NaN, 0.01)).toBe(0.5);
  });
});

describe("smoothBandLevels", () => {
  it("每段独立平滑（bass attack 快、treble 同参数）", () => {
    const prev = { bass: 0.1, mid: 0.1, treble: 0.1, peak: 0.1 };
    const next = { bass: 1.0, mid: 0.5, treble: 0.3, peak: 1.0 };
    const result = smoothBandLevels(prev, next, 0.01);
    expect(result.bass).toBeGreaterThan(prev.bass);
    expect(result.mid).toBeGreaterThan(prev.mid);
    expect(result.treble).toBeGreaterThan(prev.treble);
    // 都未到目标值（dt=10ms 不足以完全收敛）
    expect(result.bass).toBeLessThan(next.bass);
    expect(result.mid).toBeLessThan(next.mid);
  });

  it("ZERO_BAND_LEVELS 作为 prev 时正常递增", () => {
    const next = { bass: 0.8, mid: 0.4, treble: 0.2, peak: 0.8 };
    const result = smoothBandLevels(ZERO_BAND_LEVELS, next, 0.01);
    expect(result.bass).toBeGreaterThan(0);
    expect(result.bass).toBeLessThan(0.8);
  });

  it("DEFAULT_SMOOTHER 常量存在且合理", () => {
    expect(DEFAULT_SMOOTHER.attack).toBeLessThan(DEFAULT_SMOOTHER.decay);
    expect(DEFAULT_SMOOTHER.attack).toBeGreaterThan(0);
    expect(DEFAULT_SMOOTHER.decay).toBeGreaterThan(0);
  });
});
