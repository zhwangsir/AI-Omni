/**
 * window.__omniDebug 调用桥（TEST_INFRA）。
 *
 * src/App.tsx:170-200 在 import.meta.env.DEV 下挂载 __omniDebug API，
 * 暴露 setVoiceState + 便捷方法（idle/wake/listen/think/tool/speak/follow）。
 *
 * 该 API 直接调用 Space.setField —— 不经过 statusStore / IPC，专用于测试粒子视觉层。
 * E2E spec 用此桥在已挂载的 Space 上快速触发视觉态切换，无需模拟 voice-status 事件链。
 *
 * 注意：__omniDebug 仅在 DEV 模式可用（vite dev server 默认 DEV=true），E2E 默认满足。
 * 若 spec 需要测试 statusStore 数据流（data-voice-state 等），应使用 fakeTauri.emit
 * 推送 voice-status 事件，而非调用 __omniDebug。
 */
import type { Page } from "@playwright/test";

import { GLOBAL_KEYS } from "./env";
import type { VoicePipelineState } from "../../src/data/sources";

export interface OmniDebugApi {
  /** 直接调用 Space.setField 切换粒子视觉态。 */
  setVoiceState(state: VoicePipelineState): Promise<void>;
  /** 便捷方法：映射到 setVoiceState 的具体枚举值。 */
  idle(): Promise<void>;
  wake(): Promise<void>;
  listen(): Promise<void>;
  think(): Promise<void>;
  tool(): Promise<void>;
  speak(): Promise<void>;
  follow(): Promise<void>;
}

export function createDebugBridge(page: Page): OmniDebugApi {
  return {
    async setVoiceState(state) {
      await page.evaluate(
        (s) => {
          const api = (window as unknown as Record<string, unknown>)[
            GLOBAL_KEYS.OMNI_DEBUG
          ] as { setVoiceState(state: VoicePipelineState): void } | undefined;
          api?.setVoiceState(s);
        },
        state,
      );
    },
    async idle() {
      await page.evaluate(() => {
        const api = (window as unknown as Record<string, unknown>)[
          GLOBAL_KEYS.OMNI_DEBUG
        ] as { idle(): void } | undefined;
        api?.idle();
      });
    },
    async wake() {
      await page.evaluate(() => {
        const api = (window as unknown as Record<string, unknown>)[
          GLOBAL_KEYS.OMNI_DEBUG
        ] as { wake(): void } | undefined;
        api?.wake();
      });
    },
    async listen() {
      await page.evaluate(() => {
        const api = (window as unknown as Record<string, unknown>)[
          GLOBAL_KEYS.OMNI_DEBUG
        ] as { listen(): void } | undefined;
        api?.listen();
      });
    },
    async think() {
      await page.evaluate(() => {
        const api = (window as unknown as Record<string, unknown>)[
          GLOBAL_KEYS.OMNI_DEBUG
        ] as { think(): void } | undefined;
        api?.think();
      });
    },
    async tool() {
      await page.evaluate(() => {
        const api = (window as unknown as Record<string, unknown>)[
          GLOBAL_KEYS.OMNI_DEBUG
        ] as { tool(): void } | undefined;
        api?.tool();
      });
    },
    async speak() {
      await page.evaluate(() => {
        const api = (window as unknown as Record<string, unknown>)[
          GLOBAL_KEYS.OMNI_DEBUG
        ] as { speak(): void } | undefined;
        api?.speak();
      });
    },
    async follow() {
      await page.evaluate(() => {
        const api = (window as unknown as Record<string, unknown>)[
          GLOBAL_KEYS.OMNI_DEBUG
        ] as { follow(): void } | undefined;
        api?.follow();
      });
    },
  };
}
