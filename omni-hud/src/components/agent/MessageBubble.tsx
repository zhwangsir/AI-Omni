/**
 * MessageBubble 组件（M13.3）：单条对话气泡。
 *
 * 渲染 user / assistant 消息，Film Atelier 暗房风：
 * - user 气泡右对齐、fog 文字色、低透明度 abyss 底（``--omni-abyss``）；
 * - assistant 气泡左对齐、accent 文字色、略高透明度 panel 底（``--omni-panel``）；
 * - 角色标签「你」/「雪莉」放气泡上方，mono 小字 + letter-spacing；
 * - assistant 消息附带 toolCalls 时透出 ``message-bubble-toolcalls`` 槽，
 *   AgentPanel 在此注入 ToolCallCard 列表（组件本身不渲染卡片细节）。
 *
 * 纯展示组件：不订阅 store、不发起 IPC、不持有状态。
 * 无 emoji（CLAUDE.md §五 / Film Atelier 风格红线）；
 * 多行文本经 ``white-space: pre-wrap`` 保留换行。
 */
import type { Message } from "./types";
import { getAssistantLabel } from "../../store/identityStore";
import { ToolCallCard } from "./ToolCallCard";

export interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps): JSX.Element {
  const { role, text, toolCalls } = message;
  const hasToolCalls = role === "assistant" && toolCalls !== undefined && toolCalls.length > 0;

  const roleLabel = role === "user" ? "你" : getAssistantLabel(role);

  return (
    <div
      data-testid="message-bubble"
      data-role={role}
      aria-label={`${roleLabel}：${text}`}
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: role === "user" ? "flex-end" : "flex-start",
        justifyContent: role === "user" ? "flex-end" : "flex-start",
        width: "100%",
        boxSizing: "border-box",
      }}
    >
      <span
        data-testid="message-bubble-role"
        style={{
          fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
          fontSize: "10px",
          letterSpacing: "0.12em",
          color: "var(--omni-dim)",
          textTransform: "uppercase",
          marginBottom: "4px",
          padding: "0 4px",
          userSelect: "none",
        }}
      >
        {roleLabel}
      </span>
      <div
        data-testid="message-bubble-inner"
        className={`message-bubble-inner message-bubble-inner--${role}`}
        style={{
          maxWidth: "80%",
          padding: "8px 12px",
          borderRadius: "var(--omni-radius)",
          borderWidth: "1px",
          borderStyle: "solid",
          borderColor: "var(--omni-hairline)",
          // user → abyss 底（近黑、低透明）；assistant → panel 底（略高透明）
          background: role === "user" ? "var(--omni-abyss)" : "var(--omni-panel)",
          // user → fog 前景；assistant → accent 前景
          color: role === "user" ? "var(--omni-fog)" : "var(--omni-accent)",
        }}
      >
        <span
          data-testid="message-bubble-text"
          style={{
            display: "inline-block",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            fontSize: "13px",
            lineHeight: 1.5,
            letterSpacing: "0.02em",
          }}
        >
          {text}
        </span>
      </div>
      {hasToolCalls && (
        <div
          data-testid="message-bubble-toolcalls"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "6px",
            width: "100%",
            marginTop: "6px",
          }}
        >
          {toolCalls.map((call) => (
            <ToolCallCard key={call.id} call={call} />
          ))}
        </div>
      )}
    </div>
  );
}
