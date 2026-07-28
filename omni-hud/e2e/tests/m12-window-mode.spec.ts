/**
 * M12 灵动岛双形态 E2E 测试（6 用例）。
 *
 * 覆盖维度：
 * 1. voice.windowMode=mini → hud-root-mini class + MiniBar 渲染 + 状态文字
 * 2. voice.windowMode=full → data-window-mode="full" + Full 布局（无 MiniBar）
 * 3. voice.windowMode=null → 默认推导为 full（安全态）
 * 4. mini → full 切换时 set_window_mode IPC 被调用（每次 windowMode 变化触发）
 * 5. Ctrl+Shift+W 切换壁纸模式（hudStore.toggleWallpaperMode）
 * 6. wallpaperMode + idle → wallpaper 形态（voiceWindowMode=mini + !awake → wallpaper）
 *
 * 路由策略：
 * - 全部经 fakeTauri.emit(VOICE_STATUS_EVENT, fixture) 推送 voice-status 事件
 * - set_window_mode IPC 调用经 fakeTauri.callsFor 断言
 * - 壁纸模式经 Ctrl+Shift+W 快捷键触发（App.tsx:158 keydown handler）
 *
 * 推导逻辑（App.tsx:91-97）：
 *   voiceWindowMode = statusSnapshot.voice.windowMode ?? "full"
 *   windowMode = state.wallpaperMode && voiceWindowMode === "mini"
 *     ? (state.wallpaperAwake ? "full" : "wallpaper")
 *     : voiceWindowMode
 */
import { test, expect } from "../support/fixture";
import { VOICE_STATUS_EVENT, CMD } from "../support/env";
import { HudApp } from "../pages/HudApp";
import { MiniBarPage, MINI_BAR_STATE_LABEL } from "../pages/MiniBar";
import {
  VOICE_IDLE,
  VOICE_WAKE_LISTENING,
  VOICE_SPEAKING,
} from "../fixtures/voice";

test.describe("M12 灵动岛双形态", () => {
  test("voice.windowMode=mini → hud-root-mini class + MiniBar 渲染状态文字", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const mini = new MiniBarPage(appPage);

    // VOICE_IDLE 的 windowMode=mini（fixture voice.ts:67）
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_IDLE);
    await hud.waitForVoiceState("idle");

    // mini 形态：hud-root-mini class 存在，data-window-mode 属性缺省
    expect(await hud.isMiniMode()).toBe(true);
    expect(await hud.getWindowMode()).toBeNull();

    // MiniBar 挂载并显示 idle 中文状态文字
    await mini.waitForMounted();
    await mini.waitForStatusText(MINI_BAR_STATE_LABEL.idle);
  });

  test("voice.windowMode=full → data-window-mode=full + Full 布局（无 MiniBar）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const mini = new MiniBarPage(appPage);

    // VOICE_SPEAKING 的 windowMode=full
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING);
    await hud.waitForVoiceState("speaking");

    // full 形态：data-window-mode="full"，hud-root-mini class 不存在
    await hud.waitForWindowMode("full");
    expect(await hud.isMiniMode()).toBe(false);

    // MiniBar 在 full 形态下不挂载（App.tsx:282 if windowMode === "mini" 分支跳过）
    await mini.waitForUnmounted();
  });

  test("voice.windowMode=null → 默认推导为 full（安全态）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    // 显式构造 windowMode:null 的 speaking 负载
    fakeTauri.emit(VOICE_STATUS_EVENT, { ...VOICE_SPEAKING, windowMode: null });
    await hud.waitForVoiceState("speaking");
    // null → App.tsx voiceWindowMode = windowMode ?? "full" → data-window-mode="full"
    await hud.waitForWindowMode("full");
    expect(await hud.isMiniMode()).toBe(false);
  });

  test("mini → full 切换时 set_window_mode IPC 被调用", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    // 清空之前的 calls（挂载阶段已触发一次 set_window_mode）
    // 通过记录当前 calls 数量作为基线
    const baselineCalls = fakeTauri.callsFor(CMD.SET_WINDOW_MODE).length;

    // 先进入 mini（idle → windowMode=mini）
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_IDLE);
    await hud.waitForVoiceState("idle");
    expect(await hud.isMiniMode()).toBe(true);

    // 切到 full（wake_listening → windowMode=full）
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_WAKE_LISTENING);
    await hud.waitForVoiceState("wake_listening");
    await hud.waitForWindowMode("full");

    // App.tsx:107 useEffect 依赖 windowMode，每次变化调用 invoke("set_window_mode", {mode})
    // mini→full 至少触发一次 set_window_mode（mode="full"）
    await expect
      .poll(() => fakeTauri.callsFor(CMD.SET_WINDOW_MODE).length)
      .toBeGreaterThan(baselineCalls);

    // 验证最后一次调用的 mode 参数为 "full"
    const calls = fakeTauri.callsFor(CMD.SET_WINDOW_MODE);
    const lastCall = calls[calls.length - 1];
    expect(lastCall.command).toBe(CMD.SET_WINDOW_MODE);
    expect(lastCall.args).toMatchObject({ mode: "full" });
  });

  test("Ctrl+Shift+W 切换壁纸模式（hudStore.toggleWallpaperMode）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);

    // 初始：默认非壁纸模式（voice idle → mini，但 hudStore.wallpaperMode=false → windowMode=mini）
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_IDLE);
    await hud.waitForVoiceState("idle");
    expect(await hud.isMiniMode()).toBe(true);
    expect(await hud.isWallpaperMode()).toBe(false);

    // Ctrl+Shift+W → toggleWallpaperMode() → wallpaperMode=true
    // voiceWindowMode=mini + wallpaperMode=true + !awake → windowMode="wallpaper"
    await hud.pressCtrlShiftW();

    // 进入壁纸形态：hud-root-wallpaper class 存在，data-window-mode="wallpaper"
    await expect
      .poll(async () => await hud.isWallpaperMode())
      .toBe(true);
    await hud.waitForWindowMode("wallpaper");

    // 再次 Ctrl+Shift+W → toggleWallpaperMode() → wallpaperMode=false
    // 回到 voiceWindowMode=mini → windowMode=mini
    await hud.pressCtrlShiftW();
    await expect
      .poll(async () => await hud.isWallpaperMode())
      .toBe(false);
    expect(await hud.isMiniMode()).toBe(true);
  });

  test("wallpaperMode + idle → wallpaper 形态（voiceWindowMode=mini 推导）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);

    // 先进入 idle（voiceWindowMode=mini），再切壁纸模式
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_IDLE);
    await hud.waitForVoiceState("idle");
    expect(await hud.isMiniMode()).toBe(true);

    // Ctrl+Shift+W 进入壁纸模式
    // 推导：wallpaperMode=true && voiceWindowMode==="mini" && !awake → "wallpaper"
    await hud.pressCtrlShiftW();
    await hud.waitForWindowMode("wallpaper");
    expect(await hud.isWallpaperMode()).toBe(true);

    // 验证壁纸形态下仍有 data-window-mode="wallpaper"
    expect(await hud.getWindowMode()).toBe("wallpaper");

    // 切回 full（活跃态）：emit wake_listening（windowMode=full）
    // 推导：wallpaperMode=true && voiceWindowMode==="full" → "full"（活跃态自动浮出）
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_WAKE_LISTENING);
    await hud.waitForVoiceState("wake_listening");
    await hud.waitForWindowMode("full");
  });
});
