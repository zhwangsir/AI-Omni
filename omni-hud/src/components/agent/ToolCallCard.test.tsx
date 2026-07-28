/**
 * ToolCallCard 组件测试（M13.4 TDD）：工具调用卡片。
 *
 * 渲染单次 ToolCallRecord，Film Atelier 暗房风：
 * - 卡片头部：工具名 + 状态指示器（pending=加载中 / success=成功 / error=失败）；
 * - 卡片正文：参数 JSON（折叠/展开）+ 结果文本（success/error 时显示）；
 * - status=pending 时显示加载提示，不渲染结果区；
 * - 状态指示器经 Icon.tsx（activity/check 等 lucide 图标），禁止 emoji；
 * - 纯展示组件，不订阅 store、不发起 IPC。
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ToolCallRecord } from "./types";

import { ToolCallCard } from "./ToolCallCard";

function makeCall(overrides: Partial<ToolCallRecord> = {}): ToolCallRecord {
  return {
    id: overrides.id ?? "t1",
    toolName: overrides.toolName ?? "home_control_light",
    params: overrides.params ?? { room: "客厅", action: "on" },
    result: overrides.result ?? null,
    status: overrides.status ?? "pending",
    timestamp: overrides.timestamp ?? 1_700_000_000,
    ...overrides,
  } as ToolCallRecord;
}

describe("ToolCallCard 渲染契约", () => {
  it("挂载即渲染 data-testid=tool-call-card 容器", () => {
    render(<ToolCallCard call={makeCall()} />);
    expect(screen.getByTestId("tool-call-card")).toBeInTheDocument();
  });

  it("卡片暴露 data-status 属性（pending/success/error）", () => {
    render(<ToolCallCard call={makeCall({ status: "pending" })} />);
    expect(screen.getByTestId("tool-call-card")).toHaveAttribute("data-status", "pending");
  });

  it("布局中不出现 emoji（Film Atelier 风格红线）", () => {
    const { container } = render(<ToolCallCard call={makeCall()} />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u);
  });
});

describe("ToolCallCard 工具名渲染", () => {
  it("渲染工具名（header 区）", () => {
    render(<ToolCallCard call={makeCall({ toolName: "home_control_light" })} />);
    expect(screen.getByTestId("tool-call-card-name").textContent).toBe("home_control_light");
  });

  it("不同工具名都能正确渲染", () => {
    render(<ToolCallCard call={makeCall({ toolName: "weather_query" })} />);
    expect(screen.getByTestId("tool-call-card-name").textContent).toBe("weather_query");
  });
});

describe("ToolCallCard 状态指示器", () => {
  it("status=pending 显示「调用中」状态文字", () => {
    render(<ToolCallCard call={makeCall({ status: "pending" })} />);
    expect(screen.getByTestId("tool-call-card-status").textContent).toBe("调用中");
  });

  it("status=success 显示「已完成」状态文字", () => {
    render(<ToolCallCard call={makeCall({ status: "success", result: '{"ok":true}' })} />);
    expect(screen.getByTestId("tool-call-card-status").textContent).toBe("已完成");
  });

  it("status=error 显示「失败」状态文字", () => {
    render(<ToolCallCard call={makeCall({ status: "error", result: "错误：HA 不可达" })} />);
    expect(screen.getByTestId("tool-call-card-status").textContent).toBe("失败");
  });

  it("status=pending 时 data-status=pending（CSS 可挂载旋转动画）", () => {
    render(<ToolCallCard call={makeCall({ status: "pending" })} />);
    expect(screen.getByTestId("tool-call-card")).toHaveAttribute("data-status", "pending");
  });

  it("status=success 时 data-status=success", () => {
    render(<ToolCallCard call={makeCall({ status: "success", result: "ok" })} />);
    expect(screen.getByTestId("tool-call-card")).toHaveAttribute("data-status", "success");
  });

  it("status=error 时 data-status=error", () => {
    render(<ToolCallCard call={makeCall({ status: "error", result: "err" })} />);
    expect(screen.getByTestId("tool-call-card")).toHaveAttribute("data-status", "error");
  });
});

describe("ToolCallCard 参数展示", () => {
  it("渲染参数区（data-testid=tool-call-card-params）", () => {
    render(<ToolCallCard call={makeCall({ params: { room: "客厅" } })} />);
    expect(screen.getByTestId("tool-call-card-params")).toBeInTheDocument();
  });

  it("参数以 JSON 字符串形式渲染（便于调试与可读）", () => {
    render(<ToolCallCard call={makeCall({ params: { room: "客厅", action: "on" } })} />);
    const paramsText = screen.getByTestId("tool-call-card-params").textContent ?? "";
    expect(paramsText).toContain('"room"');
    expect(paramsText).toContain("客厅");
    expect(paramsText).toContain('"action"');
    expect(paramsText).toContain("on");
  });

  it("空参数对象也能渲染（不抛错）", () => {
    render(<ToolCallCard call={makeCall({ params: {} })} />);
    expect(screen.getByTestId("tool-call-card-params")).toBeInTheDocument();
  });
});

describe("ToolCallCard 结果展示", () => {
  it("status=pending 时不渲染结果区（尚未返回）", () => {
    render(<ToolCallCard call={makeCall({ status: "pending", result: null })} />);
    expect(screen.queryByTestId("tool-call-card-result")).toBeNull();
  });

  it("status=success 渲染结果文本", () => {
    render(
      <ToolCallCard
        call={makeCall({ status: "success", result: '{"ok":true,"data":"灯已打开"}' })}
      />,
    );
    const resultEl = screen.getByTestId("tool-call-card-result");
    expect(resultEl.textContent).toContain('{"ok":true,"data":"灯已打开"}');
  });

  it("status=error 渲染错误结果文本", () => {
    render(<ToolCallCard call={makeCall({ status: "error", result: "错误：HA 不可达" })} />);
    expect(screen.getByTestId("tool-call-card-result").textContent).toContain("错误：HA 不可达");
  });

  it("长结果文本不截断 DOM（white-space: pre-wrap 保留格式）", () => {
    const longResult = '{"data":"' + "x".repeat(200) + '"}';
    render(<ToolCallCard call={makeCall({ status: "success", result: longResult })} />);
    const resultEl = screen.getByTestId("tool-call-card-result");
    expect(resultEl.style.whiteSpace).toBe("pre-wrap");
    expect(resultEl.textContent).toBe(longResult);
  });
});

describe("ToolCallCard header 语义", () => {
  it("header 暴露 role=header + aria-label（含工具名与状态）", () => {
    render(<ToolCallCard call={makeCall({ toolName: "home_control_light", status: "pending" })} />);
    const header = screen.getByTestId("tool-call-card-header");
    expect(header.getAttribute("aria-label")).toContain("home_control_light");
    expect(header.getAttribute("aria-label")).toContain("调用中");
  });
});

describe("ToolCallCard 无障碍", () => {
  it("卡片容器暴露 aria-label 含工具名与状态", () => {
    render(<ToolCallCard call={makeCall({ toolName: "home_control_light", status: "success" })} />);
    const card = screen.getByTestId("tool-call-card");
    expect(card.getAttribute("aria-label")).toContain("home_control_light");
    expect(card.getAttribute("aria-label")).toContain("已完成");
  });
});
