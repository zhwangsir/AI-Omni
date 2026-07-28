/**
 * hudStore 测试（M7.2 重写，M7.4 扩展 sleeping）：穿透状态机退役后的全局状态。
 * M7.1 起点击穿透由 Rust 分区轮询拥有（set_interactive_zones），
 * 前端 hover 切换窗口级穿透的 mode 状态机随之退役；store 收窄为全局动效开关
 * + 睡眠态标记（M7.4：睡眠 = 场近零 + zones 只留声井）。
 */
import { describe, expect, it, vi } from "vitest";

import { createHudStore } from "../store/hudStore";

describe("HUD 全局状态（M7.2）", () => {
  it("初始 reducedMotion 为 false", () => {
    const store = createHudStore();
    expect(store.getState().reducedMotion).toBe(false);
  });

  it("穿透切换 API 已退役：不再暴露 enterInteractive / leaveInteractive", () => {
    const store = createHudStore();
    expect("enterInteractive" in store).toBe(false);
    expect("leaveInteractive" in store).toBe(false);
  });

  it("setReducedMotion 更新状态且幂等（同值不重复通知）", () => {
    const store = createHudStore();
    const listener = vi.fn();
    store.subscribe(listener);
    store.setReducedMotion(true);
    expect(store.getState().reducedMotion).toBe(true);
    store.setReducedMotion(true);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("状态变化通知订阅者，退订后不再通知", () => {
    const store = createHudStore();
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    store.setReducedMotion(true);
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    store.setReducedMotion(false);
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe("HUD 睡眠态（M7.4）", () => {
  it("初始 sleeping 为 false（唤醒态）", () => {
    const store = createHudStore();
    expect(store.getState().sleeping).toBe(false);
  });

  it("setSleeping(true) 切到睡眠态，幂等同值不重复通知", () => {
    const store = createHudStore();
    const listener = vi.fn();
    store.subscribe(listener);
    store.setSleeping(true);
    expect(store.getState().sleeping).toBe(true);
    store.setSleeping(true);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("setSleeping(false) 唤醒：通知订阅者", () => {
    const store = createHudStore();
    store.setSleeping(true);
    const listener = vi.fn();
    store.subscribe(listener);
    store.setSleeping(false);
    expect(store.getState().sleeping).toBe(false);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("sleeping 与 reducedMotion 独立：切换互不影响", () => {
    const store = createHudStore();
    store.setReducedMotion(true);
    store.setSleeping(true);
    expect(store.getState()).toEqual({
      reducedMotion: true,
      sleeping: true,
      fieldMode: "space",
      cinemaMode: "off",
      wallpaperMode: false,
      wallpaperAwake: false,
      wallpaperAwakeSeq: 0,
    });
    store.setSleeping(false);
    expect(store.getState().reducedMotion).toBe(true);
    expect(store.getState().sleeping).toBe(false);
  });

  it("toggleSleeping 在睡眠/唤醒间翻转，返回切换后的状态", () => {
    const store = createHudStore();
    expect(store.toggleSleeping()).toBe(true);
    expect(store.getState().sleeping).toBe(true);
    expect(store.toggleSleeping()).toBe(false);
    expect(store.getState().sleeping).toBe(false);
  });
});

describe("HUD 场景模式（M20.6 fieldMode: space/shelf）", () => {
  it("初始 fieldMode 为 space（默认显影场）", () => {
    const store = createHudStore();
    expect(store.getState().fieldMode).toBe("space");
  });

  it("setFieldMode('shelf') 切到卡片架模式，幂等同值不重复通知", () => {
    const store = createHudStore();
    const listener = vi.fn();
    store.subscribe(listener);
    store.setFieldMode("shelf");
    expect(store.getState().fieldMode).toBe("shelf");
    store.setFieldMode("shelf");
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("setFieldMode('space') 切回显影场，通知订阅者", () => {
    const store = createHudStore();
    store.setFieldMode("shelf");
    const listener = vi.fn();
    store.subscribe(listener);
    store.setFieldMode("space");
    expect(store.getState().fieldMode).toBe("space");
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("toggleFieldMode 在 space/shelf 间翻转，返回切换后的模式", () => {
    const store = createHudStore();
    expect(store.toggleFieldMode()).toBe("shelf");
    expect(store.getState().fieldMode).toBe("shelf");
    expect(store.toggleFieldMode()).toBe("space");
    expect(store.getState().fieldMode).toBe("space");
  });

  it("fieldMode 与 sleeping/reducedMotion 独立：切换互不影响", () => {
    const store = createHudStore();
    store.setReducedMotion(true);
    store.setSleeping(true);
    store.setFieldMode("shelf");
    expect(store.getState()).toEqual({
      reducedMotion: true,
      sleeping: true,
      fieldMode: "shelf",
      cinemaMode: "off",
      wallpaperMode: false,
      wallpaperAwake: false,
      wallpaperAwakeSeq: 0,
    });
    store.setFieldMode("space");
    expect(store.getState().reducedMotion).toBe(true);
    expect(store.getState().sleeping).toBe(true);
    expect(store.getState().fieldMode).toBe("space");
  });
});

describe("HUD 电影镜头模式（M21.4 cinemaMode: off/calm/standard/intense）", () => {
  it("初始 cinemaMode 为 off（不启用电影镜头）", () => {
    const store = createHudStore();
    expect(store.getState().cinemaMode).toBe("off");
  });

  it("setCinemaMode('calm') 切到 calm，幂等同值不重复通知", () => {
    const store = createHudStore();
    const listener = vi.fn();
    store.subscribe(listener);
    store.setCinemaMode("calm");
    expect(store.getState().cinemaMode).toBe("calm");
    store.setCinemaMode("calm");
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("setCinemaMode('intense') 切到 intense，通知订阅者", () => {
    const store = createHudStore();
    const listener = vi.fn();
    store.subscribe(listener);
    store.setCinemaMode("intense");
    expect(store.getState().cinemaMode).toBe("intense");
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("setCinemaMode('off') 切回 off，通知订阅者", () => {
    const store = createHudStore();
    store.setCinemaMode("standard");
    const listener = vi.fn();
    store.subscribe(listener);
    store.setCinemaMode("off");
    expect(store.getState().cinemaMode).toBe("off");
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("cinemaMode 与 fieldMode/sleeping/reducedMotion 独立：切换互不影响", () => {
    const store = createHudStore();
    store.setReducedMotion(true);
    store.setSleeping(true);
    store.setFieldMode("shelf");
    store.setCinemaMode("intense");
    expect(store.getState()).toEqual({
      reducedMotion: true,
      sleeping: true,
      fieldMode: "shelf",
      cinemaMode: "intense",
      wallpaperMode: false,
      wallpaperAwake: false,
      wallpaperAwakeSeq: 0,
    });
    // 切回其他模式不影响 cinemaMode
    store.setFieldMode("space");
    store.setSleeping(false);
    expect(store.getState().cinemaMode).toBe("intense");
  });
});

describe("HUD 壁纸模式（M22.2 wallpaperMode）", () => {
  it("初始 wallpaperMode 为 false（不沉到桌面图标层）", () => {
    const store = createHudStore();
    expect(store.getState().wallpaperMode).toBe(false);
  });

  it("setWallpaperMode(true) 切到壁纸模式，幂等同值不重复通知", () => {
    const store = createHudStore();
    const listener = vi.fn();
    store.subscribe(listener);
    store.setWallpaperMode(true);
    expect(store.getState().wallpaperMode).toBe(true);
    store.setWallpaperMode(true);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("setWallpaperMode(false) 切回正常模式，通知订阅者", () => {
    const store = createHudStore();
    store.setWallpaperMode(true);
    const listener = vi.fn();
    store.subscribe(listener);
    store.setWallpaperMode(false);
    expect(store.getState().wallpaperMode).toBe(false);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("toggleWallpaperMode 在正常/壁纸间翻转，返回切换后的状态", () => {
    const store = createHudStore();
    expect(store.toggleWallpaperMode()).toBe(true);
    expect(store.getState().wallpaperMode).toBe(true);
    expect(store.toggleWallpaperMode()).toBe(false);
    expect(store.getState().wallpaperMode).toBe(false);
  });

  it("wallpaperMode 与 sleeping/fieldMode/cinemaMode/reducedMotion 独立：切换互不影响", () => {
    const store = createHudStore();
    store.setReducedMotion(true);
    store.setSleeping(true);
    store.setFieldMode("shelf");
    store.setCinemaMode("intense");
    store.setWallpaperMode(true);
    expect(store.getState()).toEqual({
      reducedMotion: true,
      sleeping: true,
      fieldMode: "shelf",
      cinemaMode: "intense",
      wallpaperMode: true,
      wallpaperAwake: false,
      wallpaperAwakeSeq: 0,
    });
    // 切回其他模式不影响 wallpaperMode
    store.setFieldMode("space");
    store.setSleeping(false);
    store.setCinemaMode("off");
    expect(store.getState().wallpaperMode).toBe(true);
  });
});

describe("HUD 壁纸模式唤醒浮出（M22.5 wallpaperAwake）", () => {
  it("初始 wallpaperAwake 为 false（壁纸态不浮出）", () => {
    const store = createHudStore();
    expect(store.getState().wallpaperAwake).toBe(false);
  });

  it("wakeWallpaper() 每次自增 seq 并通知（支持重复双击重置 2s 计时器）", () => {
    // wakeWallpaper 不做幂等短路：每次调用自增 wallpaperAwakeSeq + 通知，
    // 以驱动 App.tsx 的 2s 渐回计时器 effect 重跑（重复双击重置倒计时）。
    const store = createHudStore();
    const listener = vi.fn();
    store.subscribe(listener);
    store.wakeWallpaper();
    expect(store.getState().wallpaperAwake).toBe(true);
    expect(store.getState().wallpaperAwakeSeq).toBe(1);
    store.wakeWallpaper(); // 重复唤醒：seq 自增 + 再通知
    expect(listener).toHaveBeenCalledTimes(2);
    expect(store.getState().wallpaperAwakeSeq).toBe(2);
  });

  it("sleepWallpaper() 切回沉态，通知订阅者", () => {
    const store = createHudStore();
    store.wakeWallpaper();
    const listener = vi.fn();
    store.subscribe(listener);
    store.sleepWallpaper();
    expect(store.getState().wallpaperAwake).toBe(false);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("sleepWallpaper 幂等：已沉态不重复通知", () => {
    const store = createHudStore();
    const listener = vi.fn();
    store.subscribe(listener);
    store.sleepWallpaper();
    expect(listener).not.toHaveBeenCalled();
  });

  it("退出壁纸模式（setWallpaperMode(false)）时同步清除 wallpaperAwake", () => {
    // 唤醒浮出态下用户退出壁纸模式 → wallpaperAwake 必须同步清零，
    // 避免下次进入壁纸模式时残留 awake 态（窗口直接浮出不沉）
    const store = createHudStore();
    store.setWallpaperMode(true);
    store.wakeWallpaper();
    expect(store.getState().wallpaperAwake).toBe(true);
    store.setWallpaperMode(false);
    expect(store.getState().wallpaperAwake).toBe(false);
  });

  it("wallpaperAwake 与 wallpaperMode 独立：可单独切换 awake 而不改 mode", () => {
    const store = createHudStore();
    store.setWallpaperMode(true);
    store.wakeWallpaper();
    expect(store.getState()).toEqual({
      reducedMotion: false,
      sleeping: false,
      fieldMode: "space",
      cinemaMode: "off",
      wallpaperMode: true,
      wallpaperAwake: true,
      wallpaperAwakeSeq: 1,
    });
    store.sleepWallpaper();
    expect(store.getState().wallpaperMode).toBe(true);
    expect(store.getState().wallpaperAwake).toBe(false);
  });
});
