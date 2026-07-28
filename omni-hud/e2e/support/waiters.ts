/**
 * E2E 通用等待工具：把高频断言模式封装为可复用函数。
 *
 * 命名约定：`waitFor<Subject><Condition>`，全部返回 Promise<void>，
 * 失败时由 Playwright 的 expect 自动 retry + 给出可读 diff。
 */
import { expect, type Page } from "@playwright/test";

import type { VoicePipelineState, WindowMode } from "../../src/data/sources";

/**
 * 等待 hud-root 的 data-voice-state 等于目标状态。
 *
 * 用法：spec 调 router.emit(VOICE_STATUS_EVENT, {...speaking...}) 后等待 UI 同步。
 * 等待时长由 playwright.config.ts expect.timeout（5s）控制。
 */
export async function waitForVoiceState(
  page: Page,
  state: VoicePipelineState,
): Promise<void> {
  await expect(
    page.locator('[data-testid="hud-root"]'),
    `voice state should become "${state}"`,
  ).toHaveAttribute("data-voice-state", state);
}

/**
 * 等待 hud-root 的 data-window-mode 等于目标形态。
 *
 * 注意：windowMode = "wallpaper" 的根节点仍带 data-window-mode="wallpaper"；
 * 但 full / mini 形态切换由 statusStore 轮询驱动，可能有 ~1s 延迟（M5.4 事件驱动后已大幅降低）。
 */
export async function waitForWindowMode(
  page: Page,
  mode: WindowMode,
): Promise<void> {
  await expect(
    page.locator('[data-testid="hud-root"]'),
    `window mode should become "${mode}"`,
  ).toHaveAttribute("data-window-mode", mode);
}

/**
 * 等待某 testid 元素出现（shortcut）。
 *
 * 适用于 lazy-mount 组件（如 LyricsDisplay 在 lyrics 非空时才挂载）。
 */
export async function waitForVisible(
  page: Page,
  testid: string,
  timeout = 5_000,
): Promise<void> {
  await page.locator(`[data-testid="${testid}"]`).waitFor({
    state: "visible",
    timeout,
  });
}

/**
 * 等待某 testid 元素消失（被卸载或 display:none）。
 *
 * 适用于 conditionally rendered 组件（如 mini 形态下 AgentPanel 不挂载）。
 */
export async function waitForAbsent(
  page: Page,
  testid: string,
  timeout = 5_000,
): Promise<void> {
  await page.locator(`[data-testid="${testid}"]`).waitFor({
    state: "hidden",
    timeout,
  });
}
