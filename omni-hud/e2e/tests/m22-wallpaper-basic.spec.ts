/**
 * M22 壁纸模式基础 E2E 测试（4 用例）。
 *
 * 覆盖维度：
 * 1. Ctrl+Shift+W 进入壁纸模式 → hud-root-wallpaper class + data-window-mode="wallpaper"
 * 2. 壁纸模式下双击 → wallpaperAwake=true → 浮出（windowMode=full）
 * 3. 唤醒后 2s 无交互 → 自动渐回壁纸态（App.tsx setTimeout 2000ms → sleepWallpaper）
 * 4. 重复双击重置 2s 计时器（wallpaperAwakeSeq 自增触发 effect 重跑）
 *
 * 推导逻辑（App.tsx:92-97）：
 *   voiceWindowMode = statusSnapshot.voice.windowMode ?? "full"
 *   windowMode = state.wallpaperMode && voiceWindowMode === "mini"
 *     ? (state.wallpaperAwake ? "full" : "wallpaper")
 *     : voiceWindowMode
 *
 * 唤醒浮出契约（hudStore.ts wakeWallpaper/sleepWallpaper）：
 * - 双击 wake-zone → store.wakeWallpaper() → wallpaperAwake=true + seq 自增
 * - App.tsx useEffect 监听 wallpaperAwake + seq：true 时启动 2s 计时器
 * - 到期调 sleepWallpaper() → wallpaperAwake=false → windowMode 回 "wallpaper"
 * - 重复双击 → seq 再次自增 → effect 重跑 → 旧计时器清除、新计时器起算
 *
 * 前置条件：壁纸模式需 voiceWindowMode=mini（idle 态）才能进入 wallpaper 形态；
 * 否则 voiceWindowMode=full 时 windowMode 直接为 full，wallpaperMode 不生效。
 */
import { test, expect } from "../support/fixture";
import { VOICE_STATUS_EVENT } from "../support/env";
import { HudApp } from "../pages/HudApp";
import { WallpaperZonesPage, WALLPAPER_AWAKE_TIMEOUT_MS } from "../pages/WallpaperZones";
import { VOICE_IDLE } from "../fixtures/voice";

test.describe("M22 壁纸模式基础", () => {
  test("Ctrl+Shift+W 进入壁纸模式 → hud-root-wallpaper class + data-window-mode=wallpaper", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const wallpaper = new WallpaperZonesPage(appPage);

    // 先进入 idle（voiceWindowMode=mini），壁纸模式才能生效
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_IDLE);
    await hud.waitForVoiceState("idle");
    expect(await hud.isMiniMode()).toBe(true);

    // Ctrl+Shift+W → toggleWallpaperMode() → wallpaperMode=true
    // 推导：wallpaperMode=true && voiceWindowMode==="mini" && !awake → "wallpaper"
    await hud.pressCtrlShiftW();
    await hud.waitForWindowMode("wallpaper");
    expect(await hud.isWallpaperMode()).toBe(true);

    // WallpaperZones 组件挂载（wallpaperMode=true 时渲染全部分区）
    await wallpaper.waitForMounted();
  });

  test("壁纸模式下双击 → wallpaperAwake=true → 浮出（windowMode=full）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const wallpaper = new WallpaperZonesPage(appPage);

    // 进入壁纸模式
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_IDLE);
    await hud.waitForVoiceState("idle");
    await hud.pressCtrlShiftW();
    await hud.waitForWindowMode("wallpaper");
    await wallpaper.waitForMounted();

    // 双击唤醒区 → onWake → store.wakeWallpaper() → wallpaperAwake=true
    // 推导：wallpaperMode=true && voiceWindowMode==="mini" && awake → "full"
    await wallpaper.doubleClickWake();
    await hud.waitForWindowMode("full");
    expect(await wallpaper.isAwake()).toBe(true);
  });

  test("唤醒后 2s 无交互 → 自动渐回壁纸态（sleepWallpaper）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const wallpaper = new WallpaperZonesPage(appPage);

    // 进入壁纸模式 + 唤醒
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_IDLE);
    await hud.waitForVoiceState("idle");
    await hud.pressCtrlShiftW();
    await hud.waitForWindowMode("wallpaper");
    await wallpaper.waitForMounted();
    await wallpaper.doubleClickWake();
    await hud.waitForWindowMode("full");

    // 等待 2s 计时器到期 → sleepWallpaper() → wallpaperAwake=false → windowMode 回 "wallpaper"
    // 留 2s 缓冲覆盖 React 重渲染 + Playwright 轮询
    await hud.waitForWindowMode("wallpaper", WALLPAPER_AWAKE_TIMEOUT_MS + 5_000);
    expect(await wallpaper.isAwake()).toBe(false);
  });

  test("重复双击重置 2s 计时器（wallpaperAwakeSeq 自增）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const wallpaper = new WallpaperZonesPage(appPage);

    // 进入壁纸模式 + 首次唤醒
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_IDLE);
    await hud.waitForVoiceState("idle");
    await hud.pressCtrlShiftW();
    await hud.waitForWindowMode("wallpaper");
    await wallpaper.waitForMounted();
    await wallpaper.doubleClickWake();
    await hud.waitForWindowMode("full");

    // 等待 ~1.5s（接近但未到 2s 计时器到期），再次双击重置计时器
    await appPage.waitForTimeout(1500);
    await wallpaper.doubleClickWake();
    // 仍为 full（awake=true，seq 自增触发 effect 重跑，新计时器起算）
    expect(await wallpaper.isAwake()).toBe(true);

    // 再等 ~1.5s：若计时器未重置，此时已过原始 2s 应渐回 wallpaper；
    // 实际因重置，仍应处于 full（新计时器才过 1.5s < 2s）
    await appPage.waitForTimeout(1500);
    expect(await wallpaper.isAwake()).toBe(true);

    // 再等 1s + 缓冲：新计时器 2s 到期 → sleepWallpaper → 渐回 wallpaper
    await hud.waitForWindowMode("wallpaper", 3_000);
    expect(await wallpaper.isAwake()).toBe(false);
  });
});
