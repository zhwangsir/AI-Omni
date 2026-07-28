/**
 * ToolCallCard Page Object：单次工具调用卡片交互入口（M13 E2E）。
 *
 * 封装对 tool-call-card 元素的查询与断言：
 * - data-testid="tool-call-card"：卡片根节点（data-status 属性反映 pending/success/error）
 * - data-testid="tool-call-card-name"：工具名（如 home_call_service）
 * - data-testid="tool-call-card-status"：状态文字（调用中 / 已完成 / 失败）
 * - data-testid="tool-call-card-params"：参数 JSON 文本
 * - data-testid="tool-call-card-result"：结果文本（status !== pending 且 result !== null 时显示）
 *
 * 用法：
 * ```ts
 * const card = new ToolCallCard(page, 0); // 第 0 个气泡的第 0 个工具卡片
 * expect(await card.getName()).toBe("home_call_service");
 * expect(await card.getStatusText()).toBe("调用中");
 * ```
 *
 * 或指定气泡索引：
 * ```ts
 * const card = new ToolCallCard(page, 0, 0); // 第 0 个气泡的第 0 个卡片
 * ```
 */
import { type Page, type Locator } from "@playwright/test";

import type { ToolCallStatus } from "../../../src/data/sources";

/** tool-call-card 选择器（在 agent-panel 内的任意层级）。 */
export const TOOL_CALL_CARD_SELECTOR = '[data-testid="tool-call-card"]';

export class ToolCallCard {
  readonly page: Page;
  readonly root: Locator;
  readonly name: Locator;
  readonly status: Locator;
  readonly params: Locator;

  /**
   * 构造 ToolCallCard page object。
   *
   * @param page Playwright Page 实例
   * @param bubbleIndex 消息气泡索引（0-based）
   * @param cardIndex 工具卡片索引（0-based，默认 0）
   */
  constructor(page: Page, bubbleIndex: number, cardIndex: number = 0) {
    this.page = page;
    const bubble = page.locator('[data-testid="message-bubble"]').nth(bubbleIndex);
    this.root = bubble.locator(TOOL_CALL_CARD_SELECTOR).nth(cardIndex);
    this.name = this.root.locator('[data-testid="tool-call-card-name"]');
    this.status = this.root.locator('[data-testid="tool-call-card-status"]');
    this.params = this.root.locator('[data-testid="tool-call-card-params"]');
  }

  /** 等待卡片挂载。 */
  async waitForMounted(timeout = 5_000): Promise<void> {
    await this.root.waitFor({ state: "attached", timeout });
  }

  /** 读取 data-status 属性（pending / success / error）。 */
  async getStatus(): Promise<ToolCallStatus | null> {
    const attr = await this.root.getAttribute("data-status");
    if (attr === "pending" || attr === "success" || attr === "error") return attr;
    return null;
  }

  /** 等待 data-status 等于目标值。 */
  async waitForStatus(status: ToolCallStatus, timeout = 5_000): Promise<void> {
    await this.root.waitFor({ state: "attached", timeout });
    // 使用 attribute 断言（root 已挂载）
    const { expect } = await import("@playwright/test");
    await expect(this.root).toHaveAttribute("data-status", status, { timeout });
  }

  /** 读取工具名文本（如 home_call_service）。 */
  async getName(): Promise<string> {
    return (await this.name.textContent()) ?? "";
  }

  /** 读取状态文字（调用中 / 已完成 / 失败）。 */
  async getStatusText(): Promise<string> {
    return (await this.status.textContent()) ?? "";
  }

  /** 读取参数 JSON 文本。 */
  async getParamsText(): Promise<string> {
    return (await this.params.textContent()) ?? "";
  }

  /** 读取结果文本（status=pending 或 result=null 时返回空串）。 */
  async getResultText(): Promise<string> {
    const resultEl = this.root.locator('[data-testid="tool-call-card-result"]');
    if ((await resultEl.count()) === 0) return "";
    return (await resultEl.textContent()) ?? "";
  }

  /** 读取卡片 aria-label（含工具名与状态）。 */
  async getAriaLabel(): Promise<string | null> {
    return await this.root.getAttribute("aria-label");
  }
}
