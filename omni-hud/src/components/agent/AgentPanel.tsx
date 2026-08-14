/**
 * AgentPanel 主面板（M13.5）：雪莉对话可视化主面板。
 *
 * 布局：固定在 Full 模式下半区（CSS: position fixed, bottom 0, height 35vh,
 * max-height 280px），半透明暗房底 + backdrop-filter blur(8px)。
 *
 * 内容三层：
 * - 标题栏：「雪莉」+ 状态指示器小圆点（颜色跟随 voice.state：
 *   idle 灰 / wake_listening 蓝 / recording 红 / thinking 紫 / speaking 绿 /
 *   tool_using 橙；follow_up_listening 与 wake_listening 同蓝，transcribing 灰蓝）；
 * - 消息列表：可滚动（overflow-y: auto），新消息自动滚到底部
 *   （useEffect + ref.scrollIntoView）；空列表显示「雪莉待命中」+ Lucide Radio 图标；
 * - 消息渲染：经 MessageBubble 组件（assistant 消息附带 toolCalls 时透出槽位）。
 *
 * 行为：
 * - 订阅 statusStore.voice.state + voice.windowMode（mini 模式返回 null，防御性，
 *   App.tsx 也会做条件渲染）；
 * - 订阅 agentStore.messages（M13.5 起 agentRuntime 把 speaking + 新 replySeq
 *   同步为 assistant 消息）；
 * - pointer-events: auto（可交互、可滚动），细滚动条（::-webkit-scrollbar 暗色细线）；
 * - 入场动画：opacity 0→1 + translateY 8px→0，200ms ease-out（CSS transition）。
 *
 * 红线：无 emoji（CLAUDE.md §五）；Lucide 图标唯一（Icon.tsx 封装）；
 * Film Atelier 暗房风（深色背景、低亮度、克制动画）。
 */
import { useEffect, useRef, useSyncExternalStore } from "react";

import type { VoicePipelineState } from "../../data/sources";
import type { AgentStore } from "../../store/agentStore";
import { getAgentStore } from "../../store/agentRuntime";
import { identityStore } from "../../store/identityStore";
import type { StatusStore } from "../../store/statusStore";
import { MessageBubble } from "./MessageBubble";
import { Icon } from "../ui/Icon";

export interface AgentPanelProps {
  statusStore: StatusStore;
  /** 注入 agentStore（测试替换）；缺省走运行时单例。 */
  agentStore?: AgentStore;
}

/**
 * 语音状态 → 状态指示器颜色（Film Atelier 暗房安全灯系，低饱和克制）。
 *
 * 取值与粒子调色板 / mood 对齐：idle=暗绿（在线）、wake/speaking=灰绿（响应中）、
 * recording=灰红、transcribing=灰蓝、thinking=灰紫、tool_using=灰橙。
 * 响应态保持低饱和但在深色背景上可辨，不使用高饱和 Tailwind 亮色（§六红线）。
 */
const STATE_INDICATOR_COLOR: Record<VoicePipelineState, string> = {
  idle: "#5a6b5a",
  wake_listening: "#7fb08a",
  follow_up_listening: "#7fb08a",
  recording: "#b07a72",
  transcribing: "#7d97b8",
  thinking: "#9a8ab0",
  tool_using: "#b5a07d",
  speaking: "#7fb08a",
};

/** 状态指示器缺省颜色（voice.state 为 null / 不可用时，与 idle 同灰）。 */
const DEFAULT_INDICATOR_COLOR = "#83878f";

