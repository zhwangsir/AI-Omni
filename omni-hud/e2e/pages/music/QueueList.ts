/**
 * QueueList Page Object（M17 音乐控制 E2E）。
 *
 * 封装 src/components/music/QueueList.tsx 的 DOM 查询与交互：
 * - 空队列占位（data-empty="true"，无 queue 时显示「队列为空」）
 * - 队列长度（data-queue-length 属性）
 * - 队列项（queue-list-row）：data-index / data-current / data-song-id
 * - 点击项触发 store.play({index}) → music_tool IPC
 *
 * 选择器全部基于 data-testid。
 */
import { expect, type Locator, type Page } from "@playwright/test";

/** QueueList 根元素选择器。 */
export const QUEUE_LIST_SELECTOR = '[data-testid="queue-list"]';

export class QueueList {
  readonly page: Page;
  readonly root: Locator;
  readonly rows: Locator;

  constructor(page: Page) {
    this.page = page;
    this.root = page.locator(QUEUE_LIST_SELECTOR);
    this.rows = page.locator('[data-testid="queue-list-row"]');
  }

  /** 等待 QueueList 挂载。 */
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

  /** 读取队列长度（data-queue-length 属性）。 */
  async getQueueLength(): Promise<number> {
    const attr = await this.root.getAttribute("data-queue-length");
    return attr !== null ? Number(attr) : 0;
  }

  /** 等待队列长度等于目标值。 */
  async waitForQueueLength(length: number, timeout = 5_000): Promise<void> {
    await expect(this.root).toHaveAttribute(
      "data-queue-length",
      String(length),
      { timeout },
    );
  }

  /** 取所有队列行 locator。 */
  getRows(): Locator {
    return this.rows;
  }

  /** 取指定 index 的队列行。 */
  getRow(index: number): Locator {
    return this.page.locator(
      `[data-testid="queue-list-row"][data-index="${index}"]`,
    );
  }

  /** 读取指定 index 队列行的 data-current 属性（"true" 表示当前播放）。 */
  async isRowCurrent(index: number): Promise<boolean> {
    const row = this.getRow(index);
    const attr = await row.getAttribute("data-current");
    return attr === "true";
  }

  /** 读取指定 index 队列行的 data-song-id 属性。 */
  async getRowSongId(index: number): Promise<string | null> {
    const row = this.getRow(index);
    return await row.getAttribute("data-song-id");
  }

  /** 点击指定 index 的队列行（触发跳转播放）。 */
  async clickRow(index: number): Promise<void> {
    await this.getRow(index).click();
  }

  /** 等待指定 index 的行标记为当前（data-current="true"）。 */
  async waitForRowCurrent(index: number, timeout = 5_000): Promise<void> {
    await expect(this.getRow(index)).toHaveAttribute("data-current", "true", {
      timeout,
    });
  }
}
