/**
 * audioAnalyser WebAudio 频谱分析器（M21.1）：
 * 把 AudioPlayer 的 ``<audio>`` 元素经 ``createMediaElementSource`` 接入
 * AnalyserNode（FFT 2048），逐帧采样得 BandLevels（bass/mid/treble/peak）。
 *
 * 浏览器自动播放策略限制（红线）：
 * - AudioContext 必须在用户手势（click / keydown）后激活——``resume()`` 调用；
 * - 本模块不在构造时创建 AudioContext，而是延迟到 ``connect()`` 调用；
 * - ``activateOnGesture()`` 注册一次性手势监听器，用户首次交互后 resume。
 *
 * 浏览器降级：
 * - 无 ``window.AudioContext`` / ``webkitAudioContext`` 时，``sample()`` 返回
 *   ``ZERO_BAND_LEVELS``，``isActive()`` 返回 false——不阻塞渲染管线。
 *
 * 依赖注入：AudioContextClass / createMediaElementSourceFactory 经 deps 注入，
 * 测试以 fake 替换，不创建真实 WebAudio 上下文。
 *
 * 纯逻辑 + 副作用边界：spectrum.ts 纯函数负责频段切分；
 * 本模块只负责 WebAudio 节点生命周期与帧采样编排。
 */
import {
  computeBandLevels,
  DEFAULT_FFT_SIZE,
  smoothBandLevels,
  ZERO_BAND_LEVELS,
  type BandLevels,
  type BandSmootherParams,
  type BandBoundaries,
} from "./spectrum";

/** AudioContext 最小契约（真实 AudioContext 与 fake 均满足）。 */
export interface AudioContextLike {
  readonly state: "running" | "suspended" | "closed";
  readonly sampleRate: number;
  /** 音频输出目标（AnalyserNode.connect 目标）；fake 用占位对象。 */
  readonly destination: unknown;
  createAnalyser(): AnalyserNodeLike;
  createMediaElementSource(audioEl: HTMLMediaElement): MediaElementSourceLike;
  resume(): Promise<void>;
  close(): Promise<void>;
}

export interface AnalyserNodeLike {
  fftSize: number;
  readonly frequencyBinCount: number;
  getFloatFrequencyData(array: Float32Array): void;
  getByteFrequencyData(array: Uint8Array): void;
  connect(destination: unknown): void;
  disconnect(): void;
}

export interface MediaElementSourceLike {
  connect(destination: unknown): void;
  disconnect(): void;
}

/** AudioContext 工厂契约（标准 ``new AudioContext()``）。 */
export interface AudioContextCtor {
  new (options?: { sampleRate?: number }): AudioContextLike;
}

/** 降级策略：``window.AudioContext`` 缺失时返回的标识。 */
export const E_NO_AUDIO_CONTEXT = "E_NO_AUDIO_CONTEXT";

/** AudioAnalyser 依赖注入参数。 */
export interface AudioAnalyserDeps {
  /** AudioContext 构造器（标准 ``window.AudioContext``）；缺省时降级。 */
  readonly AudioContextClass?: AudioContextCtor | null;
  /** FFT 尺寸（必须为 2 的幂，默认 2048）。 */
  readonly fftSize?: number;
  /** 频段边界（默认 DEFAULT_BANDS）。 */
  readonly bands?: BandBoundaries;
  /** 平滑参数（默认 DEFAULT_SMOOTHER）。 */
  readonly smoother?: BandSmootherParams;
  /** window 引用（用于 gesture 监听）；缺省时不注册手势激活。 */
  readonly windowRef?: Window | null;
}

/** 采样结果（M21.3 粒子系统消费的音频数据源）。 */
export interface AudioFrame {
  /** 频段能量（平滑后）。 */
  readonly levels: BandLevels;
  /** AudioContext 是否处于 running 状态（false 时 levels 为零）。 */
  readonly active: boolean;
  /** 当前帧时间戳（ms，用于 BPM 检测的时间序列）。 */
  readonly timestamp: number;
}

/**
 * WebAudio 频谱分析器。
 *
 * 生命周期：
 * 1. 构造：不创建 AudioContext（避免页面加载即激活违反自动播放策略）；
 * 2. ``connect(audioEl)``：创建 AudioContext + AnalyserNode + MediaElementSource 链路；
 *    AudioContext 初始为 suspended，等待 ``activate()``；
 * 3. ``activate()``：resume AudioContext（必须由用户手势触发）；
 * 4. ``sample(now)``：返回当前帧 BandLevels（active=false 时返回零）；
 * 5. ``dispose()``：关闭 AudioContext、断开节点、移除手势监听。
 */
