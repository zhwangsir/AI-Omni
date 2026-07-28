/**
 * LyricsDisplay Page Object（M18 歌词同步 E2E）。
 *
 * 封装 src/components/lyrics/LyricsDisplay.tsx 的 DOM 查询与断言：
 * - 面板挂载 / 空态（data-empty="true"，无 currentLyrics 或 parsed 为空）
 * - 歌词行列表（lyrics-row）：data-current / data-time 属性
 * - 当前行高亮（data-current="true"）
 * - 翻译行（lyrics-row-translation）
 * - 逐字高亮（lyrics-word / lyrics-word-current）
 * - 偏移指示器（lyrics-offset）
 * - 来源标识（data-source 属性：local_file / embedded / online / none）
 *
 * 选择器全部基于 data-testid，避免依赖 CSS class / 文本（暗房风格约束：
 * 不测具体颜色值，测 data-* 属性）。
 */
import { expect, type Locator, type Page } from "@playwright/test";

/** LyricsDisplay 根元素选择器。 */
export const LYRICS_DISPLAY_SELECTOR = '[data-testid="lyrics-display"]';

export class LyricsDisplay {
  readonly page: Page;
  readonly root: Locator;
  readonly rows: Locator;
  readonly offset: Locator;

  constructor(page: Page) {
    this.page = page;
    this.root = page.locator(LYRICS_DISPLAY_SELECTOR);
    this.rows = page.locator('[data-testid="lyrics-row"]');
    this.offset = page.locator('[data-testid="lyrics-offset"]');
  }

  /**
   * 等待 LyricsDisplay 挂载。
   *
   * LyricsDisplay 仅在 App.tsx 中当 ``currentSong !== null`` 时渲染。
   * 测试需先注入 music_tool 返回带 current_song 的 player state，再调
   * ``__omniDebug.music.fetchPlayerState()`` 触发 store 拉取，使
   * musicStore.playerState.current_song 非 null → App.tsx 渲染 LyricsDisplay。
   */
  async waitForMounted(timeout = 5_000): Promise<void> {
    await this.root.waitFor({ state: "attached", timeout });
  }

  /**
   * 等待 LyricsDisplay 不再挂载（current_song 变 null 时卸载）。
   *
   * 用于测试「无曲目时不渲染歌词面板」：fetchPlayerState 返回空 player state
   * → current_song=null → App.tsx 不渲染 LyricsDisplay。
   */
  async waitForDetached(timeout = 5_000): Promise<void> {
    await this.root.waitFor({ state: "detached", timeout });
  }

  /** 读取 data-empty 属性（无 currentLyrics / parsed 为空时为 "true"）。 */
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

  /** 读取 data-source 属性（local_file / embedded / online / none）。 */
  async getSource(): Promise<string | null> {
    return await this.root.getAttribute("data-source");
  }

  /** 读取 data-current-index 属性（当前行索引，0-based）。 */
  async getCurrentIndex(): Promise<number> {
    const attr = await this.root.getAttribute("data-current-index");
    return attr !== null ? Number(attr) : -1;
  }

  /** 等待 data-current-index 等于目标值。 */
  async waitForCurrentIndex(index: number, timeout = 5_000): Promise<void> {
    await expect(this.root).toHaveAttribute(
      "data-current-index",
      String(index),
      { timeout },
    );
  }

  /** 取所有歌词行 locator。 */
  getRows(): Locator {
    return this.rows;
  }

  /** 取指定 index 的歌词行。 */
  getRow(index: number): Locator {
    return this.page.locator(`[data-testid="lyrics-row"][data-time]`).nth(index);
  }

  /** 读取指定 index 行的 data-current 属性。 */
  async isRowCurrent(index: number): Promise<boolean> {
    const row = this.getRow(index);
    const attr = await row.getAttribute("data-current");
    return attr === "true";
  }

  /** 读取指定 index 行的 data-time 属性（行起始时间秒）。 */
  async getRowTime(index: number): Promise<number> {
    const row = this.getRow(index);
    const attr = await row.getAttribute("data-time");
    return attr !== null ? Number(attr) : -1;
  }

  /** 读取指定 index 行的文本内容。 */
  async getRowText(index: number): Promise<string> {
    const row = this.getRow(index);
    return (await row.textContent()) ?? "";
  }

  /** 等待指定 index 行标记为当前（data-current="true"）。 */
  async waitForRowCurrent(index: number, timeout = 5_000): Promise<void> {
    await expect(this.getRow(index)).toHaveAttribute("data-current", "true", {
      timeout,
    });
  }

  /** 取指定 index 行内的翻译 span（若无翻译返回 null）。 */
  async getRowTranslation(index: number): Promise<string | null> {
    const row = this.getRow(index);
    const translation = row.locator('[data-testid="lyrics-row-translation"]');
    const count = await translation.count();
    if (count === 0) return null;
    return (await translation.textContent()) ?? "";
  }

  /** 取指定 index 行内的所有逐字 span（lyrics-word）。 */
  getRowWords(index: number): Locator {
    return this.getRow(index).locator('[data-testid="lyrics-word"]');
  }

  /** 取当前高亮字 span（lyrics-word-current）。 */
  getCurrentWord(): Locator {
    return this.page.locator('[data-testid="lyrics-word-current"]');
  }

  /** 读取偏移指示器文本（如 "+0.0s" / "+0.5s" / "-1.2s"）。 */
  async getOffsetText(): Promise<string> {
    return (await this.offset.textContent()) ?? "";
  }
}
