/**
 * PlayControlBar Page Object（M17 音乐控制 E2E）。
 *
 * 封装 src/components/music/PlayControlBar.tsx 的 DOM 查询与交互：
 * - 空态占位（data-empty="true"）
 * - 播放/暂停按钮（点击触发 store.resume / store.pause → music_tool IPC）
 * - 上一首 / 下一首按钮（点击触发 store.previous / store.next → music_tool IPC）
 * - 进度条（range input，可 seek）
 * - 循环模式按钮（点击切换，data-repeat-mode 属性反映当前模式）
 *
 * 选择器全部基于 data-testid，避免依赖 CSS class / 文本（暗房风格约束：
 * 不测具体颜色值，测 data-* 属性）。
 */
import { expect, type Locator, type Page } from "@playwright/test";

import type { PlayerStateName, RepeatMode } from "../../../src/store/musicStore";

/** PlayControlBar 根元素选择器。 */
export const PLAY_CONTROL_BAR_SELECTOR = '[data-testid="play-control-bar"]';

export class PlayControlBar {
  readonly page: Page;
  readonly root: Locator;
  readonly previousButton: Locator;
  readonly playPauseButton: Locator;
  readonly nextButton: Locator;
  readonly progress: Locator;
  readonly repeatButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.root = page.locator(PLAY_CONTROL_BAR_SELECTOR);
    this.previousButton = page.locator(
      '[data-testid="play-control-bar-previous"]',
    );
    this.playPauseButton = page.locator(
      '[data-testid="play-control-bar-play-pause"]',
    );
    this.nextButton = page.locator('[data-testid="play-control-bar-next"]');
    this.progress = page.locator('[data-testid="play-control-bar-progress"]');
    this.repeatButton = page.locator(
      '[data-testid="play-control-bar-repeat"]',
    );
  }

  /** 等待 PlayControlBar 挂载（Full 模式下 App.tsx 必挂）。 */
  async waitForMounted(timeout = 5_000): Promise<void> {
    await this.root.waitFor({ state: "attached", timeout });
  }

  /** 读取 data-empty 属性（无 current_song 时为 "true"）。 */
  async isEmpty(): Promise<boolean> {
    const attr = await this.root.getAttribute("data-empty");
    return attr === "true";
  }

  /** 读取 data-player-state 属性（stopped / playing / paused）。 */
  async getPlayerState(): Promise<PlayerStateName | null> {
    const attr = await this.root.getAttribute("data-player-state");
    if (attr === "stopped" || attr === "playing" || attr === "paused") {
      return attr;
    }
    return null;
  }

  /** 等待 data-empty 等于目标值。 */
  async waitForEmpty(empty: boolean, timeout = 5_000): Promise<void> {
    await expect(this.root).toHaveAttribute(
      "data-empty",
      empty ? "true" : "false",
      { timeout },
    );
  }

  /** 等待 data-player-state 等于目标值。 */
  async waitForPlayerState(state: PlayerStateName, timeout = 5_000): Promise<void> {
    await expect(this.root).toHaveAttribute("data-player-state", state, {
      timeout,
    });
  }

  /** 点击播放/暂停按钮（playing → pause；paused/stopped → resume）。 */
  async clickPlayPause(): Promise<void> {
    await this.playPauseButton.click();
  }

  /** 点击下一首按钮。 */
  async clickNext(): Promise<void> {
    await this.nextButton.click();
  }

  /** 点击上一首按钮。 */
  async clickPrevious(): Promise<void> {
    await this.previousButton.click();
  }

  /** 点击循环模式按钮（sequence → list_loop → single → random → sequence）。 */
  async clickRepeat(): Promise<void> {
    await this.repeatButton.click();
  }

  /** 读取当前循环模式（data-repeat-mode 属性）。 */
  async getRepeatMode(): Promise<RepeatMode | null> {
    const attr = await this.repeatButton.getAttribute("data-repeat-mode");
    if (
      attr === "sequence" ||
      attr === "list_loop" ||
      attr === "single" ||
      attr === "random"
    ) {
      return attr;
    }
    return null;
  }

  /** 等待循环模式等于目标值。 */
  async waitForRepeatMode(mode: RepeatMode, timeout = 5_000): Promise<void> {
    await expect(this.repeatButton).toHaveAttribute("data-repeat-mode", mode, {
      timeout,
    });
  }
}
