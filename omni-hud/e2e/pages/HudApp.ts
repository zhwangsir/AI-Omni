/**
 * HudApp Page Object：HUD 根组件交互入口（M0-M2 E2E）。
 *
 * 封装对 hud-root 根节点的查询与断言：
 * - data-voice-state 属性：反映 statusStore.voice.state（null → "idle"）
 * - data-window-mode 属性：反映 App.tsx 推导后的最终 windowMode
 * - hud-root-mini class：mini 形态根节点样式钩子
 * - hud-root-wallpaper class：wallpaper 形态根节点样式钩子
 *
 * 同时提供 Ctrl+Shift+W 壁纸模式快捷键、caption-interrupt 点击等跨里程碑
 * 共用的交互动作，避免在 spec 中散落 page.locator(...) 调用。
 */
import { expect, type Page, type Locator } from "@playwright/test";

import type { VoicePipelineState, WindowMode } from "../../src/data/sources";

/** hud-root 根节点选择器。 */
export const HUD_ROOT_SELECTOR = '[data-testid="hud-root"]';

export class HudApp {
  readonly page: Page;
  readonly root: Locator;

  constructor(page: Page) {
    this.page = page;
    this.root = page.locator(HUD_ROOT_SELECTOR);
  }

  /** 读取 data-voice-state 属性（App.tsx:294 voiceState ?? "idle"）。 */
  async getVoiceState(): Promise<string> {
    return (await this.root.getAttribute("data-voice-state")) ?? "idle";
  }

  /** 读取 data-window-mode 属性（仅 full / wallpaper 形态有此属性；mini 形态缺省）。 */
  async getWindowMode(): Promise<WindowMode | null> {
    const attr = await this.root.getAttribute("data-window-mode");
    if (attr === "mini" || attr === "full" || attr === "wallpaper") return attr;
    return null;
  }

  /** 当前是否为 mini 形态（hud-root-mini class 存在）。 */
  async isMiniMode(): Promise<boolean> {
    const className = (await this.root.getAttribute("class")) ?? "";
    return className.includes("hud-root-mini");
  }

  /** 当前是否为 wallpaper 形态（hud-root-wallpaper class 存在）。 */
  async isWallpaperMode(): Promise<boolean> {
    const className = (await this.root.getAttribute("class")) ?? "";
    return className.includes("hud-root-wallpaper");
  }

  /** 等待 data-voice-state 等于目标值。 */
  async waitForVoiceState(state: VoicePipelineState): Promise<void> {
    await expect(this.root).toHaveAttribute("data-voice-state", state);
  }

  /** 等待 data-window-mode 等于目标值（mini 形态无此属性，应用 isMiniMode）。 */
  async waitForWindowMode(mode: WindowMode, timeout = 5_000): Promise<void> {
    await expect(this.root).toHaveAttribute("data-window-mode", mode, { timeout });
  }

  /** 模拟 Ctrl+Shift+W 快捷键（M22.2 切换壁纸模式）。 */
  async pressCtrlShiftW(): Promise<void> {
    await this.page.keyboard.down("Control");
    await this.page.keyboard.down("Shift");
    await this.page.keyboard.press("w");
    await this.page.keyboard.up("Shift");
    await this.page.keyboard.up("Control");
  }

  /**
   * 等待 caption-subtitle 元素挂载并标记为已显影（data-revealed="true"）。
   *
   * CaptionLayer 在 speaking + 新 replySeq 时经 useEffect 调 subtitleStore.begin()
   * → visible=true → 渲染 caption-subtitle + data-revealed="true"。
   * 此方法确保 subtitle 已显影后才进行 hover（否则 hover 的元素不存在或不稳定）。
   */
  async waitForSubtitleRevealed(timeout = 5_000): Promise<void> {
    await this.page
      .locator('[data-testid="caption-subtitle"][data-revealed="true"]')
      .waitFor({ state: "attached", timeout });
  }

