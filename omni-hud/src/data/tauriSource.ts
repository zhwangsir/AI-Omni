/**
 * Tauri IPC 数据源：经 invoke 调 Rust commands（get_voice_status /
 * get_home_summary / get_system_stats）获取真实状态；M5.4 起同时经
 * listen("voice-status") 订阅 Rust voice_watch 的状态文件事件推送。
 *
 * invoke / event 返回值是不可信的 IPC 边界数据，统一经 normalize_* 防御性映射；
 * 非 Tauri 环境（纯浏览器 / vitest）与 invoke / listen 失败一律降级为
 * available:false 空负载（订阅则退化为 noop 退订），由 store 呈现离线态
 * 或保留轮询兜底，而非报错刷屏。
 */
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

import { isTauri } from "../lib/window";
import {
  EMPTY_HOME_SUMMARY,
  EMPTY_SYSTEM_STATS,
  EMPTY_VOICE_STATUS,
  VOICE_STATUS_EVENT,
  type HomeDeviceBrief,
  type HomeRoomBrief,
  type HomeSummary,
  type HudDataSource,
  type HudSourceEventListener,
  type SystemStats,
  type ToolCallRecord,
  type ToolCallStatus,
  type VoicePipelineState,
  type VoiceStatus,
  type WindowMode,
} from "./sources";

export const CMD_GET_VOICE_STATUS = "get_voice_status";
export const CMD_GET_HOME_SUMMARY = "get_home_summary";
export const CMD_GET_SYSTEM_STATS = "get_system_stats";

const VOICE_PIPELINE_STATES: ReadonlySet<string> = new Set<VoicePipelineState>([
  "idle",
  "wake_listening",
  "follow_up_listening",
  "recording",
  "transcribing",
  "thinking",
  "tool_using",
  "speaking",
]);

/** 把不可信输入收敛为已知管道状态；无法识别返回 null。 */
export function toVoicePipelineState(raw: unknown): VoicePipelineState | null {
  if (typeof raw === "string" && VOICE_PIPELINE_STATES.has(raw)) {
    return raw as VoicePipelineState;
  }
  return null;
}

/** 把不可信输入收敛为已知窗口形态（M12）；无法识别返回 null（前端按 full 缺省）。 */
export function toWindowMode(raw: unknown): WindowMode | null {
  if (raw === "mini" || raw === "full") return raw;
  return null;
}

const TOOL_CALL_STATUSES: ReadonlySet<string> = new Set<ToolCallStatus>([
  "pending",
  "success",
  "error",
]);

/**
 * M13.2：把不可信的单个工具调用元素归一为 ``ToolCallRecord``。
 *
 * Rust 侧已做 snake_case → camelCase 归一，这里做 IPC 边界防御性兜底：
 * 任一必填字段缺失 / 类型不符返回 null（元素被 ``normalizeToolCalls`` 过滤）。
 * ``params`` 必须是对象（非数组 / 非标量）；``status`` 必须是 pending/success/error。
 */
export function normalizeToolCall(raw: unknown): ToolCallRecord | null {
  const obj = asRecord(raw);
  if (obj === null) return null;
  if (typeof obj.id !== "string" || typeof obj.toolName !== "string") return null;
  // params 必须是对象（非 null / 非数组）；数组在 JS 中 typeof 也是 "object"，需显式排除。
  const params = obj.params;
  if (params === null || typeof params !== "object" || Array.isArray(params)) return null;
  if (obj.result !== null && typeof obj.result !== "string") return null;
  if (typeof obj.status !== "string" || !TOOL_CALL_STATUSES.has(obj.status)) return null;
  const timestamp = asFiniteNumber(obj.timestamp);
  if (timestamp === null) return null;
  return {
    id: obj.id,
    toolName: obj.toolName,
    params: params as Record<string, unknown>,
    result: typeof obj.result === "string" ? obj.result : null,
    status: obj.status as ToolCallStatus,
    timestamp,
  };
}

/**
 * M13.2：把不可信的 ``toolCalls`` 字段归一为 ``ToolCallRecord[] | null``。
 *
 * - 非数组（字符串 / 对象 / 标量）→ ``null``（与旧格式兼容，前端不渲染）；
 * - 数组 → 每个元素经 ``normalizeToolCall`` 守卫，非法元素被过滤；
 *   空数组保留为 ``[]``（表示本轮工具链已结束，与 null 语义区分）。
 */
export function normalizeToolCalls(raw: unknown): readonly ToolCallRecord[] | null {
  if (!Array.isArray(raw)) return null;
  return raw
    .map(normalizeToolCall)
    .filter((c): c is ToolCallRecord => c !== null);
}

function asRecord(raw: unknown): Record<string, unknown> | null {
  return raw !== null && typeof raw === "object" ? (raw as Record<string, unknown>) : null;
}

function asFiniteNumber(raw: unknown): number | null {
  return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
}

function normalizeDevice(raw: unknown): HomeDeviceBrief | null {
  const obj = asRecord(raw);
  if (obj === null || typeof obj.name !== "string") return null;
  return {
    name: obj.name,
    stateText: typeof obj.stateText === "string" ? obj.stateText : "",
  };
}

