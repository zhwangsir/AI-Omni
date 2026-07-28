/**
 * quality 画质档监控（M5.1 + M21.7 cinematic 扩展）：
 * 三档基础定义（high 4000 / medium 2000 / low 800 粒子）+ fps 滚动均值自动降档
 * （<50fps）与持续高帧升档（>58fps 保持数秒）+ 手动覆盖 + prefers-reduced-motion 强制 low。
 * M21.7 追加 cinematic 三档（cinematic_high 8000 / cinematic_medium 4000 / cinematic_low 2000，
 * D21.3 音乐模式放宽粒子数上限）——cinematic 档仅作手动覆盖，不参与 fps 自动升降档
 * （auto-stepping 限定在 normal 三档内，避免音乐模式帧率波动时跨入 cinematic 抖动）。
 * 纯逻辑模块：帧时间戳全部注入，不依赖 three / DOM，可独立单测。
 */

/** 普通画质档：auto-stepping 限定在此范围内。 */
export type QualityTier = "high" | "medium" | "low";

/** M21.7 cinematic 画质档：音乐模式手动覆盖专用，放宽粒子数上限（D21.3）。 */
export type CinematicQualityTier = "cinematic_high" | "cinematic_medium" | "cinematic_low";

/** M22.4 壁纸模式画质档：壁纸态降密降亮，粒子≤2000，保 GPU<15%。 */
export type WallpaperQualityTier = "wallpaper";

/** 全部画质档名：normal + cinematic + wallpaper。 */
export type QualityTierName = QualityTier | CinematicQualityTier | WallpaperQualityTier;

export interface QualityTierSpec {
  readonly tier: QualityTierName;
  /** 该档 GPU 粒子数上限（M5.2 真粒子系统消费；M5.1 占位点云远低于此）。 */
  readonly particleCount: number;
  /** 是否开启 MSAA 抗锯齿。 */
  readonly antialias: boolean;
  /** 像素比上限：低档压到 1 保帧率。 */
  readonly pixelRatioCap: number;
}

/** normal 三档定义，顺序固定 high → medium → low（升降档按索引步进）。 */
export const QUALITY_TIERS: readonly QualityTierSpec[] = [
  { tier: "high", particleCount: 4000, antialias: true, pixelRatioCap: 2 },
  { tier: "medium", particleCount: 2000, antialias: true, pixelRatioCap: 1.5 },
  { tier: "low", particleCount: 800, antialias: false, pixelRatioCap: 1 },
];

/**
 * M21.7 cinematic 三档定义（D21.3 音乐模式放宽）：
 * cinematic_high 8000（音乐模式下场面感拉满，但不超过 GPU 粒子约束 M5 high≤8000 上限）
 * cinematic_medium 4000（≈ normal high 的粒子数，但语义为"音乐模式标准档"）
 * cinematic_low 2000（音乐模式最低档仍保场面感，不低于 normal medium）
 * 顺序固定 cinematic_high → cinematic_medium → cinematic_low（仅展示用，不参与 auto-stepping）。
 */
export const CINEMATIC_QUALITY_TIERS: readonly QualityTierSpec[] = [
  { tier: "cinematic_high", particleCount: 8000, antialias: true, pixelRatioCap: 2 },
  { tier: "cinematic_medium", particleCount: 4000, antialias: true, pixelRatioCap: 1.5 },
  { tier: "cinematic_low", particleCount: 2000, antialias: false, pixelRatioCap: 1 },
];

/**
 * M22.4 壁纸模式画质档定义（D22.1 壁纸态降密降亮）：
 * particleCount 2000（≤2000 红线，M22.4 spec），关闭 AA，像素比钳到 1。
 * 壁纸态窗口沉到桌面图标下方，不抢前台焦点，GPU 占用 < 15%。
 * 由 QualityMonitor.setWallpaperMode(true) 强制锁定，不参与 fps 自动升降档。
 */
export const WALLPAPER_QUALITY_TIER: QualityTierSpec = {
  tier: "wallpaper",
  particleCount: 2000,
  antialias: false,
  pixelRatioCap: 1,
};

