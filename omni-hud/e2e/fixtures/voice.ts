/**
 * VoiceStatus 测试夹具（M0-M2 E2E）。
 *
 * 与 src/data/sources.ts 的 VoiceStatus 类型对齐，覆盖 8 种 VoicePipelineState
 * + windowMode 推导 + reply / replySeq / toolCalls 字段。所有 fixture 为
 * available:true 的完整负载（available:false 由 router 默认 handler 提供）。
 *
 * 字段命名严格遵循 src/data/tauriSource.ts 的 normalizeVoiceStatus 归一化结果
 * （camelCase），与 Rust 侧 serde 序列化对齐——保证 E2E 注入的负载与真实
 * Rust 推送的字段结构完全一致。
 */
import type { VoiceStatus, VoicePipelineState } from "../../src/data/sources";

/** 标签 + fixture 二元组，用于参数化测试。 */
export interface VoiceStateFixture {
  readonly label: VoicePipelineState;
  readonly status: VoiceStatus;
}

/**
 * 离线态（router 默认 handler 返回值）。
 *
 * spec 不需要显式注入——fixture.ts 默认 handler 即返回此结构。
 * 这里导出供 spec 在断言「降级到 EMPTY」时比较。
 */
export const VOICE_OFFLINE: VoiceStatus = {
  available: false,
  state: null,
  running: false,
  fakeMode: false,
  reply: null,
  replySeq: null,
  windowMode: null,
  toolCalls: null,
};

/**
 * 8 种 VoicePipelineState 对应的完整 VoiceStatus fixture。
 *
 * windowMode 选择遵循 pipeline.py derive_window_mode 的真实语义：
 * - idle → mini（待命态，HUD 收为顶部 mini bar）
 * - wake_listening / follow_up_listening → full（活跃监听，全屏显影场）
 * - recording / transcribing → full
 * - thinking / tool_using / speaking → full
 *
 * reply / replySeq 仅在 speaking 时填充（M6.3 omni_voice 实现）；
 * toolCalls 仅在 tool_using / speaking 时携带（M13.2 Agent 可视化）。
 */
function voiceFixture(
  state: VoicePipelineState,
  windowMode: "mini" | "full",
  extra: Partial<VoiceStatus> = {},
): VoiceStatus {
  return {
    available: true,
    state,
    running: true,
    fakeMode: false,
    reply: null,
    replySeq: null,
    windowMode,
    toolCalls: null,
    ...extra,
  };
}

export const VOICE_IDLE: VoiceStatus = voiceFixture("idle", "mini");

export const VOICE_WAKE_LISTENING: VoiceStatus = voiceFixture(
  "wake_listening",
  "full",
);

export const VOICE_FOLLOW_UP_LISTENING: VoiceStatus = voiceFixture(
  "follow_up_listening",
  "full",
);

export const VOICE_RECORDING: VoiceStatus = voiceFixture("recording", "full");

export const VOICE_TRANSCRIBING: VoiceStatus = voiceFixture(
  "transcribing",
  "full",
);

export const VOICE_THINKING: VoiceStatus = voiceFixture("thinking", "full");

export const VOICE_TOOL_USING: VoiceStatus = voiceFixture("tool_using", "full", {
  toolCalls: [
    {
      id: "call_1",
      toolName: "home_call_service",
      params: { entity: "light.living_room", service: "turn_on" },
      result: null,
      status: "pending",
      timestamp: 1700000000.0,
    },
  ],
});

export const VOICE_SPEAKING: VoiceStatus = voiceFixture("speaking", "full", {
  reply: "你好，我在",
  replySeq: 1,
});

/**
 * speaking 态 + replySeq=2（相同文本，新一轮回复）。
 *
 * 用于测试 replySeq 递增触发重新渲染（M6.3 修复：相同文本不同 seq 也构成语义变化）。
 */
export const VOICE_SPEAKING_SEQ2: VoiceStatus = voiceFixture("speaking", "full", {
  reply: "你好，我在",
  replySeq: 2,
});

/**
 * 8 种 VoicePipelineState 的全量 fixture 列表（用于参数化测试）。
 *
 * 顺序：idle → wake_listening → follow_up_listening → recording →
 * transcribing → thinking → tool_using → speaking
 */
export const ALL_VOICE_STATES: readonly VoiceStateFixture[] = [
  { label: "idle", status: VOICE_IDLE },
  { label: "wake_listening", status: VOICE_WAKE_LISTENING },
  { label: "follow_up_listening", status: VOICE_FOLLOW_UP_LISTENING },
  { label: "recording", status: VOICE_RECORDING },
  { label: "transcribing", status: VOICE_TRANSCRIBING },
  { label: "thinking", status: VOICE_THINKING },
  { label: "tool_using", status: VOICE_TOOL_USING },
  { label: "speaking", status: VOICE_SPEAKING },
];

/**
 * 畸形负载：缺 available 字段，应被 isVoiceStatusPayload 守卫拒绝。
 *
 * statusStore.handleSourceEvent 调用 isVoiceStatusPayload(payload)，
 * 失败则丢弃事件、保留上一次有效状态——避免非法字段污染渲染层。
 */
export const VOICE_MALFORMED_NO_AVAILABLE = {
  state: "speaking",
  running: true,
  fakeMode: false,
  // 缺 available 字段
} as unknown as VoiceStatus;

/**
 * 畸形负载：state 是非枚举字符串。
 *
 * isVoiceStatusPayload 检查 state === null || typeof state === "string"，
 * 所以畸形字符串能通过事件守卫，但 normalizeVoiceStatus 会把它收敛为 null
 * （toVoicePipelineState 返回 null）。然后 App.tsx 的 voiceState ?? "idle"
 * 会显示 "idle"。
 */
export const VOICE_MALFORMED_BAD_STATE = {
  available: true,
  state: "__invalid_state__",
  running: true,
  fakeMode: false,
  reply: null,
  replySeq: null,
  windowMode: null,
  toolCalls: null,
} as unknown as VoiceStatus;

/**
 * voice_interrupt IPC 错误响应（模拟 Rust panic / Python 退出码非零）。
 *
 * 用于测试 interruptSpeaking() 静默吞错（src/lib/voice.ts:25-32 try/catch）。
 */
export const VOICE_INTERRUPT_ERROR = new Error("E_CLI_FAILED: python3 omni_voice interrupt failed");
