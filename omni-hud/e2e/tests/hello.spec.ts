/**
 * Hello world smoke test：验证 fake Tauri IPC 注入 + dev server + App 挂载链路通畅。
 *
 * 不覆盖具体业务功能，只验证基础设施（TEST_INFRA 阶段 2 出口）：
 * 1. dev server 启动 + baseURL 可访问
 * 2. addInitScript 注入的 __TAURI_INTERNALS__ 生效（isTauri() 返回 true）
 * 3. App 挂载 hud-root 节点
 * 4. fakeTauri router 默认 handler 响应 get_voice_status（available:false）
 * 5. router.emit 触发浏览器侧 listen 回调（事件链路通畅）
 *
 * 通过后即可推进阶段 3-12 的业务 spec。
 *
 * 注意：page.evaluate 内不能 import 第三方模块（bare specifier 不被 Vite 转译），
 * 因此直接调用 `window.__TAURI_INTERNALS__.invoke` —— 这正是 @tauri-apps/api/core
 * 的 invoke() 内部实现（见 node_modules/@tauri-apps/api/core.js:201-202）。
 */
import { test, expect } from "../support/fixture";
import { VOICE_STATUS_EVENT, GLOBAL_KEYS } from "../support/env";

test.describe("hello world · fake Tauri IPC 注入", () => {
  test("dev server 启动 + App 挂载 hud-root", async ({ appPage }) => {
    await expect(appPage.locator('[data-testid="hud-root"]')).toBeVisible();
  });

  test("__TAURI_INTERNALS__ 已注入（isTauri 返回 true）", async ({ appPage }) => {
    const isTauriInjected = await appPage.evaluate(() => {
      return "__TAURI_INTERNALS__" in window;
    });
    expect(isTauriInjected).toBe(true);
  });

  test("__omniE2ERouter__ 与 ready 标记已就位", async ({ appPage }) => {
    const status = await appPage.evaluate(() => {
      const w = window as unknown as Record<string, unknown>;
      return {
        router: "__omniE2ERouter__" in window,
        ready: w.__omniE2EReady === true,
      };
    });
    expect(status.router).toBe(true);
    expect(status.ready).toBe(true);
    // 防止常量漂移：编译期校验 GLOBAL_KEYS 与运行时 key 字面量一致
    expect(GLOBAL_KEYS.OMNI_E2E_ROUTER).toBe("__omniE2ERouter__");
  });

  test("router 默认 handler 响应 get_voice_status（available:false）", async ({
    appPage,
    fakeTauri,
  }) => {
    // 直接调用 window.__TAURI_INTERNALS__.invoke —— 与 @tauri-apps/api/core 的 invoke 等价
    const result = await appPage.evaluate(async () => {
      const internals = (window as unknown as {
        __TAURI_INTERNALS__: {
          invoke(cmd: string, args?: unknown): Promise<unknown>;
        };
      }).__TAURI_INTERNALS__;
      return internals.invoke("get_voice_status");
    });
    expect(result).toMatchObject({ available: false, running: false });
    // router 记录了调用日志
    const calls = fakeTauri.callsFor("get_voice_status");
    expect(calls.length).toBeGreaterThanOrEqual(1);
  });

  test("router.emit 触发 listen() 回调（事件链路通畅）", async ({ appPage, fakeTauri }) => {
    // 用 transformCallback 注册一个把 payload 写到 window 的回调，
    // 模拟 @tauri-apps/api/event 的 listen() 内部实现（见 event.js:71-82）
    const setupInfo = await appPage.evaluate(() => {
      const internals = (window as unknown as {
        __TAURI_INTERNALS__: {
          transformCallback(cb: (payload: unknown) => void): number;
          invoke(cmd: string, args?: unknown): Promise<unknown>;
        };
      }).__TAURI_INTERNALS__;
      const handlerId = internals.transformCallback((payload) => {
        (window as unknown as Record<string, unknown>).__omniE2E_lastEvent =
          payload;
      });
      return internals
        .invoke("plugin:event|listen", {
          event: "voice-status",
          handler: handlerId,
        })
        .then(() => ({ handlerId, listeners: (window as unknown as { __omniE2ERouter__: { _listEvents(): string[] } }).__omniE2ERouter__._listEvents() }));
    });
    // 调试：确认 listener 已注册
    expect(setupInfo.listeners).toContain("voice-status");

    // 直接在浏览器侧调用 dispatch 验证 bootstrap 自洽
    await appPage.evaluate(() => {
      (window as unknown as { __omniE2ERouter__: { dispatch(e: string, p: unknown): void } }).__omniE2ERouter__.dispatch("voice-status", { direct: true });
    });
    await expect
      .poll(async () =>
        appPage.evaluate(
          () => (window as unknown as Record<string, unknown>).__omniE2E_lastEvent,
        ),
      )
      .toMatchObject({ event: "voice-status", payload: { direct: true } });

    // 清空后用 Node 侧 emit 重测
    await appPage.evaluate(() => {
      delete (window as unknown as Record<string, unknown>).__omniE2E_lastEvent;
    });
    fakeTauri.emit(VOICE_STATUS_EVENT, { available: true, state: "speaking" });

    await expect
      .poll(async () =>
        appPage.evaluate(
          () =>
            (window as unknown as Record<string, unknown>).__omniE2E_lastEvent,
        ),
      )
      .toMatchObject({
        event: "voice-status",
        payload: { available: true, state: "speaking" },
      });
  });

  test("未注册的 command 抛错（unknown command 模拟）", async ({ appPage }) => {
    const error = await appPage.evaluate(async () => {
      const internals = (window as unknown as {
        __TAURI_INTERNALS__: {
          invoke(cmd: string, args?: unknown): Promise<unknown>;
        };
      }).__TAURI_INTERNALS__;
      try {
        await internals.invoke("__nonexistent_command__");
        return null;
      } catch (e) {
        return (e as Error).message;
      }
    });
    expect(error).toContain("unknown command");
  });
});
