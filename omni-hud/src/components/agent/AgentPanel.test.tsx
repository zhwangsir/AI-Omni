/**
 * AgentPanel 组件测试（M13.5 TDD）：Agent 主面板。
 *
 * 主面板：标题栏「雪莉」+ 状态指示器小圆点 + 消息列表 + 空状态。
 * - 订阅 statusStore.voice.state → 状态指示器颜色（idle 灰 / wake_listening 蓝 /
 *   recording 红 / thinking 紫 / speaking 绿 / tool_using 橙）；
 * - 订阅 agentStore.messages → 渲染 MessageBubble 列表；
 * - 空状态（messages 为空）：居中显示「雪莉待命中」+ Lucide Radio 图标；
 * - 新消息自动滚动到底部（useEffect + scrollIntoView）；
 * - mini 模式不渲染（windowMode === "mini" → 返回 null）；
 * - Film Atelier 暗房风：rgba 半透明 + backdrop-filter blur(8px)；
 * - 无 emoji（CLAUDE.md §五 / Film Atelier 风格红线）。
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  EMPTY_HOME_SUMMARY,
  EMPTY_SYSTEM_STATS,
  EMPTY_VOICE_STATUS,
  type VoicePipelineState,
  type VoiceStatus,
  type WindowMode,
} from "../../data/sources";
import type { AgentStore, AgentState } from "../../store/agentStore";
import type { StatusState, StatusStore } from "../../store/statusStore";
import type { Message } from "./types";

import { AgentPanel } from "./AgentPanel";

/** 状态 → 期望的指示器颜色（与 AgentPanel.tsx STATE_INDICATOR_COLOR 对齐）。
 * 浏览器把 hex 规范化为 rgb()，断言用 rgb 形式以匹配 style.backgroundColor 读取值。 */
const EXPECTED_COLORS: Record<VoicePipelineState, string> = {
  idle: "rgb(131, 135, 143)",
  wake_listening: "rgb(91, 141, 239)",
  follow_up_listening: "rgb(91, 141, 239)",
  recording: "rgb(176, 74, 58)",
  transcribing: "rgb(139, 147, 167)",
  thinking: "rgb(155, 107, 214)",
  tool_using: "rgb(217, 154, 78)",
  speaking: "rgb(111, 181, 138)",
};

function makeVoice(overrides: Partial<VoiceStatus> = {}): VoiceStatus {
  return { ...EMPTY_VOICE_STATUS, available: true, ...overrides };
}

function makeMessage(overrides: Partial<Message> & { role?: Message["role"]; text?: string } = {}): Message {
  return {
    id: overrides.id ?? "m1",
    role: overrides.role ?? "assistant",
    text: overrides.text ?? "好的",
    timestamp: overrides.timestamp ?? 1_700_000_000,
    ...overrides,
  } as Message;
}

interface FakeStatusOpts {
  state?: VoicePipelineState | null;
  windowMode?: WindowMode | null;
}

function makeFakeStatusStore(opts: FakeStatusOpts = {}): {
  store: StatusStore;
  setVoice(patch: Partial<VoiceStatus>): void;
} {
  let voice: VoiceStatus = makeVoice({
    state: opts.state ?? "idle",
    windowMode: opts.windowMode ?? "full",
  });
  let state: StatusState = {
    voice,
    home: EMPTY_HOME_SUMMARY,
    system: EMPTY_SYSTEM_STATS,
    failures: { voice: 0, home: 0, system: 0 },
    running: true,
    paused: false,
  };
  const listeners = new Set<() => void>();
  const store = {
    getState: () => state,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    start: () => {},
    stop: () => {},
    pause: () => {},
    resume: () => {},
  } as unknown as StatusStore;
  return {
    store,
    setVoice(patch) {
      voice = { ...voice, ...patch };
      state = { ...state, voice };
      act(() => {
        for (const listener of [...listeners]) listener();
      });
    },
  };
}

