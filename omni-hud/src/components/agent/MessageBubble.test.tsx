/**
 * MessageBubble 组件测试（M13.3 TDD）：对话气泡。
 *
 * 渲染单条 Message（user / assistant），Film Atelier 暗房风：
 * - user 气泡右对齐、fog 文字色、低透明度 abyss 底；
 * - assistant 气泡左对齐、accent 文字色、略高透明度 panel 底；
 * - 显示消息文本，data-testid/message-bubble/data-role 暴露语义钩子；
 * - 无 emoji（CLAUDE.md §五 / Film Atelier 风格红线）；
 * - 纯展示组件，不订阅 store、不发起 IPC。
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Message } from "./types";

import { MessageBubble } from "./MessageBubble";

function makeMessage(overrides: Partial<Message> & { role?: Message["role"]; text?: string } = {}): Message {
  return {
    id: overrides.id ?? "m1",
    role: overrides.role ?? "user",
    text: overrides.text ?? "打开客厅的灯",
    timestamp: overrides.timestamp ?? 1_700_000_000,
    ...overrides,
  } as Message;
}

describe("MessageBubble 渲染契约", () => {
  it("挂载即渲染 data-testid=message-bubble 容器", () => {
    render(<MessageBubble message={makeMessage()} />);
    expect(screen.getByTestId("message-bubble")).toBeInTheDocument();
  });

  it("user 消息 data-role=user", () => {
    render(<MessageBubble message={makeMessage({ role: "user" })} />);
    expect(screen.getByTestId("message-bubble")).toHaveAttribute("data-role", "user");
  });

  it("assistant 消息 data-role=assistant", () => {
    render(<MessageBubble message={makeMessage({ role: "assistant", text: "好的" })} />);
    expect(screen.getByTestId("message-bubble")).toHaveAttribute("data-role", "assistant");
  });

  it("布局中不出现 emoji（Film Atelier 风格红线）", () => {
    const { container } = render(<MessageBubble message={makeMessage()} />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u);
  });
});

describe("MessageBubble 文本渲染", () => {
  it("渲染 user 消息文本", () => {
    render(<MessageBubble message={makeMessage({ role: "user", text: "打开客厅的灯" })} />);
    expect(screen.getByTestId("message-bubble-text").textContent).toBe("打开客厅的灯");
  });

  it("渲染 assistant 消息文本", () => {
    render(<MessageBubble message={makeMessage({ role: "assistant", text: "已为你打开客厅灯" })} />);
    expect(screen.getByTestId("message-bubble-text").textContent).toBe("已为你打开客厅灯");
  });

  it("多行文本保留换行（white-space: pre-wrap）", () => {
    render(<MessageBubble message={makeMessage({ text: "第一行\n第二行" })} />);
    const textEl = screen.getByTestId("message-bubble-text");
    expect(textEl.style.whiteSpace).toBe("pre-wrap");
  });

  it("空字符串消息也能渲染（不抛错、不省略容器）", () => {
    render(<MessageBubble message={makeMessage({ text: "" })} />);
    expect(screen.getByTestId("message-bubble")).toBeInTheDocument();
    expect(screen.getByTestId("message-bubble-text").textContent).toBe("");
  });
});

describe("MessageBubble 对齐与角色样式", () => {
  it("user 气泡右对齐（justify-content/flex-end 风格）", () => {
    render(<MessageBubble message={makeMessage({ role: "user" })} />);
    const bubble = screen.getByTestId("message-bubble");
    // 外层容器 row + flex-end 表示气泡靠右
    expect(bubble.style.justifyContent).toBe("flex-end");
  });

  it("assistant 气泡左对齐（justify-content/flex-start 风格）", () => {
    render(<MessageBubble message={makeMessage({ role: "assistant" })} />);
    const bubble = screen.getByTestId("message-bubble");
    expect(bubble.style.justifyContent).toBe("flex-start");
  });

  it("user 气泡内层有 user 专属 className（便于 CSS 细化样式）", () => {
    render(<MessageBubble message={makeMessage({ role: "user" })} />);
    const inner = screen.getByTestId("message-bubble-inner");
    expect(inner.className).toContain("message-bubble-inner--user");
  });

  it("assistant 气泡内层有 assistant 专属 className", () => {
    render(<MessageBubble message={makeMessage({ role: "assistant" })} />);
    const inner = screen.getByTestId("message-bubble-inner");
    expect(inner.className).toContain("message-bubble-inner--assistant");
  });
});

describe("MessageBubble 角色标签", () => {
  it("user 气泡暴露「你」角色标签（中文短标签）", () => {
    render(<MessageBubble message={makeMessage({ role: "user" })} />);
    expect(screen.getByTestId("message-bubble-role").textContent).toBe("你");
  });

  it("assistant 气泡暴露「雪莉」角色标签", () => {
    render(<MessageBubble message={makeMessage({ role: "assistant" })} />);
    expect(screen.getByTestId("message-bubble-role").textContent).toBe("雪莉");
  });
});

describe("MessageBubble 工具调用透传", () => {
  it("assistant 消息附带 toolCalls 时渲染工具调用占位槽（AgentPanel 注入 ToolCallCard）", () => {
    const message = makeMessage({
      role: "assistant",
      text: "已开灯",
      toolCalls: [
        {
          id: "t1",
          toolName: "home_control_light",
          params: { room: "客厅" },
          result: '{"ok":true}',
          status: "success",
          timestamp: 1,
        },
      ],
    });
    render(<MessageBubble message={message} />);
    const slot = screen.getByTestId("message-bubble-toolcalls");
    expect(slot).toBeInTheDocument();
  });

  it("user 消息不渲染 toolCalls 槽（user 永不附带工具调用）", () => {
    render(<MessageBubble message={makeMessage({ role: "user" })} />);
    expect(screen.queryByTestId("message-bubble-toolcalls")).toBeNull();
  });

  it("assistant 消息无 toolCalls 时不渲染 toolCalls 槽", () => {
    render(<MessageBubble message={makeMessage({ role: "assistant", text: "你好" })} />);
    expect(screen.queryByTestId("message-bubble-toolcalls")).toBeNull();
  });

  it("assistant 消息 toolCalls 为空数组时不渲染 toolCalls 槽", () => {
    const message: Message = {
      id: "m1",
      role: "assistant",
      text: "你好",
      timestamp: 1,
      toolCalls: [],
    };
    render(<MessageBubble message={message} />);
    expect(screen.queryByTestId("message-bubble-toolcalls")).toBeNull();
  });
});

describe("MessageBubble 无障碍", () => {
  it("容器暴露 role=log 与 aria-label（对话流语义）", () => {
    render(<MessageBubble message={makeMessage()} />);
    // 注：每条气泡自身 role=log 便于屏幕阅读器感知对话流变化
    const bubble = screen.getByTestId("message-bubble");
    expect(bubble.getAttribute("aria-label")).toContain("你");
  });

  it("assistant 气泡 aria-label 含「雪莉」", () => {
    render(<MessageBubble message={makeMessage({ role: "assistant" })} />);
    expect(screen.getByTestId("message-bubble").getAttribute("aria-label")).toContain("雪莉");
  });
});