export function AgentPanel({ statusStore, agentStore }: AgentPanelProps): JSX.Element | null {
  const store = agentStore ?? getAgentStore();
  const voice = useSyncExternalStore(statusStore.subscribe, statusStore.getState).voice;
  const agentState = useSyncExternalStore(store.subscribe, store.getState);
  const identity = useSyncExternalStore(identityStore.subscribe, identityStore.getState).identity;
  const messages = agentState.messages;

  // 自动滚动到底部：messages 长度变化时触发。
  // 注意：所有 hooks 必须在条件 return 之前调用，避免 hooks 数量随 windowMode 变化。
  // jsdom 不实现 scrollIntoView，typeof 守卫兜底测试环境；生产浏览器一定有。
  const bottomRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = bottomRef.current;
    if (el !== null && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [messages.length]);

  // mini 模式防御性不渲染（App.tsx 也会做条件渲染，这里兜底防误挂载）。
  if (voice.windowMode === "mini") return null;

  const indicatorColor =
    voice.state !== null ? STATE_INDICATOR_COLOR[voice.state] : DEFAULT_INDICATOR_COLOR;

  const isEmpty = messages.length === 0;
  const isCompact = isEmpty && (voice.state === "idle" || voice.state === null);

  return (
    <div
      data-testid="agent-panel"
      data-voice-state={voice.state ?? "idle"}
      data-compact={isCompact ? "true" : "false"}
      className="agent-panel"
      aria-label={`${identity.display_name}对话面板`}
      style={{
        position: "fixed",
        left: 0,
        right: 0,
        bottom: 0,
        height: isCompact ? "auto" : "35vh",
        maxHeight: isCompact ? "none" : "280px",
        minHeight: isCompact ? "auto" : "160px",
        display: "flex",
        flexDirection: "column",
        background: isCompact
          ? "rgba(11, 12, 14, 0.60)"
          : "rgba(11, 12, 14, 0.72)",
        backdropFilter: isCompact ? "blur(6px)" : "blur(8px)",
        WebkitBackdropFilter: isCompact ? "blur(6px)" : "blur(8px)",
        borderTop: "1px solid var(--omni-hairline)",
        pointerEvents: "auto",
        animation: "agent-panel-enter 200ms ease-out",
        zIndex: 10,
      }}
    >
      {/* 标题栏：雪莉 + 状态指示器小圆点 */}
      <div
        data-testid="agent-panel-header"
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          padding: "8px 14px",
          borderBottom: "1px solid var(--omni-hairline)",
          userSelect: "none",
          flexShrink: 0,
        }}
      >
        <span
          data-testid="agent-panel-indicator"
          aria-hidden="true"
          className={`agent-panel-indicator ${voice.state !== "idle" && voice.state !== null ? "agent-panel-indicator-active" : ""}`}
          style={{
            display: "inline-block",
            width: "8px",
            height: "8px",
            borderRadius: "50%",
            backgroundColor: indicatorColor,
            // 呼吸感：颜色变化时 240ms 过渡（克制，不高频抖动）。
            transition: "background-color 240ms ease-out",
            boxShadow: `0 0 8px 2px ${indicatorColor}99`,
          }}
        />
        <span
          data-testid="agent-panel-title"
          style={{
            fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
            fontSize: "12px",
            letterSpacing: "0.14em",
            color: "var(--omni-fog)",
            textTransform: "uppercase",
          }}
        >
          {identity.display_name}
        </span>
      </div>

      {/* 消息列表 / 空状态 */}
      <div
        data-testid="agent-panel-messages"
        style={{
          flex: isCompact ? "0 0 auto" : "1 1 auto",
          overflowY: isCompact ? "visible" : "auto",
          padding: isCompact ? "6px 14px 8px" : "10px 14px 14px",
          display: "flex",
          flexDirection: "column",
          gap: "10px",
          scrollbarWidth: "thin",
          scrollbarColor: "rgba(216, 217, 220, 0.18) transparent",
        }}
      >
        {isEmpty ? (
          <div
            data-testid="agent-panel-empty"
            style={{
              display: "flex",
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "flex-start",
              gap: "8px",
              color: "var(--omni-dim)",
              userSelect: "none",
              padding: isCompact ? "0" : "20px 0",
            }}
          >
            <Icon name="radio" size={14} color="var(--omni-dim)" label={`${identity.display_name}待命`} />
            <span
              style={{
                fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
                fontSize: "11px",
                letterSpacing: "0.1em",
                color: "var(--omni-dim)",
              }}
            >
              {identity.display_name}待命中
            </span>
          </div>
        ) : (
          messages.map((msg) => <MessageBubble key={msg.id} message={msg} />)
        )}
        {/* 滚动锚点：始终在列表底部，messages 变化时触发 scrollIntoView。 */}
        <div ref={bottomRef} aria-hidden="true" style={{ height: 0, flexShrink: 0 }} />
      </div>
    </div>
  );
}