/** 全部档位定义（normal + cinematic + wallpaper），用于 getTierSpec 查找。 */
const ALL_TIERS: readonly QualityTierSpec[] = [
  ...QUALITY_TIERS,
  ...CINEMATIC_QUALITY_TIERS,
  WALLPAPER_QUALITY_TIER,
];

/** 滚动窗口评估所需的最小帧数：窗口未满前不做任何自动决策。 */
export const MIN_EVAL_FRAMES = 60;

/** 未知档位一律 RangeError（调用侧依赖此契约做入参校验）。 */
export function getTierSpec(tier: QualityTierName): QualityTierSpec {
  const spec = ALL_TIERS.find((s) => s.tier === tier);
  if (!spec) throw new RangeError(`未知画质档: ${String(tier)}`);
  return spec;
}

/** M21.7 类型守卫：判断档位是否为 cinematic 档。 */
export function isCinematicTier(tier: QualityTierName): tier is CinematicQualityTier {
  return (
    tier === "cinematic_high" || tier === "cinematic_medium" || tier === "cinematic_low"
  );
}

/** M22.4 类型守卫：判断档位是否为 wallpaper 档。 */
export function isWallpaperTier(tier: QualityTierName): tier is WallpaperQualityTier {
  return tier === "wallpaper";
}

/** M21.7 normal → cinematic 映射；已是 cinematic 档幂等返回。
 * M22.4：wallpaper 档（壁纸模式专属）映射到 cinematic_low（同为低功耗语义）。 */
export function toCinematicTier(tier: QualityTierName): CinematicQualityTier {
  if (isCinematicTier(tier)) return tier;
  switch (tier) {
    case "high":
      return "cinematic_high";
    case "medium":
      return "cinematic_medium";
    case "low":
      return "cinematic_low";
    case "wallpaper":
      // 壁纸档 ≈ 低功耗语义，映射到 cinematic_low（音乐模式接入住壁纸态时取最低 cinematic 档）
      return "cinematic_low";
  }
}

/** M21.7 cinematic → normal 映射；已是 normal 档幂等返回。
 * M22.4：wallpaper 档（壁纸模式专属）映射到 low（同为低功耗语义）。 */
export function toNormalTier(tier: QualityTierName): QualityTier {
  if (!isCinematicTier(tier)) {
    // normal 档（high/medium/low）幂等返回；wallpaper 档映射到 low（低功耗语义对齐）
    return tier === "wallpaper" ? "low" : tier;
  }
  switch (tier) {
    case "cinematic_high":
      return "high";
    case "cinematic_medium":
      return "medium";
    case "cinematic_low":
      return "low";
  }
}

export interface QualityMonitorOptions {
  /** 滚动均值低于此 fps 降一档（默认 50）。 */
  readonly downFps?: number;
  /** 滚动均值高于此 fps 开始升档计时（默认 58；必须大于 downFps）。 */
  readonly upFps?: number;
  /** 连续两次自动降档的最小间隔（默认 2500ms，防抖）。 */
  readonly cooldownMs?: number;
  /** 升档所需的高帧持续时长（默认 4000ms）。 */
  readonly upHoldMs?: number;
  /** 构造时的 reduced-motion 初始态。 */
  readonly reducedMotion?: boolean;
  /** M22.4 构造时的 wallpaper 模式初始态。 */
  readonly wallpaperMode?: boolean;
}

export type QualityListener = (tier: QualityTierName) => void;

export interface QualityMonitor {
  /** 喂一帧时间戳（ms）。reduced-motion / 手动覆盖 / wallpaper 期间忽略。 */
  recordFrame(now: number): void;
  /** 有效档位 = reduced-motion ? low : (wallpaper ? wallpaper : (override ?? auto))。 */
  getTier(): QualityTierName;
  getTierSpec(): QualityTierSpec;
  /** 手动覆盖；传 null 清除回到自动档。未知档抛 RangeError。cinematic 档接受为覆盖。 */
  setOverride(tier: QualityTierName | null): void;
  setReducedMotion(on: boolean): void;
  /** M22.4 壁纸模式：true 强制 wallpaper 档，false 回自动档。 */
  setWallpaperMode(on: boolean): void;
  /** 订阅有效档位变化；返回退订函数。 */
  subscribe(listener: QualityListener): () => void;
}