function normalizeRoom(raw: unknown): HomeRoomBrief | null {
  const obj = asRecord(raw);
  if (obj === null || typeof obj.name !== "string") return null;
  const devices = Array.isArray(obj.devices)
    ? obj.devices.map(normalizeDevice).filter((d): d is HomeDeviceBrief => d !== null)
    : [];
  return { name: obj.name, devices };
}

function normalizeVoiceStatus(raw: unknown): VoiceStatus {
  const obj = asRecord(raw);
  if (obj === null || obj.available !== true) return EMPTY_VOICE_STATUS;
  return {
    available: true,
    state: toVoicePipelineState(obj.state),
    running: obj.running === true,
    fakeMode: obj.fakeMode === true,
    // M6.3：reply 缺省（旧版 Rust 未升级）或非字符串一律归 null。
    reply: typeof obj.reply === "string" ? obj.reply : null,
    // reply_seq（轮次序号）同理：仅非负整数透传，缺省/非法归 null。
    replySeq:
      typeof obj.replySeq === "number" && Number.isInteger(obj.replySeq) && obj.replySeq >= 0
        ? obj.replySeq
        : null,
    // M12：window_mode 缺省（旧版 Rust/Python 未升级）或非 mini/full 一律归 null，
    // 前端按 full 缺省处理（安全态）。
    windowMode: toWindowMode(obj.windowMode),
    // M13.2：toolCalls 非数组归 null（旧格式兼容）；数组经 normalizeToolCalls 守卫，
    // 非法元素被过滤；空数组保留为 []（本轮工具链已结束）。
    toolCalls: normalizeToolCalls(obj.toolCalls),
  };
}

function normalizeHomeSummary(raw: unknown): HomeSummary {
  const obj = asRecord(raw);
  if (obj === null || obj.available !== true) return EMPTY_HOME_SUMMARY;
  const statsObj = asRecord(obj.stats);
  const devices = statsObj === null ? null : asFiniteNumber(statsObj.devices);
  const rooms = statsObj === null ? null : asFiniteNumber(statsObj.rooms);
  return {
    available: true,
    demo: obj.demo === true,
    rooms: Array.isArray(obj.rooms)
      ? obj.rooms.map(normalizeRoom).filter((r): r is HomeRoomBrief => r !== null)
      : [],
    stats: devices !== null && rooms !== null ? { devices, rooms } : null,
  };
}

function normalizeSystemStats(raw: unknown): SystemStats {
  const obj = asRecord(raw);
  if (obj === null || obj.available !== true) return EMPTY_SYSTEM_STATS;
  const cpuPercent = asFiniteNumber(obj.cpuPercent);
  const memoryUsedBytes = asFiniteNumber(obj.memoryUsedBytes);
  const memoryTotalBytes = asFiniteNumber(obj.memoryTotalBytes);
  const networkRxBytesPerSec = asFiniteNumber(obj.networkRxBytesPerSec);
  const networkTxBytesPerSec = asFiniteNumber(obj.networkTxBytesPerSec);
  if (
    cpuPercent === null ||
    memoryUsedBytes === null ||
    memoryTotalBytes === null ||
    networkRxBytesPerSec === null ||
    networkTxBytesPerSec === null
  ) {
    return EMPTY_SYSTEM_STATS;
  }
  return {
    available: true,
    cpuPercent,
    memoryUsedBytes,
    memoryTotalBytes,
    networkRxBytesPerSec,
    networkTxBytesPerSec,
  };
}

async function invokeGuarded<T>(command: string, normalize: (raw: unknown) => T): Promise<T> {
  const unavailable = normalize(null);
  if (!isTauri()) return unavailable;
  try {
    return normalize(await invoke(command));
  } catch {
    return unavailable;
  }
}

/**
 * 订阅 Rust voice_watch 的 voice-status 事件推送（M5.4）。
 *
 * - 事件负载先经 normalizeVoiceStatus 归一化再送达 listener（IPC 边界防御）；
 * - listen 是异步注册：退订发生在 resolve 之前时，resolve 后立即反注册，
 *   不留悬挂监听；
 * - 非 Tauri 环境或注册失败一律退化为 noop 退订——调用方保留轮询兜底。
 */
function subscribeVoiceStatus(listener: HudSourceEventListener): () => void {
  if (!isTauri()) return () => {};
  let unlisten: UnlistenFn | null = null;
  let disposed = false;
  listen(VOICE_STATUS_EVENT, (event) => {
    listener({ type: VOICE_STATUS_EVENT, payload: normalizeVoiceStatus(event.payload) });
  })
    .then((fn) => {
      if (disposed) fn();
      else unlisten = fn;
    })
    .catch(() => {});
  return () => {
    disposed = true;
    unlisten?.();
  };
}

export function createTauriSource(): HudDataSource {
  return {
    voiceStatus: () => invokeGuarded(CMD_GET_VOICE_STATUS, normalizeVoiceStatus),
    homeSummary: () => invokeGuarded(CMD_GET_HOME_SUMMARY, normalizeHomeSummary),
    systemStats: () => invokeGuarded(CMD_GET_SYSTEM_STATS, normalizeSystemStats),
    subscribe: subscribeVoiceStatus,
  };
}
