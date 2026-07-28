/**
 * audioAnalyser WebAudio 频谱分析器测试（M21.1 TDD 红）：
 * - 浏览器降级：无 AudioContextClass 时 isAvailable=false、connect 返回 E_NO_AUDIO_CONTEXT、
 *   sample 返回零能量；
 * - 连接链路：connect 调用 createAnalyser + createMediaElementSource + 双向 connect；
 * - 激活策略：activate resume AudioContext；activateOnGesture 注册一次性手势监听器；
 * - sample 采样：getFloatFrequencyData → dB 归一化 → BandLevels；
 * - dispose 幂等：关闭 ctx、断开节点、移除监听器。
 * 纯逻辑测试：fake AudioContext 注入预设频谱数据，不依赖真实 WebAudio。
 */
import { describe, expect, it, vi } from "vitest";

import {
  createAudioAnalyser,
  createFakeAudioContextCtor,
  E_NO_AUDIO_CONTEXT,
} from "./audioAnalyser";
import { DEFAULT_FFT_SIZE, ZERO_BAND_LEVELS } from "./spectrum";

const SAMPLE_RATE = 44100;

/** 构造仅低频有能量的频谱数据（dB，-60 静音 / 0 满量）。 */
function bassHeavyFreqData(): Float32Array {
  const data = new Float32Array(DEFAULT_FFT_SIZE / 2).fill(-100);
  // 低频前 12 个 bin 设为 -10 dB（强能量），其余静音
  for (let i = 0; i < 12; i++) data[i] = -10;
  return data;
}

describe("浏览器降级（无 AudioContextClass）", () => {
  it("isAvailable=false", () => {
    const a = createAudioAnalyser({});
    expect(a.isAvailable()).toBe(false);
  });

  it("connect 返回 E_NO_AUDIO_CONTEXT 且不创建上下文", () => {
    const a = createAudioAnalyser({});
    const audioEl = new Audio();
    expect(a.connect(audioEl)).toBe(E_NO_AUDIO_CONTEXT);
    expect(a.isConnected()).toBe(false);
    expect(a.isActive()).toBe(false);
  });

  it("sample 返回零能量 active=false", () => {
    const a = createAudioAnalyser({});
    const frame = a.sample(1000);
    expect(frame.active).toBe(false);
    expect(frame.levels).toEqual(ZERO_BAND_LEVELS);
    expect(frame.timestamp).toBe(1000);
  });

  it("activate 解析为 false", async () => {
    const a = createAudioAnalyser({});
    await expect(a.activate()).resolves.toBe(false);
  });

  it("dispose 幂等无副作用", () => {
    const a = createAudioAnalyser({});
    expect(() => a.dispose()).not.toThrow();
    expect(() => a.dispose()).not.toThrow();
  });
});

describe("connect 连接链路", () => {
  it("connect 成功创建 AnalyserNode + MediaElementSource + 双向 connect", () => {
    const FakeCtor = createFakeAudioContextCtor({
      sampleRate: SAMPLE_RATE,
      freqData: bassHeavyFreqData(),
    });
    const a = createAudioAnalyser({ AudioContextClass: FakeCtor });
    const audioEl = new Audio();
    expect(a.connect(audioEl)).toBeNull();
    expect(a.isConnected()).toBe(true);
    expect(a.isAvailable()).toBe(true);
  });

  it("connect 幂等：重复调用返回 null 不重复创建", () => {
    const FakeCtor = createFakeAudioContextCtor({ freqData: bassHeavyFreqData() });
    const a = createAudioAnalyser({ AudioContextClass: FakeCtor });
    const audioEl = new Audio();
    a.connect(audioEl);
    expect(a.connect(audioEl)).toBeNull();
    expect(a.isConnected()).toBe(true);
  });

  it("AudioContext 创建失败时降级返回 E_NO_AUDIO_CONTEXT", () => {
    const FakeCtor = createFakeAudioContextCtor({
      freqData: bassHeavyFreqData(),
      failCreate: true,
    });
    const a = createAudioAnalyser({ AudioContextClass: FakeCtor });
    expect(a.connect(new Audio())).toBe(E_NO_AUDIO_CONTEXT);
    expect(a.isConnected()).toBe(false);
  });

  it("dispose 后 connect 返回 E_NO_AUDIO_CONTEXT", () => {
    const FakeCtor = createFakeAudioContextCtor({ freqData: bassHeavyFreqData() });
    const a = createAudioAnalyser({ AudioContextClass: FakeCtor });
    a.connect(new Audio());
    a.dispose();
    expect(a.connect(new Audio())).toBe(E_NO_AUDIO_CONTEXT);
  });
});

