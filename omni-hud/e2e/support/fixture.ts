/**
 * Playwright fixture 扩展：注入 fake Tauri IPC（TEST_INFRA D1/D5 决策）。
 *
 * 使用方式：
 * ```ts
 * import { test, expect } from "../support/fixture";
 * test("spec", async ({ page, fakeTauri }) => { ... });
 * ```
 *
 * fakeTauri 是 IpcRouter 实例，提供 register/override/reset/calls/callsFor/emit API。
 * 每个 test 用例自动 cleanup（router.reset + 清 calls 日志），避免跨用例污染。
 *
 * 与既有 vitest 零冲突：vitest 读 vite.config.ts 的 test 段，Playwright 读本 fixture。
 */
import { test as base, expect, type Page } from "@playwright/test";

import { createIpcRouter, type IpcRouter } from "./ipcRouter";
import { buildBootstrapScript } from "./fakeTauri";
import { CMD, DEV_SERVER_URL, GLOBAL_KEYS, VOICE_STATUS_EVENT } from "./env";

export interface OmniFixtures {
  /**
   * 注入的 fake Tauri IPC router：spec 用 register/override 注入 fixture 响应，
   * 用 calls/callsFor 断言 invoke 调用，用 emit 模拟 Rust 事件推送。
   */
  fakeTauri: IpcRouter;
  /**
   * 在 baseURL 上完成 navigation 并等待 `__omniE2EReady` 标记的 page。
   * 比 base `page` 更严格：保证 fake Tauri 注入完成 + App 首帧挂载。
   */
  appPage: Page;
}

/**
 * 跟踪最近一次 emit 的 voice-status 负载，供 get_voice_status 轮询兜底返回。
 *
 * 背景：statusStore.start() 调度 voice 通道 delay=0 的首轮轮询（statusStore.ts:200），
 * 与 spec 的 emit 形成 race：若首轮轮询在 emit 之后才返回，会把 voice 覆盖回
 * EMPTY_VOICE_STATUS（available:false, state:null）→ data-voice-state=idle，
 * 导致「emit 后被轮询覆盖」的假阳性失败。
 *
 * 此跟踪变量让轮询也返回最近一次 emit 的负载（若已 emit 过），避免 race；
 * spec 仍可用 router.override(CMD.GET_VOICE_STATUS, ...) 显式注入不同的轮询响应
 * （覆盖此默认行为）。
 */
let lastEmittedVoice: unknown = null;

