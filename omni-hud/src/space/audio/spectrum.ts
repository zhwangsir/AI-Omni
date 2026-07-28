/**
 * spectrum 频谱分段纯函数（M21.1）：把 AnalyserNode 的 frequencyBinCount
 * 数组切分为低 / 中 / 高频段，并归一化到 [0,1]。
 *
 * 频段边界（D21.1 配套，与典型音乐频谱对齐）：
 * - bass（低频）：0~250 Hz，对应 kick / bass，驱动大粒子脉冲
 * - mid（中频）：250~2000 Hz，对应主旋律 / 人声，驱动流动
 * - treble（高频）：2000~8000 Hz，对应 hi-hat / 镲片，驱动闪烁
 *
 * 纯逻辑模块：不依赖 WebAudio / DOM，输入输出全是 number / TypedArray，
 * 可在 vitest 中以预构造频谱数据独立断言（非镜像实现）。
 *
 * 频率换算：bin i 对应频率 = i * sampleRate / fftSize；
 * AnalyserNode 的 frequencyBinCount = fftSize / 2。
 */
export interface BandBoundaries {
  /** 低频上界（Hz，含）。 */
  readonly bassMax: number;
  /** 中频上界（Hz，含）。 */
  readonly midMax: number;
  /** 高频上界（Hz，含）。 */
  readonly trebleMax: number;
}

/** 默认频段边界（M21.1 决策点 D21.1）。 */
export const DEFAULT_BANDS: BandBoundaries = {
  bassMax: 250,
  midMax: 2000,
  trebleMax: 8000,
};

/** 分段能量结果（每段 0~1 归一化振幅均值）。 */
export interface BandLevels {
  /** 低频段均值 [0,1]。 */
  readonly bass: number;
  /** 中频段均值 [0,1]。 */
  readonly mid: number;
  /** 高频段均值 [0,1]。 */
  readonly treble: number;
  /** 全频段峰值 [0,1]，用于强拍检测。 */
  readonly peak: number;
}

/** 空数据：降级或静音场景的零输出（不可变常量）。 */
export const ZERO_BAND_LEVELS: BandLevels = {
  bass: 0,
  mid: 0,
  treble: 0,
  peak: 0,
};

/** 默认 FFT 尺寸（M21.1 spec：FFT 2048）。 */
export const DEFAULT_FFT_SIZE = 2048;

/**
 * bin 索引 → 频率（Hz）：i * sampleRate / fftSize。
 * AnalyserNode frequencyBinCount = fftSize / 2，因此有效 bin 范围 [0, fftSize/2)。
 */
export function binFrequency(
  binIndex: number,
  sampleRate: number,
  fftSize: number = DEFAULT_FFT_SIZE,
): number {
  if (!Number.isFinite(binIndex) || binIndex < 0) {
    throw new RangeError(`非法 bin 索引: ${binIndex}`);
  }
  if (!Number.isFinite(sampleRate) || sampleRate <= 0) {
    throw new RangeError(`非法采样率: ${sampleRate}`);
  }
  if (!Number.isFinite(fftSize) || fftSize <= 0) {
    throw new RangeError(`非法 FFT 尺寸: ${fftSize}`);
  }
  return (binIndex * sampleRate) / fftSize;
}

/**
 * 频率 → 对应 bin 索引（向下取整）。频率超 Nyquist（sampleRate/2）返回最后一个 bin。
 */
export function frequencyToBin(
  freq: number,
  sampleRate: number,
  fftSize: number = DEFAULT_FFT_SIZE,
): number {
  if (!Number.isFinite(freq) || freq < 0) {
    throw new RangeError(`非法频率: ${freq}`);
  }
  if (!Number.isFinite(sampleRate) || sampleRate <= 0) {
    throw new RangeError(`非法采样率: ${sampleRate}`);
  }
  const maxBin = Math.floor(fftSize / 2) - 1;
  const bin = Math.floor((freq * fftSize) / sampleRate);
  return Math.min(maxBin, Math.max(0, bin));
}

/** 段内振幅均值（容错空段返回 0）。 */
function segmentAverage(data: Float32Array, start: number, end: number): number {
  if (end <= start) return 0;
  let sum = 0;
  for (let i = start; i < end; i++) {
    const v = data[i]!;
    sum += Number.isFinite(v) ? v : 0;
  }
  const avg = sum / (end - start);
  // 钳制 [0,1]：AnalyserNode 数据理论上 [0,1] 但 dB 模式可能负值，统一截断
  return Math.min(1, Math.max(0, avg));
}