describe("activate 激活策略", () => {
  it("未连接时 activate 返回 false", async () => {
    const FakeCtor = createFakeAudioContextCtor({
      freqData: bassHeavyFreqData(),
      initialState: "suspended",
    });
    const a = createAudioAnalyser({ AudioContextClass: FakeCtor });
    await expect(a.activate()).resolves.toBe(false);
  });

  it("connect 后 activate resume AudioContext 到 running", async () => {
    const FakeCtor = createFakeAudioContextCtor({
      freqData: bassHeavyFreqData(),
      initialState: "suspended",
    });
    const a = createAudioAnalyser({ AudioContextClass: FakeCtor });
    a.connect(new Audio());
    expect(a.isActive()).toBe(false);
    await expect(a.activate()).resolves.toBe(true);
    expect(a.isActive()).toBe(true);
  });

  it("已 running 时 activate 幂等返回 true", async () => {
    const FakeCtor = createFakeAudioContextCtor({
      freqData: bassHeavyFreqData(),
      initialState: "running",
    });
    const a = createAudioAnalyser({ AudioContextClass: FakeCtor });
    a.connect(new Audio());
    await expect(a.activate()).resolves.toBe(true);
    await expect(a.activate()).resolves.toBe(true);
  });

  it("activateOnGesture 注册 click/keydown/touchstart/pointerdown 一次性监听器", () => {
    const FakeCtor = createFakeAudioContextCtor({
      freqData: bassHeavyFreqData(),
      initialState: "suspended",
    });
    const addSpy = vi.spyOn(window, "addEventListener");
    const a = createAudioAnalyser({
      AudioContextClass: FakeCtor,
      windowRef: window,
    });
    a.connect(new Audio());
    a.activateOnGesture();
    expect(addSpy).toHaveBeenCalledWith("click", expect.any(Function), { once: true });
    expect(addSpy).toHaveBeenCalledWith("keydown", expect.any(Function), { once: true });
    expect(addSpy).toHaveBeenCalledWith("touchstart", expect.any(Function), { once: true });
    expect(addSpy).toHaveBeenCalledWith("pointerdown", expect.any(Function), { once: true });
    addSpy.mockRestore();
    a.dispose(); // 清理：避免监听器泄漏到后续测试
  });

  it("activateOnGesture 触发后激活 AudioContext 且移除监听器", async () => {
    const FakeCtor = createFakeAudioContextCtor({
      freqData: bassHeavyFreqData(),
      initialState: "suspended",
    });
    const removeSpy = vi.spyOn(window, "removeEventListener");
    const a = createAudioAnalyser({
      AudioContextClass: FakeCtor,
      windowRef: window,
    });
    a.connect(new Audio());
    a.activateOnGesture();
    expect(a.isActive()).toBe(false);
    window.dispatchEvent(new Event("click"));
    // 等待 activate().then(removeGestureHandlers) 链路完成
    await vi.waitFor(() => expect(a.isActive()).toBe(true));
    await vi.waitFor(() => expect(removeSpy).toHaveBeenCalledTimes(4));
    removeSpy.mockRestore();
  });

  it("已激活时 activateOnGesture 幂等 no-op", () => {
    const FakeCtor = createFakeAudioContextCtor({
      freqData: bassHeavyFreqData(),
      initialState: "running",
    });
    const addSpy = vi.spyOn(window, "addEventListener");
    const a = createAudioAnalyser({
      AudioContextClass: FakeCtor,
      windowRef: window,
    });
    a.connect(new Audio());
    a.activateOnGesture();
    expect(addSpy).not.toHaveBeenCalled();
    addSpy.mockRestore();
  });

  it("未连接时 activateOnGesture no-op", () => {
    const FakeCtor = createFakeAudioContextCtor({ freqData: bassHeavyFreqData() });
    const addSpy = vi.spyOn(window, "addEventListener");
    const a = createAudioAnalyser({
      AudioContextClass: FakeCtor,
      windowRef: window,
    });
    a.activateOnGesture();
    expect(addSpy).not.toHaveBeenCalled();
    addSpy.mockRestore();
  });
});

