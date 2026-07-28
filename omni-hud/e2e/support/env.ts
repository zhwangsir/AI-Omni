/**
 * E2E 测试环境常量（TEST_INFRA 里程碑）。
 *
 * 集中管理 dev server URL / Tauri command 名 / 全局对象 key，
 * 避免散落字符串在测试代码中导致拼写漂移。
 *
 * 与 src/lib/window.ts、src/data/tauriSource.ts 的导出常量保持同名同值，
 * 但 E2E 侧独立维护（不 import src/），符合项目隔离纪律。
 */

/** Vite dev server 地址（与 vite.config.ts strictPort 1420 对齐）。 */
export const DEV_SERVER_URL = "http://localhost:1420";

/**
 * Tauri command 注册表（与 src-tauri/src/lib.rs:376-388 generate_handler! 一一对应）。
 *
 * E2E 侧独立常量，不 import src/lib/window.ts 的导出——避免 vitest 与 Playwright
 * 共享运行时模块导致跨测试框架耦合（D5 决策：不分离 vite.config.ts，但隔离代码）。
 */
export const CMD = {
  SET_CLICK_THROUGH: "set_click_through",
  SET_ALWAYS_ON_TOP: "set_always_on_top",
  SET_INTERACTIVE_ZONES: "set_interactive_zones",
  SET_WINDOW_MODE: "set_window_mode",
  GET_VOICE_STATUS: "get_voice_status",
  GET_HOME_SUMMARY: "get_home_summary",
  GET_SYSTEM_STATS: "get_system_stats",
  VOICE_INTERRUPT: "voice_interrupt",
  MUSIC_TOOL: "music_tool",
  LYRICS_TOOL: "lyrics_tool",
  WEATHER_TOOL: "weather_tool",
} as const;

/**
 * 浏览器侧注入的全局对象 key。
 *
 * - `__TAURI_INTERNALS__`：@tauri-apps/api/core 的 invoke / transformCallback 入口
 *   （src/lib/window.ts:25 isTauri() 通过 `"__TAURI_INTERNALS__" in window` 检测）
 * - `__TAURI_EVENT_PLUGIN_INTERNALS__`：@tauri-apps/api/event 的 unregisterListener 入口
 * - `__omniE2ERouter__`：bootstrap 脚本暴露的 emit / debug API，测试侧经 evaluate 调用
 * - `__omniE2E_callRouter`：page.exposeFunction 暴露的 Node 侧 router 入口
 */
export const GLOBAL_KEYS = {
  TAURI_INTERNALS: "__TAURI_INTERNALS__",
  TAURI_EVENT_PLUGIN_INTERNALS: "__TAURI_EVENT_PLUGIN_INTERNALS__",
  OMNI_E2E_ROUTER: "__omniE2ERouter__",
  OMNI_E2E_CALL_ROUTER: "__omniE2E_callRouter",
  OMNI_DEBUG: "__omniDebug",
} as const;

/**
 * voice-status 事件名（与 src/data/sources.ts:128 VOICE_STATUS_EVENT 对齐）。
 *
 * Rust voice_watch 模块经此事件推送 VoiceStatus 变化；
 * E2E 测试通过 router.emit(VOICE_STATUS_EVENT, payload) 模拟推送。
 */
export const VOICE_STATUS_EVENT = "voice-status";
