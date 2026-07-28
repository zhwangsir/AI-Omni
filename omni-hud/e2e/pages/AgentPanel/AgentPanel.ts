/**
 * AgentPanel Page Object：雪莉对话面板交互入口（M13 E2E）。
 *
 * 封装对 agent-panel 根节点及其子元素的查询与断言：
 * - data-testid="agent-panel"：面板根节点（Full 模式渲染，mini 模式返回 null）
 * - data-testid="agent-panel-empty"：空状态（无消息时显示「雪莉待命中」）
 * - data-testid="agent-panel-messages"：消息列表容器（可滚动）
 * - data-testid="agent-panel-indicator"：状态指示器小圆点（颜色跟随 voice.state）
 * - data-testid="agent-panel-title"：标题文字「雪莉」
 * - data-testid="message-bubble"：单条对话气泡（user / assistant）
 * - data-testid="message-bubble-toolcalls"：assistant 消息的工具调用槽位
 *
 * 与 HudApp 的关系：HudApp 封装 hud-root 根节点（voice-state / window-mode），
 * AgentPanel 封装 agent-panel 子树（对话流 / 工具调用）。spec 通常先创建 HudApp
 * 等待 voice 状态稳定，再创建 AgentPanel 查询消息列表。
 */
import { expect, type Page, type Locator } from "@playwright/test";

import type { VoicePipelineState } from "../../../src/data/sources";

/** agent-panel 根节点选择器。 */
export const AGENT_PANEL_SELECTOR = '[data-testid="agent-panel"]';

export class AgentPanel {
  readonly page: Page;
  readonly root: Locator;
  readonly messages: Locator;
  readonly empty: Locator;
  readonly indicator: Locator;
  readonly title: Locator;

  constructor(page: Page) {
    this.page = page;
    this.root = page.locator(AGENT_PANEL_SELECTOR);
    this.messages = page.locator('[data-testid="agent-panel-messages"]');
    this.empty = page.locator('[data-testid="agent-panel-empty"]');
    this.indicator = page.locator('[data-testid="agent-panel-indicator"]');
    this.title = page.locator('[data-testid="agent-panel-title"]');
  }

  /** 等待 AgentPanel 挂载（Full 模式下渲染）。 */
  async waitForMounted(timeout = 5_000): Promise<void> {
    await this.root.waitFor({ state: "attached", timeout });
  }

  /** 等待 AgentPanel 卸载（mini 模式不渲染）。 */
  async waitForUnmounted(timeout = 5_000): Promise<void> {
    await this.root.waitFor({ state: "detached", timeout });
  }

  /** 读取面板 data-voice-state 属性（跟随 statusStore.voice.state）。 */
  async getVoiceState(): Promise<string> {
    return (await this.root.getAttribute("data-voice-state")) ?? "idle";
  }

  /** 读取状态指示器背景色（rgb 字符串，如 "rgb(111, 181, 138)"）。 */
  async getIndicatorColor(): Promise<string> {
    const style = await this.indicator.evaluate((el) => {
      const computed = window.getComputedStyle(el);
      return computed.backgroundColor;
    });
    return style;
  }

  /** 等待状态指示器颜色变为目标值（rgb 字符串）。 */
  async waitForIndicatorColor(color: string, timeout = 5_000): Promise<void> {
    await expect
      .poll(async () => this.getIndicatorColor(), { timeout })
      .toBe(color);
  }

  /** 当前是否为空状态（无消息）。 */
  async isEmpty(): Promise<boolean> {
    return (await this.empty.count()) > 0;
  }

  /** 等待空状态出现（消息列表被清空）。 */
  async waitForEmpty(timeout = 5_000): Promise<void> {
    await this.empty.waitFor({ state: "attached", timeout });
  }

  /** 等待空状态消失（首条消息出现）。 */
  async waitForNonEmpty(timeout = 5_000): Promise<void> {
    await this.empty.waitFor({ state: "detached", timeout });
  }

  /** 获取当前消息气泡列表。 */
  getBubbles(): Locator {
    return this.page.locator('[data-testid="message-bubble"]');
  }

  /** 获取指定索引的消息气泡。 */
  getBubble(index: number): Locator {
    return this.page.locator('[data-testid="message-bubble"]').nth(index);
  }

  /** 获取消息气泡数量。 */
  async getBubbleCount(): Promise<number> {
    return await this.page.locator('[data-testid="message-bubble"]').count();
  }

  /** 等待消息气泡数量达到目标值。 */
  async waitForBubbleCount(count: number, timeout = 5_000): Promise<void> {
    await expect
      .poll(async () => this.getBubbleCount(), { timeout })
      .toBe(count);
  }

  /** 获取指定索引消息气泡的 data-role 属性（user / assistant）。 */
  async getBubbleRole(index: number): Promise<string | null> {
    return await this.getBubble(index).getAttribute("data-role");
  }

  /** 获取指定索引消息气泡的文本内容。 */
  async getBubbleText(index: number): Promise<string> {
    const el = this.getBubble(index).locator('[data-testid="message-bubble-text"]');
    return (await el.textContent()) ?? "";
  }

  /** 获取指定索引消息气泡的工具调用槽位（若存在）。 */
  getBubbleToolCalls(index: number): Locator {
    return this.getBubble(index).locator('[data-testid="message-bubble-toolcalls"]');
  }

  /** 获取指定索引消息气泡的工具调用卡片列表。 */
  getBubbleToolCallCards(index: number): Locator {
    return this.getBubble(index).locator('[data-testid="tool-call-card"]');
  }

  /** 获取指定索引消息气泡的工具调用卡片数量。 */
  async getBubbleToolCallCardCount(index: number): Promise<number> {
    return await this.getBubble(index).locator('[data-testid="tool-call-card"]').count();
  }

  /** 获取消息列表容器的滚动条位置（scrollTop）。 */
  async getMessagesScrollTop(): Promise<number> {
    return await this.messages.evaluate((el) => el.scrollTop);
  }

  /** 获取消息列表容器的滚动高度（scrollHeight）。 */
  async getMessagesScrollHeight(): Promise<number> {
    return await this.messages.evaluate((el) => el.scrollHeight);
  }

  /** 消息列表是否滚动到底部（scrollTop + clientHeight >= scrollHeight - 5px 容差）。 */
  async isScrolledToBottom(): Promise<boolean> {
    return await this.messages.evaluate((el) => {
      return el.scrollTop + el.clientHeight >= el.scrollHeight - 5;
    });
  }

  /** 等待消息列表滚动到底部（自动滚动行为验证）。 */
  async waitForScrolledToBottom(timeout = 5_000): Promise<void> {
    await expect
      .poll(async () => this.isScrolledToBottom(), { timeout })
      .toBe(true);
  }
}