describe("sample 采样", () => {
  it("未激活时 sample 返回零能量 active=false", () => {
    const FakeCtor = createFakeAudioContextCtor({
      freqData: bassHeavyFreqData(),
      initialState: "suspended",
    });
    const a = createAudioAnalyser({ AudioContextClass: FakeCtor });
    a.connect(new Audio());
    const frame = a.sample(1000);
    expect(frame.active).toBe(false);
    expect(frame.levels).toEqual(ZERO_BAND_LEVELS);
  });

  it("激活后 sample 返回非零能量 active=true", async () => {
    const FakeCtor = createFakeAudioContextCtor({
      sampleRate: SAMPLE_RATE,
      freqData: bassHeavyFreqData(),
      initialState: "suspended",
    });
    const a = createAudioAnalyser({ AudioContextClass: FakeCtor });
    a.connect(new Audio());
    await a.activate();
    const frame = a.sample(1000);
    expect(frame.active).toBe(true);
    expect(frame.levels.bass).toBeGreaterThan(0.2); // 低频有强能量
    expect(frame.levels.treble).toBeLessThan(0.05); // 高频静音
    expect(frame.timestamp).toBe(1000);
  });

  it("dB 归一化：所有低频 bin -10dB → bass 段均值 ~0.316 线性振幅", async () => {
    // bass 段覆盖 0..250Hz，sampleRate=44100/fftSize=2048 → bins 0..11（12 个）
    const bassEndBin = Math.floor((250 * DEFAULT_FFT_SIZE) / SAMPLE_RATE) + 1;
    const data = new Float32Array(DEFAULT_FFT_SIZE / 2).fill(-100);
    for (let i = 0; i < bassEndBin; i++) data[i] = -10; // 低频段全部 -10dB
    const FakeCtor = createFakeAudioContextCtor({
      sampleRate: SAMPLE_RATE,
      freqData: data,
      initialState: "running",
    });
    const a = createAudioAnalyser({ AudioContextClass: FakeCtor });
    a.connect(new Audio());
    const frame = a.sample(0);
    // -10dB → 10^(-10/20) = 0.316，所有低频 bin 同值 → 均值 = 0.316
    expect(frame.levels.bass).toBeCloseTo(0.316, 2);
  });

  it("逐帧时间戳推进（dt 计算）", async () => {
    const FakeCtor = createFakeAudioContextCtor({
      freqData: bassHeavyFreqData(),
      initialState: "running",
    });
    const a = createAudioAnalyser({ AudioContextClass: FakeCtor });
    a.connect(new Audio());
    a.sample(0);
    const frame = a.sample(16); // 16ms = 60fps
    expect(frame.timestamp).toBe(16);
  });

  it("dispose 后 sample 返回零能量", async () => {
    const FakeCtor = createFakeAudioContextCtor({
      freqData: bassHeavyFreqData(),
      initialState: "running",
    });
    const a = createAudioAnalyser({ AudioContextClass: FakeCtor });
    a.connect(new Audio());
    a.dispose();
    const frame = a.sample(0);
    expect(frame.active).toBe(false);
    expect(frame.levels).toEqual(ZERO_BAND_LEVELS);
  });
});

describe("dispose 释放资源", () => {
  it("dispose 关闭 AudioContext 状态变为 closed", async () => {
    const FakeCtor = createFakeAudioContextCtor({
      freqData: bassHeavyFreqData(),
      initialState: "running",
    });
    const a = createAudioAnalyser({ AudioContextClass: FakeCtor });
    a.connect(new Audio());
    a.dispose();
    // 等待 close() Promise resolve
    await vi.waitFor(() => expect(a.isActive()).toBe(false));
    expect(a.isConnected()).toBe(false);
  });

  it("dispose 移除未触发的手势监听器", () => {
    const FakeCtor = createFakeAudioContextCtor({
      freqData: bassHeavyFreqData(),
      initialState: "suspended",
    });
    const removeSpy = vi.spyOn(window, "removeEventListener");
    const a = createAudioAnalyser({
      AudioContextClass: FakeCtor,
      windowRef: window,
    });
    a.connect(new Audio());
    a.activateOnGesture();
    a.dispose();
    expect(removeSpy).toHaveBeenCalledTimes(4);
    removeSpy.mockRestore();
  });

  it("dispose 幂等：多次调用无副作用", () => {
    const FakeCtor = createFakeAudioContextCtor({ freqData: bassHeavyFreqData() });
    const a = createAudioAnalyser({ AudioContextClass: FakeCtor });
    a.connect(new Audio());
    a.dispose();
    expect(() => a.dispose()).not.toThrow();
    expect(() => a.dispose()).not.toThrow();
  });
});