  /**
   * 悬停 caption-subtitle 元素以触发 CaptionLayer 的 hovered 状态。
   *
   * CaptionLayer.tsx:156 渲染 caption-interrupt 按钮的条件是
   * `subtitleActive && hovered`——subtitleActive 需要 speaking + subtitle 可见，
   * hovered 需要 pointerenter 事件。spec 在 clickInterrupt / waitForInterruptVisible
   * 前必须先调 waitForSubtitleRevealed + 此方法，否则按钮不会挂载。
   *
   * 使用 dispatchEvent 直接派发 pointerenter 事件：caption-subtitle 有 CSS opacity
   * 过渡（0→1），过渡期间 Playwright 的 hover 视元素为 "animating" 不稳定会超时；
   * force: true 虽绕过稳定性检查，但 React 的 onPointerEnter 合成事件在
   * pointer-events:none 的过渡态下可能不触发。dispatchEvent 直接派发原生事件，
   * React 17+ 通过根委托监听 pointerenter，可靠触发 hovered=true。
   */
  async hoverCaptionSubtitle(): Promise<void> {
    await this.page.evaluate(() => {
      const el = document.querySelector('[data-testid="caption-subtitle"]');
      if (!el) return;
      // React 18 委托 pointerenter/leave 通过监听 pointerover/out（冒泡事件）
      // 在根容器合成。直接 dispatch pointerenter（不冒泡）不会触发 React handler。
      // 正确方式：dispatch pointerover（bubbles=true），React 合成 enter 语义。
      // relatedTarget=null 模拟「从外部进入」。
      el.dispatchEvent(
        new PointerEvent("pointerover", {
          bubbles: true,
          cancelable: true,
          relatedTarget: null,
        }),
      );
      // 也 dispatch mouseover 作为兼容后备（部分浏览器/React 版本经 mouseover 合成）
      el.dispatchEvent(
        new MouseEvent("mouseover", {
          bubbles: true,
          cancelable: true,
          relatedTarget: null,
        }),
      );
    });
  }

  /**
   * 点击 caption-interrupt 按钮触发语音打断。
   *
   * caption-interrupt 仅在 speaking 态 + subtitle 悬停时显示（CaptionLayer.tsx:156
   * 条件 `subtitleActive && hovered`）。调用前 spec 应：
   * 1. emit VOICE_SPEAKING 让 subtitle 挂载
   * 2. 调 hoverCaptionSubtitle() 触发 hovered 状态
   */
  async clickInterrupt(): Promise<void> {
    await this.page.locator('[data-testid="caption-interrupt"]').click();
  }

  /**
   * 等待 caption-interrupt 元素出现（speaking + hovered 态显示）。
   *
   * CaptionLayer 在 speaking + subtitle 可见 + hovered 时显示「× 打断」glyph。
   * 调用前应先 emit VOICE_SPEAKING + hoverCaptionSubtitle()。
   */
  async waitForInterruptVisible(timeout = 5_000): Promise<void> {
    await this.page.locator('[data-testid="caption-interrupt"]').waitFor({
      state: "visible",
      timeout,
    });
  }

  /**
   * 等待 ``window.__omniDebug`` 注入完成（DEV 模式 App.tsx useEffect 挂载）。
   *
   * App.tsx 在 useEffect 中设置 __omniDebug（含 music / lyrics 控制入口），
   * effect 在首次 render commit 后执行。appPage fixture 的 waitForVoiceState("idle")
   * 只保证首轮 render 已落地，不保证 effect 已跑——故 spec 调用
   * ``__omniDebug.music.fetchPlayerState()`` 前必须先等待此 API 就绪，
   * 否则 evaluate 返回 undefined（optional chaining 短路），fetchPlayerState 不执行。
   */
  async waitForDebugApi(timeout = 10_000): Promise<void> {
    await this.page.waitForFunction(
      () => {
        const debug = (window as unknown as { __omniDebug?: { music?: unknown; lyrics?: unknown } }).__omniDebug;
        return debug !== undefined && debug.music !== undefined && debug.lyrics !== undefined;
      },
      undefined,
      { timeout },
    );
  }
}
