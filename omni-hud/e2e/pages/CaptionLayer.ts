/**
 * CaptionLayer Page Object（M4-M7 显影场 E2E）。
 *
 * 封装对 CaptionLayer 组件（src/components/CaptionLayer.tsx）的查询与断言：
 * - data-testid="caption-layer"：CaptionLayer 根节点
 * - data-testid="caption-status-mark"：状态标（左上 mono 小字，voice.state 变化显影 2.5s）
 *   - data-visible="true|false"：状态标是否可见
 * - data-testid="caption-subtitle"：显影字幕（speaking + subtitle.visible 时挂载）
 *   - data-revealed="true|false"：字幕是否已显影（visible && !fadingOut）
 *   - data-fading="true|false"：字幕是否正在渐隐（fadingOut）
 *
 * 状态标行为（CaptionLayer.tsx:72-86）：
 * - voice.state 变化时 setMarkVisible(true) + 重置 2.5s 计时器
 * - 2.5s 后 setMarkVisible(false) 渐隐
 *
 * 字幕行为（CaptionLayer.tsx:88-103）：
 * - speaking + 新 replySeq → subtitleStore.begin + appendChunk(reply)
 * - 离开 speaking → subtitleStore.finish（1.2s 展示 + 400ms 渐隐）
 * - 打断 → subtitleStore.hide 立即收起
 */
import { expect, type Page, type Locator } from "@playwright/test";

/** CaptionLayer 根节点选择器。 */
export const CAPTION_LAYER_SELECTOR = '[data-testid="caption-layer"]';
/** 状态标选择器。 */
export const CAPTION_STATUS_MARK_SELECTOR = '[data-testid="caption-status-mark"]';
/** 字幕选择器。 */
export const CAPTION_SUBTITLE_SELECTOR = '[data-testid="caption-subtitle"]';

/** 状态标显影后渐隐时长（CaptionLayer.tsx STATUS_MARK_LINGER_MS）。 */
export const STATUS_MARK_LINGER_MS = 2500;

/** 字幕完整文字停留时长（subtitleStore.ts SUBTITLE_FINAL_SHOW_MS）。 */
export const SUBTITLE_FINAL_SHOW_MS = 1200;

/** 字幕渐隐动画时长（subtitleStore.ts SUBTITLE_FADE_OUT_MS）。 */
export const SUBTITLE_FADE_OUT_MS = 400;

export class CaptionLayerPage {
  readonly page: Page;
  readonly root: Locator;
  readonly statusMark: Locator;
  readonly subtitle: Locator;

  constructor(page: Page) {
    this.page = page;
    this.root = page.locator(CAPTION_LAYER_SELECTOR);
    this.statusMark = page.locator(CAPTION_STATUS_MARK_SELECTOR);
    this.subtitle = page.locator(CAPTION_SUBTITLE_SELECTOR);
  }

  /** 等待 CaptionLayer 根节点挂载（full 形态下出现）。 */
  async waitForMounted(timeout = 5_000): Promise<void> {
    await this.root.waitFor({ state: "attached", timeout });
  }

  /** 读取状态标 data-visible 属性值。 */
  async getStatusMarkVisible(): Promise<boolean> {
    const attr = await this.statusMark.getAttribute("data-visible");
    return attr === "true";
  }

  /** 等待状态标 data-visible 等于目标值。 */
  async waitForStatusMarkVisible(
    visible: boolean,
    timeout = 5_000,
  ): Promise<void> {
    await expect(this.statusMark).toHaveAttribute(
      "data-visible",
      visible ? "true" : "false",
      { timeout },
    );
  }

  /** 读取状态标文字（voice.state ?? "离线"）。 */
  async getStatusMarkText(): Promise<string> {
    return (await this.statusMark.textContent()) ?? "";
  }

  /** 等待字幕挂载（speaking + subtitle.visible 时）。 */
  async waitForSubtitleMounted(timeout = 5_000): Promise<void> {
    await this.subtitle.waitFor({ state: "attached", timeout });
  }

  /** 等待字幕卸载（finish 渐隐完成后 subtitle.visible=false）。 */
  async waitForSubtitleUnmounted(timeout = 5_000): Promise<void> {
    await this.subtitle.waitFor({ state: "detached", timeout });
  }

  /** 读取字幕 data-revealed 属性值（visible && !fadingOut）。 */
  async getSubtitleRevealed(): Promise<boolean> {
    const attr = await this.subtitle.getAttribute("data-revealed");
    return attr === "true";
  }

  /** 等待字幕 data-revealed 等于目标值。 */
  async waitForSubtitleRevealedState(revealed: boolean, timeout = 5_000): Promise<void> {
    await expect(this.subtitle).toHaveAttribute(
      "data-revealed",
      revealed ? "true" : "false",
      { timeout },
    );
  }

  /** 读取字幕 data-fading 属性值（fadingOut=true 时正在渐隐）。 */
  async getSubtitleFading(): Promise<boolean> {
    const attr = await this.subtitle.getAttribute("data-fading");
    return attr === "true";
  }

  /** 等待字幕 data-fading 等于目标值。 */
  async waitForSubtitleFading(fading: boolean, timeout = 5_000): Promise<void> {
    await expect(this.subtitle).toHaveAttribute(
      "data-fading",
      fading ? "true" : "false",
      { timeout },
    );
  }

  /** 读取字幕文本内容。 */
  async getSubtitleText(): Promise<string> {
    return (await this.subtitle.textContent()) ?? "";
  }
}