/**
 * 计算频谱分段能量。freqData 长度应 = fftSize/2（frequencyBinCount），
 * 长度不符时按实际数据长度切分（容错降级，不抛错——WebAudio 数据可能因
 * 浏览器实现差异略有不同）。
 *
 * 返回 BandLevels（bass/mid/treble/peak，均 [0,1]）。
 * freqData 为空或非 TypedArray 时返回 ZERO_BAND_LEVELS。
 */
export function computeBandLevels(
  freqData: ArrayLike<number> | null | undefined,
  sampleRate: number,
  bands: BandBoundaries = DEFAULT_BANDS,
  fftSize: number = DEFAULT_FFT_SIZE,
): BandLevels {
  if (!freqData || (freqData as ArrayLike<number>).length === 0) {
    return ZERO_BAND_LEVELS;
  }
  if (!Number.isFinite(sampleRate) || sampleRate <= 0) {
    return ZERO_BAND_LEVELS;
  }
  const data = freqData as ArrayLike<number>;
  const len = data.length;
  if (len === 0) return ZERO_BAND_LEVELS;

  const bassEnd = Math.min(len, frequencyToBin(bands.bassMax, sampleRate, fftSize) + 1);
  const midEnd = Math.min(len, frequencyToBin(bands.midMax, sampleRate, fftSize) + 1);
  const trebleEnd = Math.min(len, frequencyToBin(bands.trebleMax, sampleRate, fftSize) + 1);

  // 转换为 Float32Array 视图以便 segmentAverage 复用（不复制，仅类型断言）
  const view = data as Float32Array;
  const bass = segmentAverage(view, 0, bassEnd);
  const mid = segmentAverage(view, bassEnd, midEnd);
  const treble = segmentAverage(view, midEnd, trebleEnd);

  let peak = 0;
  for (let i = 0; i < len; i++) {
    const v = data[i]!;
    if (Number.isFinite(v) && v > peak) peak = v;
  }
  peak = Math.min(1, Math.max(0, peak));

  return { bass, mid, treble, peak };
}

/**
 * 平滑器（M21.1 节奏感关键）：对逐帧 BandLevels 做 attack/decay 平滑，
 * 让 bass 段在强拍后快速跌落、弱拍时缓慢回升——产生"脉冲呼吸感"而非
 * 平均值跟随。attack 快（≤30ms 落位）、decay 慢（~200ms 衰减）。
 *
 * 纯函数：输入 prev + next + dt，返回平滑后的值。dt 单位秒。
 */
export interface BandSmootherParams {
  /** attack 时间常数（秒，越小越快冲顶）。 */
  readonly attack: number;
  /** decay 时间常数（秒，越小越快跌落）。 */
  readonly decay: number;
}

export const DEFAULT_SMOOTHER: BandSmootherParams = {
  attack: 0.03,
  decay: 0.2,
};

/** 单值平滑（attack/decay 分段）。 */
export function smoothBandValue(
  prev: number,
  next: number,
  dt: number,
  params: BandSmootherParams = DEFAULT_SMOOTHER,
): number {
  // NaN 视为"无新数据"：prev 保持不变（避免错误跌落到 0）
  if (!Number.isFinite(next)) return prev;
  if (!Number.isFinite(prev)) prev = 0;
  if (!Number.isFinite(dt) || dt <= 0) return prev;
  const tau = next > prev ? params.attack : params.decay;
  if (tau <= 0) return next;
  const alpha = 1 - Math.exp(-dt / tau);
  return prev + (next - prev) * alpha;
}

/** BandLevels 整体平滑（每段独立 attack/decay）。 */
export function smoothBandLevels(
  prev: BandLevels,
  next: BandLevels,
  dt: number,
  params: BandSmootherParams = DEFAULT_SMOOTHER,
): BandLevels {
  return {
    bass: smoothBandValue(prev.bass, next.bass, dt, params),
    mid: smoothBandValue(prev.mid, next.mid, dt, params),
    treble: smoothBandValue(prev.treble, next.treble, dt, params),
    peak: smoothBandValue(prev.peak, next.peak, dt, params),
  };
}
