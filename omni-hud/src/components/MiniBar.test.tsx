/**
 * MiniBar 组件测试（M12 灵动岛双形态 TDD）。
 *
 * Mini 浮窗（240×48 顶部居中）的状态文字层——idle 待命态时 Full cover-display
 * 退化为顶部浮窗，仅显示精简状态文字（如「雪莉 · 待命」），让出桌面视野。
 *
 * 契约：
 * - 订阅 statusStore.voice → 根据 state 渲染对应中文状态文字；
 * - pointer-events: none（Rust 分区轮询 Mini 形态下全穿透，浮窗不拦截桌面点击）；
 * - aria-hidden=true（MiniBar 是观察性状态显示，不承担交互语义）；
 * - 无 emoji（图标全部经 Icon.tsx / lucide 渲染为 svg）。
 *
 * 全部 fake statusStore，不碰真实 IPC / WebGL / 定时器。
 */
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EMPTY_HOME_SUMMARY, EMPTY_SYSTEM_STATS, EMPTY_VOICE_STATUS } from "../data/sources";
import type { StatusState, StatusStore } from "../store/statusStore";
import type { VoicePipelineState } from "../data/sources";

import { MiniBar } from "./MiniBar";

/** 可控 fake StatusStore：仅实现 MiniBar 消费的契约面。 */
function makeFakeStatusStore(initialState: VoicePipelineState | null): {
  store: StatusStore;
  setVoice(state: VoicePipelineState | null): void;
} {
  let state: StatusState = {
    voice: { ...EMPTY_VOICE_STATUS, available: true, state: initialState },
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
  } as unknown as StatusStore;
  return {
    store,
    setVoice(next): void {
      state = { ...state, voice: { ...state.voice, state: next } };
      act(() => {
        for (const listener of [...listeners]) listener();
      });
    },
  };
}

describe("MiniBar 渲染契约", () => {
  it("挂载即渲染 data-testid=mini-bar 容器", () => {
    const { store } = makeFakeStatusStore("idle");
    render(<MiniBar statusStore={store} />);
    expect(screen.getByTestId("mini-bar")).toBeInTheDocument();
  });

  it("容器 pointer-events:none（Rust 分区轮询 Mini 形态下全穿透，浮窗不拦截）", () => {
    const { store } = makeFakeStatusStore("idle");
    render(<MiniBar statusStore={store} />);
    expect(screen.getByTestId("mini-bar").style.pointerEvents).toBe("none");
  });

  it("容器 aria-hidden=true（观察性状态显示，不承担交互语义）", () => {
    const { store } = makeFakeStatusStore("idle");
    render(<MiniBar statusStore={store} />);
    expect(screen.getByTestId("mini-bar")).toHaveAttribute("aria-hidden", "true");
  });

  it("布局中不出现 emoji（图标全部经 Icon.tsx / lucide 渲染为 svg）", () => {
    const { store } = makeFakeStatusStore("idle");
    const { container } = render(<MiniBar statusStore={store} />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u);
  });
});

describe("MiniBar 状态文字", () => {
  it("idle 状态显示「雪莉 · 待命」", () => {
    const { store } = makeFakeStatusStore("idle");
    render(<MiniBar statusStore={store} />);
    expect(screen.getByTestId("mini-bar-status-text").textContent).toBe("雪莉 · 待命");
  });

  it("wake_listening 状态显示「唤醒中…」", () => {
    const { store } = makeFakeStatusStore("wake_listening");
    render(<MiniBar statusStore={store} />);
    expect(screen.getByTestId("mini-bar-status-text").textContent).toBe("唤醒中…");
  });

  it("recording 状态显示「聆听中…」", () => {
    const { store } = makeFakeStatusStore("recording");
    render(<MiniBar statusStore={store} />);
    expect(screen.getByTestId("mini-bar-status-text").textContent).toBe("聆听中…");
  });

  it("thinking 状态显示「思考中…」", () => {
    const { store } = makeFakeStatusStore("thinking");
    render(<MiniBar statusStore={store} />);
    expect(screen.getByTestId("mini-bar-status-text").textContent).toBe("思考中…");
  });

  it("speaking 状态显示「应答中…」", () => {
    const { store } = makeFakeStatusStore("speaking");
    render(<MiniBar statusStore={store} />);
    expect(screen.getByTestId("mini-bar-status-text").textContent).toBe("应答中…");
  });

  it("tool_using 状态显示「调用工具…」", () => {
    const { store } = makeFakeStatusStore("tool_using");
    render(<MiniBar statusStore={store} />);
    expect(screen.getByTestId("mini-bar-status-text").textContent).toBe("调用工具…");
  });

  it("null 状态（管道未启动 / 不可用）显示「雪莉 · 待命」", () => {
    const { store } = makeFakeStatusStore(null);
    render(<MiniBar statusStore={store} />);
    expect(screen.getByTestId("mini-bar-status-text").textContent).toBe("雪莉 · 待命");
  });

  it("状态变化时文字同步更新", () => {
    const { store, setVoice } = makeFakeStatusStore("idle");
    render(<MiniBar statusStore={store} />);
    expect(screen.getByTestId("mini-bar-status-text").textContent).toBe("雪莉 · 待命");
    setVoice("thinking");
    expect(screen.getByTestId("mini-bar-status-text").textContent).toBe("思考中…");
    setVoice("speaking");
    expect(screen.getByTestId("mini-bar-status-text").textContent).toBe("应答中…");
  });
});

describe("MiniBar 卸载清理", () => {
  it("卸载时不抛错（订阅正确退订）", () => {
    const { store } = makeFakeStatusStore("idle");
    const { unmount } = render(<MiniBar statusStore={store} />);
    expect(() => unmount()).not.toThrow();
  });
});