export function createQualityMonitor(options: QualityMonitorOptions = {}): QualityMonitor {
  const downFps = options.downFps ?? 50;
  const upFps = options.upFps ?? 58;
  const cooldownMs = options.cooldownMs ?? 2500;
  const upHoldMs = options.upHoldMs ?? 4000;
  if (!(downFps < upFps)) {
    throw new RangeError(`降档阈值(${downFps})必须低于升档阈值(${upFps})，否则状态机会抖动`);
  }

  // autoTier 限定 normal 三档：fps 自动升降档不跨入 cinematic（避免音乐模式帧率波动抖动）
  let autoTier: QualityTier = "high";
  let override: QualityTierName | null = null;
  let reducedMotion = options.reducedMotion ?? false;
  // M22.4：wallpaper 模式强制 wallpaper 档（优先级低于 reduced-motion，高于 override/auto）
  let wallpaperMode = options.wallpaperMode ?? false;
  const stamps: number[] = [];
  let lastDownAt = Number.NEGATIVE_INFINITY;
  let upSince: number | null = null;
  const listeners = new Set<QualityListener>();

  // 优先级：reduced-motion（光敏防护）> wallpaper（壁纸降密）> override > auto
  const effectiveTier = (): QualityTierName =>
    reducedMotion ? "low" : (wallpaperMode ? "wallpaper" : (override ?? autoTier));

  // 单一出口：任何输入变化后同步一次，变了才通知（相同档位不重复通知）。
  let current: QualityTierName = effectiveTier();
  const sync = (): void => {
    const next = effectiveTier();
    if (next === current) return;
    current = next;
    for (const listener of listeners) listener(next);
  };

  // auto-stepping 只在 normal 三档内步进（QUALITY_TIERS 不含 cinematic）
  const stepTier = (tier: QualityTier, delta: number): QualityTier => {
    const index = QUALITY_TIERS.findIndex((s) => s.tier === tier);
    // QUALITY_TIERS 只含 normal 档，tier 字段实际为 QualityTier；cast 安全
    return QUALITY_TIERS[Math.min(QUALITY_TIERS.length - 1, Math.max(0, index + delta))]!
      .tier as QualityTier;
  };

  const resetTiming = (): void => {
    stamps.length = 0;
    upSince = null;
  };

  return {
    recordFrame(now: number): void {
      // 锁定期忽略帧数据：reduced-motion / override / wallpaper
      if (reducedMotion || override !== null || wallpaperMode) return;
      stamps.push(now);
      if (stamps.length > MIN_EVAL_FRAMES) stamps.shift();
      if (stamps.length < MIN_EVAL_FRAMES) return;
      const span = stamps[stamps.length - 1]! - stamps[0]!;
      if (span <= 0) return;
      const fps = ((stamps.length - 1) * 1000) / span;

      if (fps < downFps) {
        upSince = null;
        if (now - lastDownAt >= cooldownMs && autoTier !== "low") {
          lastDownAt = now;
          autoTier = stepTier(autoTier, 1);
          sync();
        }
        return;
      }

      if (fps > upFps) {
        upSince ??= now;
        if (now - upSince >= upHoldMs && autoTier !== "high") {
          autoTier = stepTier(autoTier, -1);
          upSince = null;
          sync();
        }
      } else {
        upSince = null; // 中间帧率打断升档计时，重新累计
      }
    },

    getTier(): QualityTierName {
      return effectiveTier();
    },

    getTierSpec(): QualityTierSpec {
      return getTierSpec(effectiveTier());
    },

    setOverride(tier: QualityTierName | null): void {
      if (tier !== null) getTierSpec(tier); // 非法档直接 RangeError
      override = tier;
      resetTiming();
      sync();
    },

    setReducedMotion(on: boolean): void {
      if (on === reducedMotion) return;
      reducedMotion = on;
      resetTiming();
      sync();
    },

    setWallpaperMode(on: boolean): void {
      if (on === wallpaperMode) return;
      wallpaperMode = on;
      resetTiming();
      sync();
    },

    subscribe(listener: QualityListener): () => void {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
