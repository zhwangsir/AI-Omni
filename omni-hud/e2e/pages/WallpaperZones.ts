/**
 * WallpaperZones Page Object（M22 壁纸模式 E2E）。
 *
 * 封装对 WallpaperZones 组件（src/components/WallpaperZones.tsx）的查询与交互：
 * - data-testid="wallpaper-wake-zone"：全屏透明双击唤醒区（onDoubleClick → onWake）
 * - data-testid="wallpaper-control-bar"：右下角控制条（240×60）
 * - data-testid="wallpaper-exit-button"：退出壁纸模式按钮
 * - data-testid="wallpaper-left-edge"：左边缘触发条
 * - data-testid="wallpaper-right-edge"：右边缘触发条
 *
 * 挂载契约（WallpaperZones.tsx:77）：仅 wallpaperMode=true 时挂载全部分区，
 * false 时组件返回 null，全部分区卸载。
 *
 * 唤醒浮出契约（hudStore.ts wakeWallpaper/sleepWallpaper）：
 * - 双击 wake-zone → onWake → store.wakeWallpaper() → wallpaperAwake=true +
 *   wallpaperAwakeSeq 自增
 * - App.tsx useEffect 监听 wallpaperAwake + wallpaperAwakeSeq：true 时启动 2s
 *   计时器，到期调 sleepWallpaper() 渐回壁纸态
 * - 重复双击 → seq 再次自增 → effect 重跑 → 旧计时器清除、新计时器起算（重置 2s 倒计时）
 *
 * windowMode 推导（App.tsx:92-97）：
 * - wallpaperMode=true + voiceWindowMode=mini + !wallpaperAwake → "wallpaper"
 * - wallpaperMode=true + voiceWindowMode=mini + wallpaperAwake → "full"（浮出）
 * - 其他情况沿用 voiceWindowMode
 */
import { expect, type Page, type Locator } from "@playwright/test";

/** 双击唤醒区选择器。 */
export const WALLPAPER_WAKE_ZONE_SELECTOR = '[data-testid="wallpaper-wake-zone"]';
/** 控制条选择器。 */
export const WALLPAPER_CONTROL_BAR_SELECTOR = '[data-testid="wallpaper-control-bar"]';
/** 退出壁纸模式按钮选择器。 */
export const WALLPAPER_EXIT_BUTTON_SELECTOR = '[data-testid="wallpaper-exit-button"]';

/** 唤醒浮出后 2s 自动渐回（App.tsx setTimeout 2000ms）。 */
export const WALLPAPER_AWAKE_TIMEOUT_MS = 2000;

export class WallpaperZonesPage {
  readonly page: Page;
  readonly wakeZone: Locator;
  readonly controlBar: Locator;
  readonly exitButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.wakeZone = page.locator(WALLPAPER_WAKE_ZONE_SELECTOR);
    this.controlBar = page.locator(WALLPAPER_CONTROL_BAR_SELECTOR);
    this.exitButton = page.locator(WALLPAPER_EXIT_BUTTON_SELECTOR);
  }

  /** 等待双击唤醒区挂载（wallpaperMode=true 时）。 */
  async waitForMounted(timeout = 5_000): Promise<void> {
    await this.wakeZone.waitFor({ state: "attached", timeout });
  }

  /** 等待双击唤醒区卸载（退出壁纸模式后）。 */
  async waitForUnmounted(timeout = 5_000): Promise<void> {
    await this.wakeZone.waitFor({ state: "detached", timeout });
  }

  /**
   * 双击唤醒区触发 onWake 回调（store.wakeWallpaper）。
   *
   * WallpaperZones.tsx:86 onDoubleClick={onWake}，使用 Playwright dblclick
   * 派发原生 dblclick 事件（React 委托监听 dblclick 冒泡）。
   */
  async doubleClickWake(): Promise<void> {
    await this.wakeZone.dblclick();
  }

  /** 点击退出壁纸模式按钮（control-bar 内的 exit-button）。 */
  async clickExit(): Promise<void> {
    await this.exitButton.click();
  }

  /**
   * 读取当前 hudStore.wallpaperAwake 状态（经 __omniDebug 或 DOM 间接推断）。
   *
   * App.tsx 推导：wallpaperAwake=true 时 windowMode=full（浮出），
   * wallpaperAwake=false 时 windowMode=wallpaper（沉到桌面图标层）。
   * 通过 hud-root 的 data-window-mode 属性间接断言：
   * - "full" → wallpaperAwake=true（浮出态）
   * - "wallpaper" → wallpaperAwake=false（沉态）
   */
  async isAwake(): Promise<boolean> {
    const attr = await this.page
      .locator('[data-testid="hud-root"]')
      .getAttribute("data-window-mode");
    return attr === "full";
  }
}