export const test = base.extend<OmniFixtures>({
  fakeTauri: async ({ page }, use) => {
    const router = createIpcRouter();

    // 重置上一用例残留的 emit 跟踪（模块级变量，需手动清理）
    lastEmittedVoice = null;

    // 让默认 get_voice_status handler 返回最近一次 emit 的负载（若有），
    // 否则返回 available:false 的 EMPTY 离线态。spec 可 override 覆盖此行为。
    router.override(CMD.GET_VOICE_STATUS, () => lastEmittedVoice ?? {
      available: false,
      state: null,
      running: false,
      fakeMode: false,
      reply: null,
      replySeq: null,
      windowMode: null,
      toolCalls: null,
    });

    // 1. exposeFunction 必须在 addInitScript 前调用：暴露 Node 侧 invoke 桥
    //    Playwright 保证 exposeFunction 在 navigation 前生效（先于 addInitScript 脚本执行）
    await page.exposeFunction(
      GLOBAL_KEYS.OMNI_E2E_CALL_ROUTER,
      async (method: string, ...args: unknown[]): Promise<unknown> => {
        if (method === "invoke") {
          const [cmd, invokeArgs] = args as [string, unknown];
          return router.invoke(cmd, invokeArgs);
        }
        return undefined;
      },
    );

    // 2. 注入 bootstrap 脚本（在每次 navigation 前执行，先于 React/源码脚本）
    await page.addInitScript(buildBootstrapScript());

    // 3. 绑定 emit dispatcher：router.emit(event, payload) → page.evaluate(dispatch)
    //    同时跟踪 voice-status 负载，让 get_voice_status 轮询兜底也返回最近一次 emit
    //    （避免 start() 首轮 delay=0 轮询与 emit race 覆盖状态）
    //    page.evaluate 不传递闭包变量，必须把 key 作为参数传入
    const E2E_ROUTER_KEY = GLOBAL_KEYS.OMNI_E2E_ROUTER;
    router._bindEmitDispatcher((event, payload) => {
      if (event === VOICE_STATUS_EVENT) {
        lastEmittedVoice = payload;
      }
      void page
        .evaluate(
          ({ event, payload, key }) => {
            const router = (window as unknown as Record<string, unknown>)[key] as
              | { dispatch(event: string, payload: unknown): void }
              | undefined;
            router?.dispatch(event, payload);
          },
          { event, payload, key: E2E_ROUTER_KEY },
        )
        .catch((err) => {
          // page 已 close 或 navigation 中途：静默丢弃，避免污染测试输出
          if (typeof process !== "undefined" && process.env?.DEBUG) {
            // eslint-disable-next-line no-console
            console.warn("[fake-tauri] emit dropped:", err);
          }
        });
    });

    await use(router);

    // 用例结束清理：避免下一个用例继承 handler / calls / emit bridge / emit 跟踪
    lastEmittedVoice = null;
    router.reset();
  },
  appPage: async ({ page, fakeTauri }, use) => {
    // fakeTauri fixture 已 setup，goto 触发 addInitScript 执行
    await page.goto(DEV_SERVER_URL);
    // 等待 bootstrap 完成标记（addInitScript 在 navigation 前，但 App 首帧挂载需 React 渲染）
    await page.waitForFunction(
      () => (window as unknown as Record<string, unknown>).__omniE2EReady === true,
      undefined,
      { timeout: 10_000 },
    );
    // 等待 hud-root 挂载（App.tsx 顶层根节点）
    await page.waitForSelector('[data-testid="hud-root"]', { timeout: 10_000 });
    // 等待 statusStore 完成 voice-status 事件订阅：
    // statusStore.start() 调 source.subscribe() → listen("voice-status")
    // → invoke("plugin:event|listen") 异步注册到 bootstrap 的 eventListeners 表。
    // 若 emit 早于注册完成，事件被静默丢弃——所有依赖 emit 注入状态的 spec 都会假阳性失败。
    // 注意：page.waitForFunction 不传闭包变量，需把 key 字面量内联到函数体内
    const routerKey = GLOBAL_KEYS.OMNI_E2E_ROUTER;
    await page.waitForFunction(
      (key: string) => {
        const router = (window as unknown as Record<string, unknown>)[key] as
          | { _listEvents?: () => string[] }
          | undefined;
        return router?._listEvents?.().includes("voice-status") === true;
      },
      routerKey,
      { timeout: 10_000 },
    );
    // 等待 statusStore 首轮轮询完成：start() 调度 voice 通道 delay=0 的首轮 poll
    // （statusStore.ts:200），poll 调 get_voice_status → 返回 EMPTY（lastEmittedVoice=null）
    // → voice.state=null → data-voice-state="idle"。
    // 若不等待首轮完成，spec emit 可能与首轮 poll race：poll 在 emit 之后返回时，
    // 即使 lastEmittedVoice 已更新，poll 的 invoke 往返延迟可能导致 poll 结果晚于 emit
    // 到达，短暂覆盖状态。等待 "idle" 确保首轮 poll 已落地、状态稳定。
    await page.waitForFunction(
      () =>
        document
          .querySelector('[data-testid="hud-root"]')
          ?.getAttribute("data-voice-state") === "idle",
      undefined,
      { timeout: 10_000 },
    );
    await use(page);
  },
});

export { expect };
