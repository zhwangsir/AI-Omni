/**
 * NowPlaying Page Object（M17 音乐控制 E2E）。
 *
 * 封装 src/components/music/NowPlaying.tsx 的 DOM 查询与断言：
 * - 空态占位（data-empty="true"，无 current_song 时显示「当前无播放」）
 * - 当前曲目标题（now-playing-title）
 * - 艺术家列表（now-playing-artists）
 * - 专辑名（now-playing-album，可选字段缺失时不渲染）
 * - 封面图（now-playing-cover，有 cover_url 时为 <img>，否则为占位 div）
 * - 播放控制按钮（play-pause / next / previous / stop / repeat）
 * - 进度条（now-playing-progress，range input 可 seek）
 *
 * 选择器全部基于 data-testid。
 */
import { expect, type Locator, type Page } from "@playwright/test";

import type { PlayerStateName, RepeatMode } from "../../../src/store/musicStore";

/** NowPlaying 根元素选择器。 */
export const NOW_PLAYING_SELECTOR = '[data-testid="now-playing"]';

export class NowPlaying {
  readonly page: Page;
  readonly root: Locator;
  readonly title: Locator;
  readonly artists: Locator;
  readonly album: Locator;
  readonly cover: Locator;
  readonly playPauseButton: Locator;
  readonly nextButton: Locator;
  readonly previousButton: Locator;
  readonly stopButton: Locator;
  readonly repeatButton: Locator;
  readonly progress: Locator;

  constructor(page: Page) {
    this.page = page;
    this.root = page.locator(NOW_PLAYING_SELECTOR);
    this.title = page.locator('[data-testid="now-playing-title"]');
    this.artists = page.locator('[data-testid="now-playing-artists"]');
    this.album = page.locator('[data-testid="now-playing-album"]');
    this.cover = page.locator('[data-testid="now-playing-cover"]');
    this.playPauseButton = page.locator(
      '[data-testid="now-playing-play-pause"]',
    );
    this.nextButton = page.locator('[data-testid="now-playing-next"]');
    this.previousButton = page.locator(
      '[data-testid="now-playing-previous"]',
    );
    this.stopButton = page.locator('[data-testid="now-playing-stop"]');
    this.repeatButton = page.locator('[data-testid="now-playing-repeat"]');
    this.progress = page.locator('[data-testid="now-playing-progress"]');
  }

  /** 等待 NowPlaying 挂载。 */
  async waitForMounted(timeout = 5_000): Promise<void> {
    await this.root.waitFor({ state: "attached", timeout });
  }

  /** 读取 data-empty 属性。 */
  async isEmpty(): Promise<boolean> {
    const attr = await this.root.getAttribute("data-empty");
    return attr === "true";
  }

  /** 等待 data-empty 等于目标值。 */
  async waitForEmpty(empty: boolean, timeout = 5_000): Promise<void> {
    await expect(this.root).toHaveAttribute(
      "data-empty",
      empty ? "true" : "false",
      { timeout },
    );
  }

  /** 读取当前曲目标题文本。 */
  async getTitle(): Promise<string> {
    return (await this.title.textContent()) ?? "";
  }

  /** 读取艺术家列表文本（已拼接为 "周杰伦 / 费玉清" 格式）。 */
  async getArtists(): Promise<string> {
    return (await this.artists.textContent()) ?? "";
  }

  /** 读取专辑名文本（无专辑时元素不挂载，返回 null）。 */
  async getAlbum(): Promise<string | null> {
    const count = await this.album.count();
    if (count === 0) return null;
    return (await this.album.textContent()) ?? "";
  }

  /** 读取封面 img 的 src（无 cover_url 时为占位 div，src 为 null）。 */
  async getCoverSrc(): Promise<string | null> {
    const count = await this.cover.count();
    if (count === 0) return null;
    const tag = await this.cover.evaluate((el) => el.tagName.toLowerCase());
    if (tag !== "img") return null;
    return await this.cover.getAttribute("src");
  }

  /** 等待标题等于目标值。 */
  async waitForTitle(title: string, timeout = 5_000): Promise<void> {
    await expect(this.title).toHaveText(title, { timeout });
  }

  /** 等待艺术家包含目标子串。 */
  async waitForArtistsContaining(text: string, timeout = 5_000): Promise<void> {
    await expect(this.artists).toContainText(text, { timeout });
  }

  /** 点击播放/暂停按钮。 */
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

  /** 点击停止按钮。 */
  async clickStop(): Promise<void> {
    await this.stopButton.click();
  }

  /** 点击循环模式按钮。 */
  async clickRepeat(): Promise<void> {
    await this.repeatButton.click();
  }

  /** 读取当前循环模式。 */
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

  /** 读取 data-player-state 属性。 */
  async getPlayerState(): Promise<PlayerStateName | null> {
    const attr = await this.root.getAttribute("data-player-state");
    if (attr === "stopped" || attr === "playing" || attr === "paused") {
      return attr;
    }
    return null;
  }
}