export interface AudioAnalyser {
  /** AudioContext 是否可用（无 AudioContextClass 时为 false）。 */
  isAvailable(): boolean;
  /** AudioContext 是否处于 running 状态（已激活且未关闭）。 */
  isActive(): boolean;
  /** 是否已连接音频元素。 */
  isConnected(): boolean;
  /**
   * 连接音频元素：创建 AudioContext + AnalyserNode + MediaElementSource 链路。
   * 已连接时重复调用幂等返回；AudioContextClass 缺失时返回 E_NO_AUDIO_CONTEXT。
   */
  connect(audioEl: HTMLMediaElement): string | null;
  /**
   * 激活 AudioContext（resume）。必须在用户手势事件中调用。
   * 返回激活后状态：true=running，false=不可用或失败。
   */
  activate(): Promise<boolean>;
  /**
   * 注册一次性手势监听器（click/keydown），用户首次交互后自动 resume。
   * 已激活或不可用时幂等 no-op。
   */
  activateOnGesture(): void;
  /** 采样一帧（now 为 ms 时间戳）。active=false 时返回零能量。 */
  sample(now: number): AudioFrame;
  /** 释放资源：关闭 AudioContext、断开节点、移除手势监听。幂等。 */
  dispose(): void;
}

export function createAudioAnalyser(deps: AudioAnalyserDeps = {}): AudioAnalyser {
  const AudioContextClass = deps.AudioContextClass ?? null;
  const fftSize = deps.fftSize ?? DEFAULT_FFT_SIZE;
  const bands = deps.bands;
  const smoother = deps.smoother;
  const windowRef = deps.windowRef ?? null;

  let ctx: AudioContextLike | null = null;
  let analyser: AnalyserNodeLike | null = null;
  let source: MediaElementSourceLike | null = null;
  let connected = false;
  let disposed = false;
  let freqBuffer: Float32Array | null = null;
  let prevLevels: BandLevels = ZERO_BAND_LEVELS;
  let lastSampleTs: number | null = null;
  let gestureHandlers: Array<{ type: string; handler: () => void }> = [];

  const isAvailable = (): boolean => AudioContextClass !== null;

  const activateFn = async (): Promise<boolean> => {
    if (!ctx || disposed) return false;
    if (ctx.state === "running") return true;
    try {
      await ctx.resume();
      // resume() 可能改变 state，但 TS 沿控制流收窄无法感知；用字符串比较绕过收窄。
      return (ctx.state as string) === "running";
    } catch {
      return false;
    }
  };

  const removeGestureHandlers = (): void => {
    if (!windowRef) return;
    for (const { type, handler } of gestureHandlers) {
      windowRef.removeEventListener(type, handler);
    }
    gestureHandlers = [];
  };

  return {
    isAvailable,

    isActive(): boolean {
      return ctx !== null && ctx.state === "running" && !disposed;
    },

    isConnected(): boolean {
      return connected;
    },

    connect(audioEl: HTMLMediaElement): string | null {
      if (disposed) return E_NO_AUDIO_CONTEXT;
      if (connected) return null; // 幂等
      if (!AudioContextClass) return E_NO_AUDIO_CONTEXT;
      try {
        ctx = new AudioContextClass();
        analyser = ctx.createAnalyser();
        analyser.fftSize = fftSize;
        freqBuffer = new Float32Array(analyser.frequencyBinCount);
        source = ctx.createMediaElementSource(audioEl);
        source.connect(analyser);
        analyser.connect(ctx.destination);
        connected = true;
        return null;
      } catch {
        // 创建失败（WebAudio 不可用 / 元素已连接等）：降级，不抛错
        ctx = null;
        analyser = null;
        source = null;
        freqBuffer = null;
        connected = false;
        return E_NO_AUDIO_CONTEXT;
      }
    },

    activate: activateFn,

    activateOnGesture(): void {
      if (!windowRef || disposed) return;
      if (ctx && ctx.state === "running") return; // 已激活
      if (!connected) return; // 未连接，监听无意义
      const types = ["click", "keydown", "touchstart", "pointerdown"];
      const handler = (): void => {
        void activateFn().then(() => {
          removeGestureHandlers();
        });
      };
      for (const type of types) {
        windowRef.addEventListener(type, handler, { once: true });
        gestureHandlers.push({ type, handler });
      }
    },

    sample(now: number): AudioFrame {
      if (disposed || !ctx || !analyser || !freqBuffer || ctx.state !== "running") {
        return { levels: ZERO_BAND_LEVELS, active: false, timestamp: now };
      }
      analyser.getFloatFrequencyData(freqBuffer);
      // getFloatFrequencyData 返回 dB 值（典型 -100..0），归一化到 [0,1]
      // 转换：dB → 线性振幅 = 10^(dB/20)，再钳制 [0,1]
      const normalized = new Float32Array(freqBuffer.length);
      for (let i = 0; i < freqBuffer.length; i++) {
        const db = freqBuffer[i]!;
        if (!Number.isFinite(db) || db <= -100) {
          normalized[i] = 0;
        } else {
          const lin = Math.pow(10, db / 20);
          normalized[i] = Math.min(1, Math.max(0, lin));
        }
      }
      const raw = computeBandLevels(normalized, ctx.sampleRate, bands, fftSize);
      // 平滑：基于上一帧时间戳计算 dt
      const dt = lastSampleTs === null ? 1 / 60 : Math.min(0.5, Math.max(0, (now - lastSampleTs) / 1000));
      const smoothed = smoother
        ? smoothBandLevels(prevLevels, raw, dt, smoother)
        : raw;
      prevLevels = smoothed;
      lastSampleTs = now;
      return { levels: smoothed, active: true, timestamp: now };
    },

    dispose(): void {
      if (disposed) return;
      disposed = true;
      removeGestureHandlers();
      try {
        source?.disconnect();
      } catch { /* noop */ }
      try {
        analyser?.disconnect();
      } catch { /* noop */ }
      source = null;
      analyser = null;
      freqBuffer = null;
      const c = ctx;
      ctx = null;
      if (c) {
        void c.close().catch(() => { /* noop */ });
      }
      prevLevels = ZERO_BAND_LEVELS;
      lastSampleTs = null;
      connected = false;
    },
  };
}

