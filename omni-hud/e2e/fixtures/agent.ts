/**
 * Agent 可视化测试夹具（M13 Agent 面板 E2E）。
 *
 * 与 src/data/sources.ts 的 VoiceStatus（含 toolCalls 字段）类型对齐，
 * 覆盖 tool_using / speaking 状态下携带工具调用的完整负载。
 *
 * 与 e2e/fixtures/voice.ts 的差异：
 * - voice.ts 提供 8 种 VoicePipelineState 的基础 fixture（含 VOICE_TOOL_USING / VOICE_SPEAKING）
 * - 本文件提供「携带工具调用 + 回复文本」的组合 fixture，专门用于 AgentPanel
 *   工具调用可视化测试（M13.4 ToolCallCard 渲染 + M13.5 消息同步）
 *
 * 字段命名严格遵循 src/data/tauriSource.ts 的 normalizeVoiceStatus / normalizeToolCall
 * 归一化结果（camelCase），与 Rust 侧 serde 序列化对齐。
 */
import type { VoiceStatus, ToolCallRecord } from "../../src/data/sources";

/** 构造工具调用记录的工厂函数。 */
function toolCall(
  id: string,
  toolName: string,
  params: Record<string, unknown>,
  overrides: Partial<ToolCallRecord> = {},
): ToolCallRecord {
  return {
    id,
    toolName,
    params,
    result: null,
    status: "pending",
    timestamp: 1_700_000_000,
    ...overrides,
  };
}

/**
 * tool_using 状态 + 单个 pending 工具调用（home_call_service 开灯）。
 *
 * 与 voice.ts VOICE_TOOL_USING 字段结构一致，但工具名更具语义化（home_call_service
 * 是 LLM 可能调用的工具名，omni_home 实际工具名为 home_control；此处用于测试
 * ToolCallCard 渲染，工具名只影响显示文本）。
 */
export const VOICE_TOOL_USING_HOME_LIGHT_ON: VoiceStatus = {
  available: true,
  state: "tool_using",
  running: true,
  fakeMode: false,
  reply: null,
  replySeq: null,
  windowMode: "full",
  toolCalls: [
    toolCall(
      "call_home_light_on",
      "home_call_service",
      { entity: "light.living_room", service: "turn_on" },
      { status: "pending" },
    ),
  ],
};

/**
 * tool_using 状态 + 单个 pending 工具调用（home_apply_scene 场景模式）。
 */
export const VOICE_TOOL_USING_SCENE: VoiceStatus = {
  available: true,
  state: "tool_using",
  running: true,
  fakeMode: false,
  reply: null,
  replySeq: null,
  windowMode: "full",
  toolCalls: [
    toolCall(
      "call_home_scene",
      "home_apply_scene",
      { scene: "回家模式" },
      { status: "pending" },
    ),
  ],
};

/**
 * tool_using 状态 + 单个 pending 工具调用（home_list_entities 列表查询）。
 */
export const VOICE_TOOL_USING_LIST: VoiceStatus = {
  available: true,
  state: "tool_using",
  running: true,
  fakeMode: false,
  reply: null,
  replySeq: null,
  windowMode: "full",
  toolCalls: [
    toolCall(
      "call_home_list",
      "home_list_entities",
      { room: "客厅" },
      { status: "pending" },
    ),
  ],
};

/**
 * speaking 状态 + 回复文本 + 工具调用结果（success）。
 *
 * 用于测试 tool_using → speaking 转换时工具结果保留：
 * - agentRuntime.bindAgentSync 检测 speaking + 新 replySeq → addAssistantMessage(reply, toolCalls)
 * - MessageBubble 渲染 reply 文本 + toolCalls 槽位
 * - ToolCallCard 渲染工具名 + 状态（success）+ 结果文本
 */
export const VOICE_SPEAKING_WITH_TOOLS_SUCCESS: VoiceStatus = {
  available: true,
  state: "speaking",
  running: true,
  fakeMode: false,
  reply: "已为你打开客厅主灯",
  replySeq: 1,
  windowMode: "full",
  toolCalls: [
    toolCall(
      "call_home_light_on",
      "home_call_service",
      { entity: "light.living_room", service: "turn_on" },
      {
        result: '{"ok":true,"data":{"entity":"light.living_room","state":"on"}}',
        status: "success",
      },
    ),
  ],
};

/**
 * speaking 状态 + 回复文本 + 工具调用结果（error）。
 *
 * 用于测试工具调用失败时的可视化：ToolCallCard 渲染 error 状态 + 错误结果文本。
 */
export const VOICE_SPEAKING_WITH_TOOLS_ERROR: VoiceStatus = {
  available: true,
  state: "speaking",
  running: true,
  fakeMode: false,
  reply: "抱歉，开灯失败了，请稍后再试",
  replySeq: 1,
  windowMode: "full",
  toolCalls: [
    toolCall(
      "call_home_light_on",
      "home_call_service",
      { entity: "light.living_room", service: "turn_on" },
      {
        result: "错误：HA 不可达（E_CONNECTION_REFUSED）",
        status: "error",
      },
    ),
  ],
};

/**
 * speaking 状态 + 回复文本 + 多个工具调用（pending + success 混合）。
 *
 * 用于测试多工具调用的完整渲染：开灯 success + 查询 pending。
 */
export const VOICE_SPEAKING_WITH_MULTI_TOOLS: VoiceStatus = {
  available: true,
  state: "speaking",
  running: true,
  fakeMode: false,
  reply: "已为你打开客厅灯，正在查询空调状态",
  replySeq: 1,
  windowMode: "full",
  toolCalls: [
    toolCall(
      "call_home_light_on",
      "home_call_service",
      { entity: "light.living_room", service: "turn_on" },
      {
        result: '{"ok":true,"data":{"state":"on"}}',
        status: "success",
      },
    ),
    toolCall(
      "call_home_query",
      "home_query",
      { command: "客厅空调状态" },
      { status: "pending" },
    ),
  ],
};

/**
 * 第二轮 speaking（replySeq=2）：用于测试多轮对话消息顺序。
 *
 * agentRuntime.bindAgentSync 检测 replySeq 从 1 → 2，追加新 assistant 消息。
 */
export const VOICE_SPEAKING_ROUND_2: VoiceStatus = {
  available: true,
  state: "speaking",
  running: true,
  fakeMode: false,
  reply: "好的，我已经帮你关掉了",
  replySeq: 2,
  windowMode: "full",
  toolCalls: null,
};

/**
 * 第三轮 speaking（replySeq=3）：用于测试多轮对话消息顺序 + 自动滚动。
 */
export const VOICE_SPEAKING_ROUND_3: VoiceStatus = {
  available: true,
  state: "speaking",
  running: true,
  fakeMode: false,
  reply: "还有什么可以帮你的吗？",
  replySeq: 3,
  windowMode: "full",
  toolCalls: null,
};

/**
 * 纯文本 speaking（无工具调用）：replySeq=1，toolCalls=null。
 *
 * 用于测试 speaking + reply 但无工具调用时的纯消息渲染。
 */
export const VOICE_SPEAKING_PLAIN: VoiceStatus = {
  available: true,
  state: "speaking",
  running: true,
  fakeMode: false,
  reply: "你好，我在",
  replySeq: 1,
  windowMode: "full",
  toolCalls: null,
};
