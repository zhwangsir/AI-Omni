/**
 * quality 画质档监控测试（M5.1）：fps 滚动均值 → 自动降档（<50fps）/
 * 持续高帧升档（>58fps 保持数秒），冷却防抖、手动覆盖、
 * prefers-reduced-motion 强制 low。纯逻辑，帧时间戳全部注入。
 */
import { describe, expect, it, vi } from "vitest";

import {
  CINEMATIC_QUALITY_TIERS,
  MIN_EVAL_FRAMES,
  QUALITY_TIERS,
  createQualityMonitor,
  getTierSpec,
  isCinematicTier,
  isWallpaperTier,
  toCinematicTier,
  toNormalTier,
  type QualityTier,
  type QualityTierName,
} from "./quality";

const FRAME_60FPS = 1000 / 60; // ≈16.67ms
const FRAME_30FPS = 1000 / 30; // ≈33.33ms
/** 52fps 上下的帧间隔：高于降档线、低于升档线，用来打断升档计时。 */
const FRAME_RECOVER = 19;

/** 以固定帧间隔喂 frames 帧，返回最后一帧的时刻。 */
function feed(
  monitor: { recordFrame: (now: number) => void },
  start: number,
  frames: number,
  interval: number,
): number {
  let t = start;
  for (let i = 0; i < frames; i++) {
    t += interval;
    monitor.recordFrame(t);
  }
  return t;
}

describe("画质档定义", () => {
  it("三档粒子数 4000 / 2000 / 800，顺序 high → medium → low", () => {
    expect(QUALITY_TIERS.map((spec) => spec.tier)).toEqual(["high", "medium", "low"]);
    expect(getTierSpec("high").particleCount).toBe(4000);
    expect(getTierSpec("medium").particleCount).toBe(2000);
    expect(getTierSpec("low").particleCount).toBe(800);
  });

  it("低档关闭抗锯齿并收紧像素比上限（保帧率优先）", () => {
    expect(getTierSpec("high").antialias).toBe(true);
    expect(getTierSpec("low").antialias).toBe(false);
    expect(getTierSpec("low").pixelRatioCap).toBeLessThan(getTierSpec("high").pixelRatioCap);
  });

  it("getTierSpec 对未知档位抛 RangeError", () => {
    expect(() => getTierSpec("ultra" as QualityTier)).toThrow(RangeError);
  });

  it("降档阈值必须低于升档阈值，否则拒绝构造", () => {
    expect(() => createQualityMonitor({ downFps: 60, upFps: 58 })).toThrow(RangeError);
  });
});

describe("fps 滚动均值自动降档", () => {
  it("帧数据不足评估窗口时不降档", () => {
    const monitor = createQualityMonitor();
    feed(monitor, 0, MIN_EVAL_FRAMES - 10, FRAME_30FPS);
    expect(monitor.getTier()).toBe("high");
  });

  it("滚动均值 < 50fps 时降一档", () => {
    const monitor = createQualityMonitor();
    feed(monitor, 0, 60, FRAME_30FPS);
    expect(monitor.getTier()).toBe("medium");
  });

  it("持续低帧率跨过冷却期后继续降到 low", () => {
    const monitor = createQualityMonitor();
    let t = feed(monitor, 0, 60, FRAME_30FPS); // ≈2s → medium
    expect(monitor.getTier()).toBe("medium");
    feed(monitor, t, 90, FRAME_30FPS); // 又 ≈3s，越过 2.5s 冷却
    expect(monitor.getTier()).toBe("low");
  });

  it("冷却期内不连续降档（防抖）", () => {
    const monitor = createQualityMonitor({ cooldownMs: 2500 });
    let t = feed(monitor, 0, 60, FRAME_30FPS); // 降 medium（t≈2s）
    expect(monitor.getTier()).toBe("medium");
    feed(monitor, t, 30, FRAME_30FPS); // 又过 ≈1s < 冷却 2.5s
    expect(monitor.getTier()).toBe("medium");
  });

  it("滚动均值 > 58fps 且持续数秒后才升一档", () => {
    const monitor = createQualityMonitor();
    let t = feed(monitor, 0, 60, FRAME_30FPS); // → medium
    expect(monitor.getTier()).toBe("medium");
    t = feed(monitor, t, 120, FRAME_60FPS); // 高帧 ≈2s < 4s 保持期
    expect(monitor.getTier()).toBe("medium");
    feed(monitor, t, 300, FRAME_60FPS); // 持续累计 > 4s
    expect(monitor.getTier()).toBe("high");
  });

  it("升档计时被中间帧率打断后重新计时", () => {
    const monitor = createQualityMonitor();
    let t = feed(monitor, 0, 60, FRAME_30FPS); // → medium
    t = feed(monitor, t, 120, FRAME_60FPS); // 高帧 ≈2s，开始计时
    t = feed(monitor, t, 45, FRAME_RECOVER); // 中间帧率把滚动均值拖下 58 → 计时重置
    t = feed(monitor, t, 120, FRAME_60FPS); // 重新持续 ≈2s
    expect(monitor.getTier()).toBe("medium"); // 重新计时未满 4s
    feed(monitor, t, 300, FRAME_60FPS); // 重新计时累计 > 4s
    expect(monitor.getTier()).toBe("high");
  });

  it("自动降档时通知订阅者，退订后不再通知", () => {
    const monitor = createQualityMonitor();
    const listener = vi.fn();
    const unsubscribe = monitor.subscribe(listener);
    const t = feed(monitor, 0, 60, FRAME_30FPS); // → medium，通知一次
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    feed(monitor, t, 200, FRAME_30FPS); // → low，不再通知
    expect(listener).toHaveBeenCalledTimes(1);
    expect(monitor.getTier()).toBe("low");
  });
});

