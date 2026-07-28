/**
 * MiniBar Page Object（M12 灵动岛双形态 E2E）。
 *
 * 封装对 mini 形态下 MiniBar 组件的查询与断言：
 * - data-testid="mini-bar"：mini 形态下挂载的浮窗根节点（App.tsx:285）
 * - data-testid="mini-bar-status-text"：状态文字 span（MiniBar.tsx:60）
 *
 * MiniBar 在 idle 待命态（voice.windowMode=mini）由 App.tsx 渲染；
 * 切到 full 形态时整体 hud-root-mini 分支不挂载，MiniBar 自然消失。
 *
 * 状态文字映射（MiniBar.tsx STATE_LABEL）：
 * - idle → "雪莉 · 待命"
 * - wake_listening → "唤醒中…"
 * - speaking → "应答中…" 等
 */
import { expect, type Page, type Locator } from "@playwright/test";

import type { VoicePipelineState } from "../../src/data/sources";

/** MiniBar 根节点选择器。 */
export const MINI_BAR_SELECTOR = '[data-testid="mini-bar"]';

/** MiniBar 状态文字 span 选择器。 */
export const MINI_BAR_STATUS_TEXT_SELECTOR = '[data-testid="mini-bar-status-text"]';

/**
 * voice.state → MiniBar 中文状态文字映射（与 MiniBar.tsx STATE_LABEL 同步）。
 *
 * 用于 spec 断言「emit voice-status 后 MiniBar 显示对应中文文字」。
 * 字段命名严格遵循源文件，避免常量漂移。
 */
export const MINI_BAR_STATE_LABEL: Record<VoicePipelineState, string> = {
  idle: "雪莉 · 待命",
  wake_listening: "唤醒中…",
  follow_up_listening: "续听中…",
  recording: "聆听中…",
  transcribing: "转写中…",
  thinking: "思考中…",
  tool_using: "调用工具…",
  speaking: "应答中…",
};

/** voice.state=null / available=false 时显示的默认文字。 */
export const MINI_BAR_DEFAULT_LABEL = "雪莉 · 待命";

export class MiniBarPage {
  readonly page: Page;
  readonly root: Locator;
  readonly statusText: Locator;

  constructor(page: Page) {
    this.page = page;
    this.root = page.locator(MINI_BAR_SELECTOR);
    this.statusText = page.locator(MINI_BAR_STATUS_TEXT_SELECTOR);
  }

  /** 等待 MiniBar 根节点挂载（mini 形态下出现）。 */
  async waitForMounted(timeout = 5_000): Promise<void> {
    await this.root.waitFor({ state: "attached", timeout });
  }

  /** 等待 MiniBar 根节点卸载（切到 full 形态后消失）。 */
  async waitForUnmounted(timeout = 5_000): Promise<void> {
    await this.root.waitFor({ state: "detached", timeout });
  }

  /** 读取 MiniBar 状态文字（如「雪莉 · 待命」「应答中…」）。 */
  async getStatusText(): Promise<string> {
    return (await this.statusText.textContent()) ?? "";
  }

  /** 等待 MiniBar 显示指定状态文字（参数为 MiniBar.tsx STATE_LABEL 的值）。 */
  async waitForStatusText(label: string, timeout = 5_000): Promise<void> {
    await expect(this.statusText).toHaveText(label, { timeout });
  }
}
