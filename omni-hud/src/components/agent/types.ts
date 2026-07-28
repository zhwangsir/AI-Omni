/**
 * Agent 可视化数据模型（M13.1）：对话气泡 + 工具调用记录。
 *
 * 三层结构：
 * - ``ToolCallRecord``：单次工具调用（pending/success/error 三态）；
 * - ``Message``：对话气泡（user / assistant），assistant 可附带多张工具调用卡片；
 * - ``AgentSession``：完整会话快照（messages + 当前轮次进行中的工具调用）。
 *
 * 数据来源：Python state_file.tool_calls 字段（M13.2 起） → Rust voice_watch
 * 透传 → 前端 statusStore → agentRuntime 同步到 agentStore。这里只定义类型
 * 与运行时守卫，不耦合具体 IPC 实现。
 */

/** 工具调用状态：pending=加载中 / success=成功 / error=失败。 */
export type ToolCallStatus = "pending" | "success" | "error";

export interface ToolCallRecord {
  /** 唯一 ID（reply_seq + 序号 或独立 uuid）。 */
  readonly id: string;
  /** 工具名（如 home_control_light）。 */
  readonly toolName: string;
  /** 调用参数（JSON 解析后的对象）。 */
  readonly params: Record<string, unknown>;
  /** 工具返回结果（JSON 字符串）；null 表示尚未返回（pending）。 */
  readonly result: string | null;
  /** 调用状态。 */
  readonly status: ToolCallStatus;
  /** 调用时间戳（ms 或 s，由调用方约定）。 */
  readonly timestamp: number;
}

export type MessageRole = "user" | "assistant";

export interface Message {
  /** 消息唯一 ID。 */
  readonly id: string;
  /** 角色：user = 用户输入 / assistant = 雪莉回复。 */
  readonly role: MessageRole;
  /** 消息文本。 */
  readonly text: string;
  /** 消息时间戳。 */
  readonly timestamp: number;
  /** assistant 消息可附带工具调用列表（按调用顺序排列）。 */
  readonly toolCalls?: readonly ToolCallRecord[];
}

export interface AgentSession {
  /** 完整对话消息列表（按时间顺序）。 */
  readonly messages: readonly Message[];
  /** 当前轮次进行中（pending）的工具调用，便于 UI 顶部高亮显示。 */
  readonly currentToolCalls: readonly ToolCallRecord[];
}

/** 空会话快照（启动态 / 无交互时）。 */
export const EMPTY_AGENT_SESSION: AgentSession = {
  messages: [],
  currentToolCalls: [],
};

const TOOL_CALL_STATUSES: ReadonlySet<string> = new Set<ToolCallStatus>([
  "pending",
  "success",
  "error",
]);

const MESSAGE_ROLES: ReadonlySet<string> = new Set<MessageRole>([
  "user",
  "assistant",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object";
}

/**
 * 运行时守卫：判断输入是否为合法 ToolCallRecord。
 *
 * IPC 边界 / 状态文件解析出的数据不可信，组件层使用前必须经此守卫，
 * 畸形数据被 agentRuntime 丢弃而非 crash。
 */
export function isToolCallRecord(raw: unknown): raw is ToolCallRecord {
  if (!isRecord(raw)) return false;
  if (typeof raw.id !== "string") return false;
  if (typeof raw.toolName !== "string") return false;
  if (!isRecord(raw.params)) return false;
  if (raw.result !== null && typeof raw.result !== "string") return false;
  if (typeof raw.status !== "string" || !TOOL_CALL_STATUSES.has(raw.status)) {
    return false;
  }
  if (typeof raw.timestamp !== "number") return false;
  return true;
}

/**
 * 运行时守卫：判断输入是否为合法 Message。
 *
 * toolCalls 字段可选；存在时每个元素必须经 isToolCallRecord 守卫。
 */
export function isMessage(raw: unknown): raw is Message {
  if (!isRecord(raw)) return false;
  if (typeof raw.id !== "string") return false;
  if (typeof raw.role !== "string" || !MESSAGE_ROLES.has(raw.role)) {
    return false;
  }
  if (typeof raw.text !== "string") return false;
  if (typeof raw.timestamp !== "number") return false;
  if (raw.toolCalls !== undefined) {
    if (!Array.isArray(raw.toolCalls)) return false;
    for (const tc of raw.toolCalls) {
      if (!isToolCallRecord(tc)) return false;
    }
  }
  return true;
}