describe("手动覆盖", () => {
  it("覆盖锁定档位，不受 fps 影响", () => {
    const monitor = createQualityMonitor();
    monitor.setOverride("low");
    expect(monitor.getTier()).toBe("low");
    feed(monitor, 0, 600, FRAME_60FPS); // 10s 高帧也不得升档
    expect(monitor.getTier()).toBe("low");
  });

  it("清除覆盖后回到自动档", () => {
    const monitor = createQualityMonitor();
    feed(monitor, 0, 60, FRAME_30FPS); // 自动 → medium
    monitor.setOverride("high");
    expect(monitor.getTier()).toBe("high");
    monitor.setOverride(null);
    expect(monitor.getTier()).toBe("medium");
  });

  it("覆盖到相同档位不重复通知订阅者", () => {
    const monitor = createQualityMonitor();
    const listener = vi.fn();
    monitor.subscribe(listener);
    monitor.setOverride("high"); // 与当前一致
    expect(listener).not.toHaveBeenCalled();
    monitor.setOverride("medium");
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("setOverride 对未知档位抛 RangeError", () => {
    const monitor = createQualityMonitor();
    expect(() => monitor.setOverride("ultra" as QualityTier)).toThrow(RangeError);
  });
});

describe("prefers-reduced-motion", () => {
  it("开启后强制 low，即使手动覆盖 high", () => {
    const monitor = createQualityMonitor();
    monitor.setOverride("high");
    monitor.setReducedMotion(true);
    expect(monitor.getTier()).toBe("low");
    expect(monitor.getTierSpec().particleCount).toBe(800);
  });

  it("reduced-motion 期间忽略帧数据，解除后恢复自动档", () => {
    const monitor = createQualityMonitor();
    monitor.setReducedMotion(true);
    feed(monitor, 0, 300, FRAME_30FPS); // 全部忽略，auto 不得降级
    expect(monitor.getTier()).toBe("low");
    monitor.setReducedMotion(false);
    expect(monitor.getTier()).toBe("high");
  });

  it("构造时即可指定 reduced-motion 初始态", () => {
    const monitor = createQualityMonitor({ reducedMotion: true });
    expect(monitor.getTier()).toBe("low");
  });
});

describe("M21.7 cinematic 画质分档扩展", () => {
  it("cinematic 三档粒子数 8000 / 4000 / 2000（音乐模式放宽，D21.3）", () => {
    expect(CINEMATIC_QUALITY_TIERS.map((s) => s.tier)).toEqual([
      "cinematic_high",
      "cinematic_medium",
      "cinematic_low",
    ]);
    expect(getTierSpec("cinematic_high").particleCount).toBe(8000);
    expect(getTierSpec("cinematic_medium").particleCount).toBe(4000);
    expect(getTierSpec("cinematic_low").particleCount).toBe(2000);
  });

  it("cinematic_high 粒子数 8000 > normal high 粒子数 4000（音乐模式放宽上限）", () => {
    expect(getTierSpec("cinematic_high").particleCount).toBeGreaterThan(
      getTierSpec("high").particleCount,
    );
  });

  it("cinematic_low 粒子数 2000 > normal low 粒子数 800（音乐模式最低档仍保场面感）", () => {
    expect(getTierSpec("cinematic_low").particleCount).toBeGreaterThan(
      getTierSpec("low").particleCount,
    );
  });

  it("cinematic 档抗锯齿与像素比配置完整（high/medium 开 AA，low 关 AA）", () => {
    expect(getTierSpec("cinematic_high").antialias).toBe(true);
    expect(getTierSpec("cinematic_medium").antialias).toBe(true);
    expect(getTierSpec("cinematic_low").antialias).toBe(false);
    expect(getTierSpec("cinematic_low").pixelRatioCap).toBeLessThanOrEqual(
      getTierSpec("cinematic_high").pixelRatioCap,
    );
  });

  it("getTierSpec 接受所有 6 档（normal + cinematic），未知档仍抛 RangeError", () => {
    const allTiers: QualityTierName[] = [
      "high",
      "medium",
      "low",
      "cinematic_high",
      "cinematic_medium",
      "cinematic_low",
    ];
    for (const tier of allTiers) {
      expect(() => getTierSpec(tier)).not.toThrow();
    }
    expect(() => getTierSpec("ultra" as QualityTierName)).toThrow(RangeError);
    expect(() => getTierSpec("cinematic" as QualityTierName)).toThrow(RangeError);
  });

  it("isCinematicTier 正确区分 normal / cinematic 档", () => {
    expect(isCinematicTier("cinematic_high")).toBe(true);
    expect(isCinematicTier("cinematic_medium")).toBe(true);
    expect(isCinematicTier("cinematic_low")).toBe(true);
    expect(isCinematicTier("high")).toBe(false);
    expect(isCinematicTier("medium")).toBe(false);
    expect(isCinematicTier("low")).toBe(false);
  });

  it("toCinematicTier 把 normal 档映射到同级别 cinematic 档", () => {
    expect(toCinematicTier("high")).toBe("cinematic_high");
    expect(toCinematicTier("medium")).toBe("cinematic_medium");
    expect(toCinematicTier("low")).toBe("cinematic_low");
  });

  it("toCinematicTier 对已是 cinematic 的档幂等返回原档", () => {
    expect(toCinematicTier("cinematic_high")).toBe("cinematic_high");
    expect(toCinematicTier("cinematic_medium")).toBe("cinematic_medium");
    expect(toCinematicTier("cinematic_low")).toBe("cinematic_low");
  });

  it("toNormalTier 把 cinematic 档映射回同级别 normal 档", () => {
    expect(toNormalTier("cinematic_high")).toBe("high");
    expect(toNormalTier("cinematic_medium")).toBe("medium");
    expect(toNormalTier("cinematic_low")).toBe("low");
  });

  it("toNormalTier 对已是 normal 的档幂等返回原档", () => {
    expect(toNormalTier("high")).toBe("high");
    expect(toNormalTier("medium")).toBe("medium");
    expect(toNormalTier("low")).toBe("low");
  });

  it("M22.4 toCinematicTier 把 wallpaper 档映射到 cinematic_low（低功耗语义对齐）", () => {
    // 壁纸档不在 normal 三档内，但同样为低功耗语义——映射到 cinematic_low
    // 让音乐模式接入住壁纸态时取最低 cinematic 档（粒子≤2000，与 wallpaper 一致）
    expect(toCinematicTier("wallpaper")).toBe("cinematic_low");
  });

  it("M22.4 toNormalTier 把 wallpaper 档映射到 low（低功耗语义对齐）", () => {
    // 壁纸档不在 normal 三档内，但同样为低功耗语义——映射到 low
    // 让壁纸态退出后回退到 normal 低档（粒子 800，与 wallpaper 2000 同档量级）
    expect(toNormalTier("wallpaper")).toBe("low");
  });

  it("QUALITY_TIERS 仍只含 3 normal 档（auto-stepping 不跨入 cinematic）", () => {
    expect(QUALITY_TIERS).toHaveLength(3);
    expect(QUALITY_TIERS.every((s) => !isCinematicTier(s.tier))).toBe(true);
  });

  it("cinematic 档作为手动覆盖：setOverride('cinematic_high') 锁定，不受 fps 影响", () => {
    const monitor = createQualityMonitor();
    monitor.setOverride("cinematic_high");
    expect(monitor.getTier()).toBe("cinematic_high");
    expect(monitor.getTierSpec().particleCount).toBe(8000);
    // 即使低帧率也不降档（覆盖锁定）
    feed(monitor, 0, 600, FRAME_30FPS);
    expect(monitor.getTier()).toBe("cinematic_high");
  });

  it("cinematic 覆盖清除后回到自动档（normal high）", () => {
    const monitor = createQualityMonitor();
    monitor.setOverride("cinematic_high");
    monitor.setOverride(null);
    expect(monitor.getTier()).toBe("high");
    expect(isCinematicTier(monitor.getTier())).toBe(false);
  });

  it("reduced-motion 强制 low，即使覆盖 cinematic_high（光敏防护优先）", () => {
    const monitor = createQualityMonitor();
    monitor.setOverride("cinematic_high");
    monitor.setReducedMotion(true);
    expect(monitor.getTier()).toBe("low");
    expect(monitor.getTierSpec().particleCount).toBe(800);
  });

  it("cinematic 档订阅通知：覆盖切换触发 listener", () => {
    const monitor = createQualityMonitor();
    const listener = vi.fn();
    monitor.subscribe(listener);
    monitor.setOverride("cinematic_high");
    expect(listener).toHaveBeenCalledWith("cinematic_high");
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("cinematic 档切换通知订阅者后，切回 normal 也通知", () => {
    const monitor = createQualityMonitor();
    monitor.setOverride("cinematic_medium");
    const listener = vi.fn();
    monitor.subscribe(listener);
    monitor.setOverride("medium");
    expect(listener).toHaveBeenCalledWith("medium");
  });
});

describe("M22.4 壁纸模式画质档", () => {
  it("wallpaper 档粒子数 2000（≤2000 红线，M22.4 spec）", () => {
    expect(getTierSpec("wallpaper").particleCount).toBe(2000);
    expect(getTierSpec("wallpaper").particleCount).toBeLessThanOrEqual(2000);
  });

  it("wallpaper 档关闭抗锯齿 + 像素比钳到 1（保帧率优先）", () => {
    expect(getTierSpec("wallpaper").antialias).toBe(false);
    expect(getTierSpec("wallpaper").pixelRatioCap).toBe(1);
  });

  it("getTierSpec 接受 wallpaper 档", () => {
    expect(() => getTierSpec("wallpaper")).not.toThrow();
  });

  it("isWallpaperTier 正确识别 wallpaper 档", () => {
    expect(isWallpaperTier("wallpaper")).toBe(true);
    expect(isWallpaperTier("high")).toBe(false);
    expect(isWallpaperTier("cinematic_high")).toBe(false);
    expect(isWallpaperTier("low")).toBe(false);
  });

  it("setWallpaperMode(true) 强制 wallpaper 档，不受 fps 影响", () => {
    const monitor = createQualityMonitor();
    monitor.setWallpaperMode(true);
    expect(monitor.getTier()).toBe("wallpaper");
    expect(monitor.getTierSpec().particleCount).toBe(2000);
    // 即使低帧率也不降档（壁纸模式锁定）
    feed(monitor, 0, 600, FRAME_30FPS);
    expect(monitor.getTier()).toBe("wallpaper");
  });

  it("setWallpaperMode(false) 解除后回到自动档", () => {
    const monitor = createQualityMonitor();
    monitor.setWallpaperMode(true);
    monitor.setWallpaperMode(false);
    expect(monitor.getTier()).toBe("high");
    expect(isWallpaperTier(monitor.getTier())).toBe(false);
  });

  it("wallpaper 模式期间忽略帧数据，解除后恢复自动档", () => {
    const monitor = createQualityMonitor();
    monitor.setWallpaperMode(true);
    feed(monitor, 0, 300, FRAME_30FPS); // 全部忽略
    expect(monitor.getTier()).toBe("wallpaper");
    monitor.setWallpaperMode(false);
    expect(monitor.getTier()).toBe("high"); // auto 未降级
  });

  it("reduced-motion 优先级高于 wallpaper（光敏防护最优先）", () => {
    const monitor = createQualityMonitor();
    monitor.setWallpaperMode(true);
    monitor.setReducedMotion(true);
    expect(monitor.getTier()).toBe("low");
    expect(monitor.getTierSpec().particleCount).toBe(800);
  });

  it("wallpaper 模式切换触发订阅通知", () => {
    const monitor = createQualityMonitor();
    const listener = vi.fn();
    monitor.subscribe(listener);
    monitor.setWallpaperMode(true);
    expect(listener).toHaveBeenCalledWith("wallpaper");
    expect(listener).toHaveBeenCalledTimes(1);
    monitor.setWallpaperMode(false);
    expect(listener).toHaveBeenCalledWith("high");
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("setWallpaperMode 幂等：同值不重复通知", () => {
    const monitor = createQualityMonitor();
    const listener = vi.fn();
    monitor.subscribe(listener);
    monitor.setWallpaperMode(true);
    monitor.setWallpaperMode(true);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("构造时即可指定 wallpaper 初始态", () => {
    const monitor = createQualityMonitor({ wallpaperMode: true });
    expect(monitor.getTier()).toBe("wallpaper");
  });
});