/** 测试用 fake AudioContext 构造器工厂：注入预设频谱数据。 */
export function createFakeAudioContextCtor(
  options: {
    readonly sampleRate?: number;
    readonly freqData?: Float32Array;
    readonly initialState?: AudioContextLike["state"];
    readonly failCreate?: boolean;
  } = {},
): AudioContextCtor {
  const sampleRate = options.sampleRate ?? 44100;
  const freqData = options.freqData ?? new Float32Array(DEFAULT_FFT_SIZE / 2).fill(-60);
  const initialState = options.initialState ?? "suspended";
  return class FakeAudioContext implements AudioContextLike {
    state: AudioContextLike["state"] = initialState;
    readonly sampleRate = sampleRate;
    readonly destination: unknown = {};
    private analyserNode: FakeAnalyserNode;
    private sourceNode: FakeMediaElementSource;
    private closed = false;

    constructor() {
      if (options.failCreate) {
        throw new Error("fake: AudioContext create failed");
      }
      this.analyserNode = new FakeAnalyserNode(freqData);
      this.sourceNode = new FakeMediaElementSource();
    }

    createAnalyser(): AnalyserNodeLike {
      return this.analyserNode;
    }

    createMediaElementSource(_audioEl: HTMLMediaElement): MediaElementSourceLike {
      return this.sourceNode;
    }

    async resume(): Promise<void> {
      if (!this.closed) this.state = "running";
    }

    async close(): Promise<void> {
      this.closed = true;
      this.state = "closed";
    }
  };
}

class FakeAnalyserNode implements AnalyserNodeLike {
  fftSize: number = DEFAULT_FFT_SIZE;
  readonly frequencyBinCount: number;

  constructor(private readonly freqData: Float32Array) {
    this.frequencyBinCount = freqData.length;
  }

  getFloatFrequencyData(array: Float32Array): void {
    const n = Math.min(array.length, this.freqData.length);
    for (let i = 0; i < n; i++) array[i] = this.freqData[i]!;
  }

  getByteFrequencyData(array: Uint8Array): void {
    const n = Math.min(array.length, this.freqData.length);
    for (let i = 0; i < n; i++) {
      const db = this.freqData[i] ?? -100;
      const lin = Math.pow(10, db / 20);
      array[i] = Math.min(255, Math.max(0, Math.round(lin * 255)));
    }
  }

  connect(_destination: unknown): void {
    // fake：仅模拟连接成功，不维护连接状态。
  }

  disconnect(): void {
    // fake：仅模拟断开。
  }
}

class FakeMediaElementSource implements MediaElementSourceLike {
  connect(_destination: unknown): void {
    // fake：仅模拟连接成功。
  }
  disconnect(): void {
    // fake：仅模拟断开。
  }
}
