/**
 * App + AgentPanel + agentRuntime 集成测试（M13.6 TDD）。
 *
 * 验证端到端链路：statusStore.voice 进入 speaking + 新 replySeq →
 * bindAgentSync 把回复同步到 agentStore.messages → AgentPanel 渲染 MessageBubble。
 *
 * 与 AppWindowMode 测试的区别：后者只验证窗口形态切换的渲染挂载/卸载，
 * 本文件验证 speaking 事件 → agentStore → AgentPanel 消息流的完整同步语义。
 *
 * 模拟方式：替换 statusRuntime / subtitleRuntime / zoneRegistryRuntime / agentRuntime
 * 单例（部分用真实 agentStore 验证同步，部分用静止桩避免异步污染）。
 */
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  EMPTY_HOME_SUMMARY,
  EMPTY_SYSTEM_STATS,
  EMPTY_VOICE_STATUS,
  type VoiceStatus,
  type WindowMode,
} from "../data/sources";
import type { StatusState, StatusStore } from "../store/statusStore";

// ResizeObserver polyfill（useRegisteredZone 依赖）。
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
(globalThis as unknown as { ResizeObserver: typeof ResizeObserverStub }).ResizeObserver =
  ResizeObserverStub;

const subtitleState = { visible: false, text: "", isFinal: false };
const zonesList: readonly never[] = [];

interface FakeStatusHandle {
  store: StatusStore;
  setVoice(patch: Partial<VoiceStatus>): void;
}

