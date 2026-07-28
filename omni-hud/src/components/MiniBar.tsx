/**
 * MiniBar 组件（M12 灵动岛双形态）：Mini 浮窗的状态文字层。
 *
 * idle 待命态时 Full cover-display 退化为顶部 240×48 浮窗，仅显示精简
 * 状态文字（如「雪莉 · 待命」），让出桌面视野。活跃语音交互时窗口切回
 * Full 形态，MiniBar 不渲染（App.tsx 根据 windowMode 切换布局）。
 *
 * 契约：
 * - 订阅 statusStore.voice.state → 渲染对应中文状态文字；
 * - pointer-events: none（Rust 分区轮询 Mini 形态下全穿透，浮窗不拦截桌面点击）；
 * - aria-hidden=true（观察性状态显示，不承担交互语义）；
 * - 无 emoji（Film Atelier 风格，纯排版无装饰）。
 *
 * 窗口几何（240×48 顶部居中）由 Rust 侧 apply_mini_geometry 设置；
 * MiniBar 仅负责内容渲染，不控制窗口大小。
 */
import { useSyncExternalStore } from "react";

import type { VoicePipelineState } from "../data/sources";
import { identityStore } from "../store/identityStore";
import type { StatusStore } from "../store/statusStore";

export interface MiniBarProps {
  statusStore: StatusStore;
}

export function MiniBar({ statusStore }: MiniBarProps): JSX.Element {
  const voice = useSyncExternalStore(statusStore.subscribe, statusStore.getState).voice;
  const identity = useSyncExternalStore(identityStore.subscribe, identityStore.getState).identity;
  const idleLabel = identity.idle_label;

  const stateLabels: Record<VoicePipelineState, string> = {
    idle: idleLabel,
    wake_listening: "唤醒中…",
    follow_up_listening: "续听中…",
    recording: "聆听中…",
    transcribing: "转写中…",
    thinking: "思考中…",
    tool_using: "调用工具…",
    speaking: "应答中…",
  };

  const label = voice.state !== null ? stateLabels[voice.state] : idleLabel;

  return (
    <div
      data-testid="mini-bar"
      aria-hidden="true"
      style={{
        pointerEvents: "none",
        width: "100%",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <span
        data-testid="mini-bar-status-text"
        style={{
          fontFamily: "'SF Mono', 'JetBrains Mono', ui-monospace, monospace",
          fontSize: "14px",
          fontWeight: 400,
          letterSpacing: "0.04em",
          color: "rgba(216, 217, 220, 0.85)",
          textShadow: "0 1px 2px rgba(0, 0, 0, 0.5)",
          userSelect: "none",
          whiteSpace: "nowrap",
        }}
      >
        {label}
      </span>
    </div>
  );
}
