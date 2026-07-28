/**
 * Agent 可视化运行时单例 + 同步器（M13.5）。
 *
 * 职责：
 * 1. 暴露 ``getAgentStore`` 进程内单例（与 statusRuntime 同款），供 AgentPanel
 *    与 App.tsx 共享同一份 agentStore 实例；
 * 2. ``bindAgentSync(statusStore, agentStore)`` 把 statusStore.voice 的变化
 *    同步到 agentStore——speaking + 新 replySeq 时把本轮回复与工具调用列表
 *    作为一条 assistant 消息追加到 messages，让 AgentPanel 自动呈现对话流。
 *
 * 同步规则（与 omni_voice 状态文件语义对齐）：
 * - ``voice.state === "speaking"`` 且 ``voice.replySeq`` 翻篇且 ``voice.reply``
 *   非空 → ``addAssistantMessage(reply, voice.toolCalls ?? [])``；
 * - 其他状态变化（idle / wake_listening / thinking / tool_using …）不同步消息——
 *   用户输入目前没有专用 transcript 字段，待后续里程碑补；
 * - 退订时清空 lastSeenSeq 快照，重新绑定从头同步。
 *
 * 单向同步：agentStore 只读 statusStore，不反向写。组件层不直接调
 * ``addUserMessage / addAssistantMessage``，避免双写。
 */
import type { VoiceStatus } from "../data/sources";
import type { StatusStore } from "./statusStore";
import { createAgentStore, type AgentStore } from "./agentStore";

let singleton: AgentStore | null = null;

/** 获取进程内 agentStore 单例（首次调用懒构造）。 */
export function getAgentStore(): AgentStore {
  singleton ??= createAgentStore();
  return singleton;
}

/**
 * 把 statusStore.voice 变化同步到 agentStore。
 *
 * 返回解绑函数（组件卸载 / 测试 teardown 调用）。
 * 幂等：多次绑定同一对 store 会产生多个独立订阅，每个都各自同步——
 * 生产环境只绑定一次（App.tsx 挂载时），测试可重复绑定。
 */
export function bindAgentSync(statusStore: StatusStore, agentStore: AgentStore): () => void {
  let lastSeenSeq: number | null = null;
  // 首次同步：把当前 replySeq 作为基线，避免挂载即把存量回复追加一次。
  const initial = statusStore.getState().voice;
  if (initial.replySeq !== null && initial.replySeq !== undefined) {
    lastSeenSeq = initial.replySeq;
  }

  const onChange = (): void => {
    const voice: VoiceStatus = statusStore.getState().voice;
    if (voice.state !== "speaking") return;
    if (voice.reply === null || voice.reply === "") return;
    const seq = voice.replySeq;
    if (seq === null || seq === undefined) return;
    if (seq === lastSeenSeq) return;
    lastSeenSeq = seq;
    // 本轮工具调用列表（M13.2）：null（旧格式）→ 不携带；[] → 携带空（自然视为无工具）。
    const toolCalls = voice.toolCalls ?? [];
    agentStore.addAssistantMessage(voice.reply, toolCalls);
  };

  const unsubscribe = statusStore.subscribe(onChange);
  return () => {
    unsubscribe();
    lastSeenSeq = null;
  };
}