function makeFakeStatusStore(initialMode: WindowMode = "full"): FakeStatusHandle {
  let voice: VoiceStatus = {
    ...EMPTY_VOICE_STATUS,
    available: true,
    state: "idle",
    windowMode: initialMode,
  };
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

let currentFake: FakeStatusHandle;

vi.mock("../store/statusRuntime", () => ({
  getStatusStore: () => currentFake.store,
}));

vi.mock("../store/subtitleRuntime", () => ({
  getSubtitleStore: () => ({
    getState: () => subtitleState,
    subscribe: () => () => {},
    begin: () => {},
    appendChunk: () => {},
    finish: () => {},
    hide: () => {},
  }),
}));

vi.mock("../store/zoneRegistryRuntime", () => ({
  getZoneRegistry: () => ({
    getZones: () => zonesList,
    subscribe: () => () => {},
    registerZone: () => {},
    unregisterZone: () => {},
  }),
}));

vi.mock("../space/createSpace", () => ({
  createSpace: vi.fn(() => ({
    dispose: () => {},
    applyTheme: () => {},
    setReducedMotion: () => {},
    setPointer: () => {},
    setQuality: () => {},
    resize: () => {},
    setField: () => {},
  })),
  PLACEHOLDER_POINT_COUNT: 50,
}));

vi.mock("../space/runtime", () => ({
  loadSpaceRuntime: () => ({ three: {}, postfx: undefined }),
}));

const invokeMock = vi.fn().mockResolvedValue(undefined);
vi.mock("@tauri-apps/api/core", () => ({
  invoke: (cmd: string, args?: unknown) => invokeMock(cmd, args),
}));

// 真实 agentStore + bindAgentSync（不 mock），验证同步语义。
// 注意：getAgentStore 是进程内单例，多个测试共享同一实例——
// beforeEach 调 clearSession() 清空残留消息，避免测试间污染。
import { App } from "../App";
import { getAgentStore } from "../store/agentRuntime";

beforeEach(() => {
  invokeMock.mockClear();
  getAgentStore().clearSession();
});

describe("App + AgentPanel + agentRuntime 集成（M13.6）", () => {
  it("App 挂载即渲染 AgentPanel（full 模式默认）", () => {
    currentFake = makeFakeStatusStore("full");
    render(<App />);
    expect(screen.getByTestId("agent-panel")).toBeInTheDocument();
    // 空状态显示「雪莉待命中」
    expect(screen.getByTestId("agent-panel-empty").textContent).toContain("雪莉待命中");
  });

  it("voice 进入 speaking + 新 replySeq → agentStore 同步 → AgentPanel 渲染 MessageBubble", () => {
    currentFake = makeFakeStatusStore("full");
    render(<App />);
    // 初始空状态
    expect(screen.queryByTestId("message-bubble")).toBeNull();

    // 模拟 omni_voice 进入 speaking 并写入回复（replySeq 翻篇）
    currentFake.setVoice({
      state: "speaking",
      reply: "好的，已为你打开客厅灯",
      replySeq: 1,
    });

    // AgentPanel 应渲染一条 assistant 消息
    const bubbles = screen.getAllByTestId("message-bubble");
    expect(bubbles.length).toBe(1);
    expect(screen.getByTestId("message-bubble-text").textContent).toBe("好的，已为你打开客厅灯");
  });

  it("同一 replySeq 的 speaking 帧不重复同步（去重）", () => {
    currentFake = makeFakeStatusStore("full");
    render(<App />);
    currentFake.setVoice({
      state: "speaking",
      reply: "你好",
      replySeq: 1,
    });
    expect(screen.getAllByTestId("message-bubble").length).toBe(1);

    // 同 seq 再触发一次（模拟状态文件多次写入但 seq 未翻篇）
    currentFake.setVoice({
      state: "speaking",
      reply: "你好",
      replySeq: 1,
    });
    expect(screen.getAllByTestId("message-bubble").length).toBe(1);
  });

  it("多轮 speaking（replySeq 递增）追加多条 assistant 消息", () => {
    currentFake = makeFakeStatusStore("full");
    render(<App />);

    currentFake.setVoice({ state: "speaking", reply: "第一轮回复", replySeq: 1 });
    currentFake.setVoice({ state: "idle", replySeq: 1 });
    currentFake.setVoice({ state: "speaking", reply: "第二轮回复", replySeq: 2 });

    const bubbles = screen.getAllByTestId("message-bubble");
    expect(bubbles.length).toBe(2);
    const texts = bubbles.map((b) => b.querySelector('[data-testid="message-bubble-text"]')?.textContent);
    expect(texts).toContain("第一轮回复");
    expect(texts).toContain("第二轮回复");
  });

  it("speaking 时携带 toolCalls → assistant 消息附带工具调用槽", () => {
    currentFake = makeFakeStatusStore("full");
    render(<App />);
    currentFake.setVoice({
      state: "speaking",
      reply: "已开灯",
      replySeq: 1,
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
    expect(screen.getByTestId("message-bubble-toolcalls")).toBeInTheDocument();
  });

  it("windowMode 从 full 切到 mini → AgentPanel 卸载（不渲染 agent-panel）", () => {
    currentFake = makeFakeStatusStore("full");
    render(<App />);
    expect(screen.getByTestId("agent-panel")).toBeInTheDocument();

    currentFake.setVoice({ windowMode: "mini" });
    expect(screen.queryByTestId("agent-panel")).toBeNull();
    // mini 模式渲染 MiniBar
    expect(screen.getByTestId("mini-bar")).toBeInTheDocument();
  });

  it("windowMode 从 mini 切回 full → AgentPanel 重新挂载并保留历史消息", () => {
    currentFake = makeFakeStatusStore("full");
    render(<App />);
    currentFake.setVoice({ state: "speaking", reply: "历史回复", replySeq: 1 });
    expect(screen.getAllByTestId("message-bubble").length).toBe(1);

    // 切到 mini（AgentPanel 卸载，agentStore 保留 messages）
    currentFake.setVoice({ windowMode: "mini" });
    expect(screen.queryByTestId("agent-panel")).toBeNull();

    // 切回 full（AgentPanel 重新挂载，历史消息仍可见）
    currentFake.setVoice({ windowMode: "full" });
    expect(screen.getByTestId("agent-panel")).toBeInTheDocument();
    expect(screen.getAllByTestId("message-bubble").length).toBe(1);
    expect(screen.getByTestId("message-bubble-text").textContent).toBe("历史回复");
  });
});
