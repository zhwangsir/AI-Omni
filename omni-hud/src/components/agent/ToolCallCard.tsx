/**
 * ToolCallCard 组件（M13.4）：单次工具调用卡片。
 *
 * 渲染 ``ToolCallRecord``，Film Atelier 暗房风：
 * - header：工具名 + 状态指示器（Icon.tsx：activity=调用中 / sun=已完成 / square=失败）；
 * - 参数区：始终显示，JSON 字符串（便于调试与可读）；
 * - 结果区：``status !== pending`` 且 ``result !== null`` 时显示；
 * - 状态文字：``调用中`` / ``已完成`` / ``失败``。
 *
 * 「思考过程」视图设计：参数与结果始终可见，让用户一目了然看到 LLM 调用了
 * 什么、传了什么参数、得到了什么结果。不引入折叠交互——避免额外点击负担。
 *
 * 纯展示组件：不订阅 store、不发起 IPC、不持有外部状态。
 * 无 emoji（CLAUDE.md §五 / Film Atelier 风格红线）。
 */
import { Icon, type IconName } from "../ui/Icon";
import type { ToolCallRecord, ToolCallStatus } from "./types";

export interface ToolCallCardProps {
  call: ToolCallRecord;
}

/** 状态 → 中文短标签。 */
const STATUS_LABEL: Record<ToolCallStatus, string> = {
  pending: "调用中",
  success: "已完成",
  error: "失败",
};

/** 状态 → Icon 名（lucide 图标经 Icon.tsx 统一封装）。 */
const STATUS_ICON: Record<ToolCallStatus, IconName> = {
  pending: "activity",
  success: "sun",
  error: "square",
};

export function ToolCallCard({ call }: ToolCallCardProps): JSX.Element {
  const { toolName, params, result, status } = call;
  const statusLabel = STATUS_LABEL[status];
  const iconName = STATUS_ICON[status];
  const hasResult = status !== "pending" && result !== null;
  const accent = statusColor(status);

  return (
    <div
      data-testid="tool-call-card"
      data-status={status}
      aria-label={`工具调用 ${toolName}：${statusLabel}`}
      style={{
        display: "flex",
        flexDirection: "column",
        width: "100%",
        boxSizing: "border-box",
        padding: "8px 10px",
        borderRadius: "var(--omni-radius)",
        borderWidth: "1px",
        borderStyle: "solid",
        borderColor: statusBorder(status),
        background: "var(--omni-panel)",
      }}
    >
      <div
        data-testid="tool-call-card-header"
        aria-label={`工具调用 ${toolName}：${statusLabel}`}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          userSelect: "none",
        }}
      >
        <Icon name={iconName} size={12} color={accent} />
        <span
          data-testid="tool-call-card-name"
          style={{
            fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
            fontSize: "12px",
            color: "var(--omni-fog)",
            letterSpacing: "0.02em",
            flex: "1 1 auto",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {toolName}
        </span>
        <span
          data-testid="tool-call-card-status"
          style={{
            fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
            fontSize: "10px",
            letterSpacing: "0.1em",
            color: accent,
            textTransform: "uppercase",
          }}
        >
          {statusLabel}
        </span>
      </div>
      <div
        data-testid="tool-call-card-params"
        style={{
          fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
          fontSize: "11px",
          color: "var(--omni-dim)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          lineHeight: 1.4,
          marginTop: "6px",
          paddingTop: "6px",
          borderTop: "1px solid var(--omni-hairline)",
        }}
      >
        {JSON.stringify(params, null, 2)}
      </div>
      {hasResult && (
        <div
          data-testid="tool-call-card-result"
          style={{
            fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
            fontSize: "11px",
            color: status === "error" ? "var(--omni-particle-5)" : "var(--omni-fog)",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            lineHeight: 1.4,
            marginTop: "6px",
            padding: "4px 6px",
            borderLeft: `2px solid ${accent}`,
          }}
        >
          {result}
        </div>
      )}
    </div>
  );
}

/** 状态 → 强调色 token：pending=accent / success=fog / error=particle-5（警示）。 */
function statusColor(status: ToolCallStatus): string {
  switch (status) {
    case "pending":
      return "var(--omni-accent)";
    case "success":
      return "var(--omni-fog)";
    case "error":
      return "var(--omni-particle-5)";
  }
}

/** 状态 → 边框色：pending=accent 半透 / success=hairline / error=particle-5 半透。 */
function statusBorder(status: ToolCallStatus): string {
  switch (status) {
    case "pending":
      return "color-mix(in srgb, var(--omni-accent) 40%, transparent)";
    case "success":
      return "var(--omni-hairline)";
    case "error":
      return "color-mix(in srgb, var(--omni-particle-5) 50%, transparent)";
  }
}