function makeFakeAgentStore(initialMessages: readonly Message[] = []): {
  store: AgentStore;
  setState(next: AgentState): void;
} {
  let state: AgentState = {
    messages: [...initialMessages],
    currentToolCalls: [],
  };
  const listeners = new Set<() => void>();
  const store = {
    getState: () => state,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    addUserMessage: vi.fn((text: string) => {
      state = { ...state, messages: [...state.messages, makeMessage({ role: "user", text })] };
      for (const listener of listeners) listener();
    }),
    addAssistantMessage: vi.fn((text: string) => {
      state = { ...state, messages: [...state.messages, makeMessage({ role: "assistant", text })] };
      for (const listener of listeners) listener();
    }),
    addToolCall: vi.fn(),
    updateToolCall: vi.fn(),
    clearSession: vi.fn(() => {
      state = { messages: [], currentToolCalls: [] };
      for (const listener of listeners) listener();
    }),
  } as unknown as AgentStore;
  return {
    store,
    setState(next) {
      state = next;
      act(() => {
        for (const listener of [...listeners]) listener();
      });
    },
  };
}

// jsdom 未实现 scrollIntoView，补一个 spy 便于断言自动滚动行为。
const scrollIntoViewSpy = vi.fn();
beforeEach(() => {
  scrollIntoViewSpy.mockClear();
  if (typeof Element !== "undefined") {
    Element.prototype.scrollIntoView = scrollIntoViewSpy as unknown as Element["scrollIntoView"];
  }
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AgentPanel 渲染契约", () => {
  it("挂载即渲染 data-testid=agent-panel 容器", () => {
    const status = makeFakeStatusStore();
    const agent = makeFakeAgentStore();
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    expect(screen.getByTestId("agent-panel")).toBeInTheDocument();
  });

  it("布局中不出现 emoji（Film Atelier 风格红线）", () => {
    const status = makeFakeStatusStore();
    const agent = makeFakeAgentStore();
    const { container } = render(
      <AgentPanel statusStore={status.store} agentStore={agent.store} />,
    );
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u);
  });
});

describe("AgentPanel 标题栏", () => {
  it("标题栏显示「雪莉」名称", () => {
    const status = makeFakeStatusStore();
    const agent = makeFakeAgentStore();
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    expect(screen.getByTestId("agent-panel-title").textContent).toBe("雪莉");
  });

  it("标题栏渲染状态指示器小圆点（data-testid=agent-panel-indicator）", () => {
    const status = makeFakeStatusStore();
    const agent = makeFakeAgentStore();
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    expect(screen.getByTestId("agent-panel-indicator")).toBeInTheDocument();
  });
});

describe("AgentPanel 状态指示器颜色", () => {
  it("idle 状态指示器为灰色", () => {
    const status = makeFakeStatusStore({ state: "idle" });
    const agent = makeFakeAgentStore();
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    const indicator = screen.getByTestId("agent-panel-indicator");
    expect(indicator.style.backgroundColor).toBe(EXPECTED_COLORS.idle);
  });

  it("wake_listening 状态指示器为蓝色", () => {
    const status = makeFakeStatusStore({ state: "wake_listening" });
    const agent = makeFakeAgentStore();
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    expect(screen.getByTestId("agent-panel-indicator").style.backgroundColor).toBe(
      EXPECTED_COLORS.wake_listening,
    );
  });

  it("recording 状态指示器为红色", () => {
    const status = makeFakeStatusStore({ state: "recording" });
    const agent = makeFakeAgentStore();
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    expect(screen.getByTestId("agent-panel-indicator").style.backgroundColor).toBe(
      EXPECTED_COLORS.recording,
    );
  });

  it("thinking 状态指示器为紫色", () => {
    const status = makeFakeStatusStore({ state: "thinking" });
    const agent = makeFakeAgentStore();
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    expect(screen.getByTestId("agent-panel-indicator").style.backgroundColor).toBe(
      EXPECTED_COLORS.thinking,
    );
  });

  it("speaking 状态指示器为绿色", () => {
    const status = makeFakeStatusStore({ state: "speaking" });
    const agent = makeFakeAgentStore();
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    expect(screen.getByTestId("agent-panel-indicator").style.backgroundColor).toBe(
      EXPECTED_COLORS.speaking,
    );
  });

  it("tool_using 状态指示器为橙色", () => {
    const status = makeFakeStatusStore({ state: "tool_using" });
    const agent = makeFakeAgentStore();
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    expect(screen.getByTestId("agent-panel-indicator").style.backgroundColor).toBe(
      EXPECTED_COLORS.tool_using,
    );
  });

  it("voice.state 变化时指示器颜色跟随更新", () => {
    const status = makeFakeStatusStore({ state: "idle" });
    const agent = makeFakeAgentStore();
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    expect(screen.getByTestId("agent-panel-indicator").style.backgroundColor).toBe(
      EXPECTED_COLORS.idle,
    );
    status.setVoice({ state: "speaking" });
    expect(screen.getByTestId("agent-panel-indicator").style.backgroundColor).toBe(
      EXPECTED_COLORS.speaking,
    );
  });
});

