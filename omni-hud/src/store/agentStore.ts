/**
 * Agent 可视化会话状态 store（M13.1）。
 *
 * 维护对话气泡（user / assistant）与当前轮次进行中的工具调用记录，
 * 驱动 AgentPanel 渲染。框架无关订阅模式（与 hudStore/statusStore 同款），
 * React 侧经 useSyncExternalStore 绑定。
 *
 * 数据来源（M13.2 起）：agentRuntime 监听 statusStore.voice.reply /
 * voice.toolCalls 变化，调本 store 的 actions 同步——store 自身不感知 IPC。
 *
 * 一轮交互的生命周期：
 *   addUserMessage(text)         → 用户输入（transcribing 完成时）
 *   addToolCall(record)          → LLM 请求工具（voice.tool_start）
 *   updateToolCall(id, patch)    → 工具返回（voice.tool_end）
 *   addAssistantMessage(text, calls) → LLM 最终回复（speaking），清空 currentToolCalls
 *
 * clearSession 用于续听超时 / 用户主动清空。
 */
import type { Message, ToolCallRecord } from "../components/agent/types";

export interface AgentState {
  /** 完整对话消息列表（按时间顺序）。 */
  readonly messages: readonly Message[];
  /** 当前轮次进行中（pending/success/error）的工具调用，UI 顶部高亮显示。 */
  readonly currentToolCalls: readonly ToolCallRecord[];
}

export interface AgentStore {
  getState: () => AgentState;
  subscribe: (listener: () => void) => () => void;
  /** 添加用户输入消息。 */
  addUserMessage: (text: string) => void;
  /**
   * 添加雪莉回复消息，可携带本轮已完成的工具调用列表。
   * 调用后 currentToolCalls 清空（本轮结束）。
   */
  addAssistantMessage: (text: string, toolCalls?: readonly ToolCallRecord[]) => void;
  /** 添加进行中的工具调用到 currentToolCalls。 */
  addToolCall: (record: ToolCallRecord) => void;
  /** 更新工具调用结果；id 不存在时静默忽略（容错）。 */
  updateToolCall: (id: string, patch: Partial<Pick<ToolCallRecord, "result" | "status">>) => void;
  /** 清空会话（续听超时 / 用户主动清空）。 */
  clearSession: () => void;
}

/** 单调递增的消息 id 计数器（进程内）。 */
let messageIdCounter = 0;

function nextMessageId(prefix: string): string {
  messageIdCounter += 1;
  return `${prefix}-${messageIdCounter}`;
}

export function createAgentStore(): AgentStore {
  let state: AgentState = {
    messages: [],
    currentToolCalls: [],
  };
  const listeners = new Set<() => void>();

  const emit = (): void => {
    for (const listener of listeners) listener();
  };

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    addUserMessage(text) {
      const msg: Message = {
        id: nextMessageId("u"),
        role: "user",
        text,
        timestamp: Date.now(),
      };
      state = {
        ...state,
        messages: [...state.messages, msg],
      };
      emit();
    },
    addAssistantMessage(text, toolCalls) {
      const msg: Message = {
        id: nextMessageId("a"),
        role: "assistant",
        text,
        timestamp: Date.now(),
        toolCalls: toolCalls && toolCalls.length > 0 ? [...toolCalls] : undefined,
      };
      state = {
        messages: [...state.messages, msg],
        // 本轮结束：清空进行中的工具调用
        currentToolCalls: [],
      };
      emit();
    },
    addToolCall(record) {
      state = {
        ...state,
        currentToolCalls: [...state.currentToolCalls, record],
      };
      emit();
    },
    updateToolCall(id, patch) {
      let found = false;
      const nextCalls = state.currentToolCalls.map((c) => {
        if (c.id !== id) return c;
        found = true;
        return { ...c, ...patch };
      });
      if (!found) return; // 静默忽略未知 id
      state = {
        ...state,
        currentToolCalls: nextCalls,
      };
      emit();
    },
    clearSession() {
      if (state.messages.length === 0 && state.currentToolCalls.length === 0) return;
      state = {
        messages: [],
        currentToolCalls: [],
      };
      emit();
    },
  };
}
