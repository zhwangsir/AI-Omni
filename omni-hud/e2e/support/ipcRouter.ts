/**
 * IPC Router：集中式 Tauri command 路由器（TEST_INFRA D1 决策）。
 *
 * 设计目标：
 * - 在 Node 侧（测试进程）模拟 Rust `invoke_handler!` 的 11 个 command 路由，
 *   让 Playwright 经 `page.exposeFunction` 把浏览器的 `__TAURI_INTERNALS__.invoke`
 *   调用桥接到本 router；
 * - 提供 `register/override/reset` API 让单个 spec 动态注入 fixture 响应；
 * - 保留 `calls()` 调用日志，spec 可断言「set_window_mode 被调用且 args.wallpaper=true」；
 * - `emit(event, payload)` 触发浏览器侧 dispatch（由 fixture.ts 绑定 page.evaluate）。
 *
 * 事件订阅本身在浏览器侧 bootstrap 脚本维护（plugin:event|listen 在浏览器本地拦截），
 * Node 侧 router 只负责把 emit 事件转交浏览器侧 dispatch。
 *
 * 不模拟真实 Rust 执行语义（不写文件、不启动线程、不访问硬件）——仅做数据响应，
 * 符合「测试零依赖」纪律（CLAUDE.md §三）。
 */
import { CMD } from "./env";

/** 单次 invoke 调用记录，供 spec 断言。 */
export interface IpcCall {
  readonly command: string;
  readonly args: unknown;
  readonly ts: number;
}

/**
 * Tauri command handler：接收 invoke 参数，返回 payload（或抛错模拟 E_CLI_FAILED）。
 *
 * 与 Rust 侧 handler 签名对齐：args 是反序列化后的 JSON 对象（camelCase），
 * 返回值会被 JSON.stringify 后送回浏览器。
 */
export type IpcHandler = (
  args: Record<string, unknown>,
) => unknown | Promise<unknown>;

/**
 * 默认 fake 响应：所有 command 都返回「源不可用」的空负载。
 *
 * - get_* 命令返回 available:false 空负载（与 src/data/sources.ts EMPTY_* 常量对齐），
 *   UI 呈现离线态而非 crash；
 * - *_tool 命令返回 E_NOT_TAURI 信封（与 src-tauri/src/music.rs 等的真实降级一致）；
 * - set_* 命令返回 void noop（仅记录 calls）。
 *
 * spec 通过 `register` / `override` 替换为具体 fixture 响应。
 */
function buildDefaultHandlers(): Map<string, IpcHandler> {
  const handlers = new Map<string, IpcHandler>();
  handlers.set(CMD.SET_CLICK_THROUGH, () => undefined);
  handlers.set(CMD.SET_ALWAYS_ON_TOP, () => undefined);
  handlers.set(CMD.SET_INTERACTIVE_ZONES, () => undefined);
  handlers.set(CMD.SET_WINDOW_MODE, () => undefined);
  handlers.set(CMD.GET_VOICE_STATUS, () => ({
    available: false,
    state: null,
    running: false,
    fakeMode: false,
    reply: null,
    replySeq: null,
    windowMode: null,
    toolCalls: null,
  }));
  handlers.set(CMD.GET_HOME_SUMMARY, () => ({
    available: false,
    demo: false,
    rooms: [],
    stats: null,
  }));
  handlers.set(CMD.GET_SYSTEM_STATS, () => ({
    available: false,
    cpuPercent: 0,
    memoryUsedBytes: 0,
    memoryTotalBytes: 0,
    networkRxBytesPerSec: 0,
    networkTxBytesPerSec: 0,
  }));
  handlers.set(CMD.VOICE_INTERRUPT, () => undefined);
  const notTauriError = (): unknown => ({
    ok: false,
    error: {
      code: "E_NOT_TAURI",
      message: "E2E fake router: tool not implemented (register handler in spec)",
    },
  });
  handlers.set(CMD.MUSIC_TOOL, notTauriError);
  handlers.set(CMD.LYRICS_TOOL, notTauriError);
  handlers.set(CMD.WEATHER_TOOL, notTauriError);
  return handlers;
}

export interface IpcRouter {
  /** 注册 / 覆盖 command handler。 */
  register(command: string, handler: IpcHandler): void;
  /** register 的语义别名，强调「在测试中动态替换」。 */
  override(command: string, handler: IpcHandler): void;
  /** 重置到默认 handler（每个 spec 用例结束自动调，避免跨用例污染）。 */
  reset(): void;
  /** 执行 invoke（由 exposeFunction 桥接调用）。 */
  invoke(command: string, args: unknown): Promise<unknown>;
  /** 全部调用日志（按时间序）。 */
  calls(): readonly IpcCall[];
  /** 某个 command 的调用日志。 */
  callsFor(command: string): readonly IpcCall[];
  /**
   * 模拟 Rust 事件推送（voice-status 等）。
   *
   * 由 fixture.ts 在 page 就绪后绑定 dispatchBridge：调用 page.evaluate
   * 触发浏览器侧 `window.__omniE2ERouter__.dispatch(event, payload)`，
   * 后者遍历 listen() 注册的回调并调用。
   */
  emit(event: string, payload: unknown): void;
  /**
   * 内部 API：fixture.ts 绑定 / 解绑 dispatchBridge。
   * 不对外暴露（仅 fixture.ts 用 getRouterInternals 取出）。
   */
  _bindEmitDispatcher(dispatch: ((event: string, payload: unknown) => void) | null): void;
}

export function createIpcRouter(): IpcRouter {
  const defaults = buildDefaultHandlers();
  let handlers = new Map(defaults);
  const calls: IpcCall[] = [];
  let dispatchBridge: ((event: string, payload: unknown) => void) | null = null;

  return {
    register(command, handler) {
      handlers.set(command, handler);
    },
    override(command, handler) {
      handlers.set(command, handler);
    },
    reset() {
      handlers = new Map(defaults);
      calls.length = 0;
      dispatchBridge = null;
    },
    async invoke(command, args) {
      calls.push({ command, args, ts: Date.now() });
      const handler = handlers.get(command);
      if (handler === undefined) {
        // 未注册的 command：模拟 Rust 「unknown command」错误
        throw new Error(`[ipc-router] unknown command: ${command}`);
      }
      return handler((args as Record<string, unknown>) ?? {});
    },
    calls() {
      return [...calls];
    },
    callsFor(command) {
      return calls.filter((c) => c.command === command);
    },
    emit(event, payload) {
      // dispatchBridge 未绑定时（fixture setup 阶段或 page 未就绪）静默丢弃；
      // spec 调用 emit 必然在 page.goto 之后，故绑定已就绪。
      if (dispatchBridge !== null) dispatchBridge(event, payload);
    },
    _bindEmitDispatcher(dispatch) {
      dispatchBridge = dispatch;
    },
  };
}