describe("AgentPanel 消息列表", () => {
  it("渲染消息列表（messages 非空时显示 MessageBubble）", () => {
    const status = makeFakeStatusStore();
    const agent = makeFakeAgentStore([
      makeMessage({ id: "m1", role: "user", text: "打开客厅的灯" }),
      makeMessage({ id: "m2", role: "assistant", text: "已为你打开客厅灯" }),
    ]);
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    const bubbles = screen.getAllByTestId("message-bubble");
    expect(bubbles.length).toBe(2);
  });

  it("消息列表容器暴露 data-testid=agent-panel-messages（可滚动）", () => {
    const status = makeFakeStatusStore();
    const agent = makeFakeAgentStore([makeMessage()]);
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    const list = screen.getByTestId("agent-panel-messages");
    expect(list).toBeInTheDocument();
    // overflow-y: auto 保证可滚动
    expect(list.style.overflowY).toBe("auto");
  });
});

describe("AgentPanel 空状态", () => {
  it("messages 为空时显示空状态提示文字「雪莉待命中」", () => {
    const status = makeFakeStatusStore();
    const agent = makeFakeAgentStore([]);
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    expect(screen.getByTestId("agent-panel-empty").textContent).toContain("雪莉待命中");
  });

  it("空状态渲染 Lucide Radio 图标（svg）", () => {
    const status = makeFakeStatusStore();
    const agent = makeFakeAgentStore([]);
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    const empty = screen.getByTestId("agent-panel-empty");
    const svg = empty.querySelector("svg");
    expect(svg).not.toBeNull();
  });

  it("messages 非空时不渲染空状态", () => {
    const status = makeFakeStatusStore();
    const agent = makeFakeAgentStore([makeMessage()]);
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    expect(screen.queryByTestId("agent-panel-empty")).toBeNull();
  });
});

describe("AgentPanel 自动滚动", () => {
  it("新消息追加时自动滚动到底部（调用 scrollIntoView）", () => {
    const status = makeFakeStatusStore();
    const agent = makeFakeAgentStore([makeMessage({ id: "m1" })]);
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    // 初始挂载已可能触发一次 scrollIntoView，清零后再追加消息验证新触发。
    scrollIntoViewSpy.mockClear();
    agent.setState({
      messages: [
        makeMessage({ id: "m1" }),
        makeMessage({ id: "m2", text: "新消息" }),
      ],
      currentToolCalls: [],
    });
    expect(scrollIntoViewSpy).toHaveBeenCalled();
  });
});

describe("AgentPanel mini 模式隐藏", () => {
  it("windowMode=mini 时 AgentPanel 不渲染（返回 null）", () => {
    const status = makeFakeStatusStore({ windowMode: "mini" });
    const agent = makeFakeAgentStore();
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    expect(screen.queryByTestId("agent-panel")).toBeNull();
  });

  it("windowMode=full 时正常渲染", () => {
    const status = makeFakeStatusStore({ windowMode: "full" });
    const agent = makeFakeAgentStore();
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    expect(screen.getByTestId("agent-panel")).toBeInTheDocument();
  });

  it("windowMode=null（缺省）正常渲染（安全态）", () => {
    const status = makeFakeStatusStore({ windowMode: null });
    const agent = makeFakeAgentStore();
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    expect(screen.getByTestId("agent-panel")).toBeInTheDocument();
  });

  it("windowMode 从 full 切到 mini 时 AgentPanel 卸载", () => {
    const status = makeFakeStatusStore({ windowMode: "full" });
    const agent = makeFakeAgentStore();
    render(<AgentPanel statusStore={status.store} agentStore={agent.store} />);
    expect(screen.getByTestId("agent-panel")).toBeInTheDocument();
    status.setVoice({ windowMode: "mini" });
    expect(screen.queryByTestId("agent-panel")).toBeNull();
  });
});
