/**
 * CaptionLayer 组件测试（M7.4 TDD）：mono 状态标 + 显影字幕 + 打断 glyph。
 *
 * 覆盖：
 * - 容器渲染；
 * - 状态标：voice.state 变化时显影，2.5s 后渐隐（fake timers）；
 * - 字幕联动：voice → speaking + reply → subtitleStore.begin + appendChunk；
 *   voice 离开 speaking → subtitleStore.finish（自然结束 linger）；
 * - 打断 glyph：speaking 时字幕区为 active zone，hover 右端显 square 图标，
 *   点击 → interruptSpeaking + subtitleStore.hide；
 * - 睡眠态：不注册分区、不显字幕；
 * - 卸载清理。
 *
 * 全 fake：stores / zoneRegistry / interruptSpeaking 均注入桩。
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/voice", () => ({
  interruptSpeaking: vi.fn(),
  CMD_VOICE_INTERRUPT: "voice_interrupt",
}));

vi.mock("../store/zoneRegistryRuntime", () => ({
  getZoneRegistry: () => ({
    getZones: () => [],
    subscribe: () => () => {},
    registerZone: vi.fn(),
    unregisterZone: vi.fn(),
  }),
}));

import { EMPTY_HOME_SUMMARY, EMPTY_SYSTEM_STATS, EMPTY_VOICE_STATUS, type VoiceStatus } from "../data/sources";
import { interruptSpeaking } from "../lib/voice";
import { createHudStore, type HudStore } from "../store/hudStore";
import type { SubtitleState, SubtitleStore } from "../store/subtitleStore";
import type { StatusState, StatusStore } from "../store/statusStore";
import type { ZoneRegistry } from "../store/zoneRegistry";

import { CaptionLayer } from "./CaptionLayer";

// ---- ResizeObserver polyfill ------------------------------------------------
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
(globalThis as unknown as { ResizeObserver: typeof ResizeObserverStub }).ResizeObserver =
  ResizeObserverStub;

// ---- fake stores ------------------------------------------------------------

function makeFakeStatusStore(initialVoice?: Partial<VoiceStatus>): {
  store: StatusStore;
  setVoice(patch: Partial<VoiceStatus>): void;
} {
  let state: StatusState = {
    voice: { ...EMPTY_VOICE_STATUS, available: true, state: null, ...initialVoice },
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
    setVoice(patch): void {
      state = { ...state, voice: { ...state.voice, ...patch } };
      act(() => {
        for (const listener of [...listeners]) listener();
      });
    },
  };
}

function makeFakeSubtitleStore(initial?: Partial<SubtitleState>): {
  store: SubtitleStore;
  setState(patch: Partial<SubtitleState>): void;
  begin: ReturnType<typeof vi.fn>;
  appendChunk: ReturnType<typeof vi.fn>;
  finish: ReturnType<typeof vi.fn>;
  hide: ReturnType<typeof vi.fn>;
} {
  const begin = vi.fn();
  const appendChunk = vi.fn();
  const finish = vi.fn();
  const hide = vi.fn();
  let state: SubtitleState = {
    text: "",
    isFinal: false,
    fadingOut: false,
    visible: false,
    ...initial,
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
    begin,
    appendChunk,
    finish,
    hide,
  } as unknown as SubtitleStore;
  return {
    store,
    setState(patch): void {
      state = { ...state, ...patch };
      act(() => {
        for (const listener of [...listeners]) listener();
      });
    },
    begin,
    appendChunk,
    finish,
    hide,
  };
}

function makeFakeZoneRegistry(): {
  registry: ZoneRegistry;
  registerZone: ReturnType<typeof vi.fn>;
  unregisterZone: ReturnType<typeof vi.fn>;
} {
  const registerZone = vi.fn();
  const unregisterZone = vi.fn();
  const registry = {
    getZones: () => [],
    subscribe: () => () => {},
    registerZone,
    unregisterZone,
  } as unknown as ZoneRegistry;
  return { registry, registerZone, unregisterZone };
}

let hudStore: HudStore;

beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(interruptSpeaking).mockReset();
  hudStore = createHudStore();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("CaptionLayer 容器", () => {
  it("渲染 data-testid=caption-layer 容器", () => {
    const { store: status } = makeFakeStatusStore();
    const { store: subtitle } = makeFakeSubtitleStore();
    render(
      <CaptionLayer
        statusStore={status}
        hudStore={hudStore}
        subtitleStore={subtitle}
      />,
    );
    expect(screen.getByTestId("caption-layer")).toBeInTheDocument();
  });
});

describe("CaptionLayer 状态标（mono 片头标）", () => {
  it("voice.state 变化时状态标显影", () => {
    const { store: status, setVoice } = makeFakeStatusStore({ state: "idle" });
    const { store: subtitle } = makeFakeSubtitleStore();
    render(
      <CaptionLayer
        statusStore={status}
        hudStore={hudStore}
        subtitleStore={subtitle}
      />,
    );
    setVoice({ state: "thinking" });
    const mark = screen.getByTestId("caption-status-mark");
    expect(mark).toHaveAttribute("data-visible", "true");
    expect(mark.textContent).toContain("thinking");
  });

  it("2.5s 后状态标渐隐", () => {
    const { store: status, setVoice } = makeFakeStatusStore({ state: "idle" });
    const { store: subtitle } = makeFakeSubtitleStore();
    render(
      <CaptionLayer
        statusStore={status}
        hudStore={hudStore}
        subtitleStore={subtitle}
      />,
    );
    setVoice({ state: "speaking" });
    expect(screen.getByTestId("caption-status-mark")).toHaveAttribute("data-visible", "true");
    act(() => {
      vi.advanceTimersByTime(2500);
    });
    expect(screen.getByTestId("caption-status-mark")).toHaveAttribute("data-visible", "false");
  });

  it("状态未变化不重复显影（去重）", () => {
    const { store: status, setVoice } = makeFakeStatusStore({ state: "idle" });
    const { store: subtitle } = makeFakeSubtitleStore();
    render(
      <CaptionLayer
        statusStore={status}
        hudStore={hudStore}
        subtitleStore={subtitle}
      />,
    );
    setVoice({ state: "speaking" });
    const mark = screen.getByTestId("caption-status-mark");
    expect(mark).toHaveAttribute("data-visible", "true");
    // 同值再推一次不应重新显影
    act(() => {
      vi.advanceTimersByTime(2500);
    });
    expect(mark).toHaveAttribute("data-visible", "false");
    setVoice({ state: "speaking" });
    expect(mark).toHaveAttribute("data-visible", "false");
  });
});

describe("CaptionLayer 字幕联动（voice → subtitleStore）", () => {
  it("voice → speaking + reply → begin + appendChunk（显影完整回复）", () => {
    const { store: status, setVoice } = makeFakeStatusStore({ state: "idle" });
    const { store: subtitle, begin, appendChunk } = makeFakeSubtitleStore();
    render(
      <CaptionLayer
        statusStore={status}
        hudStore={hudStore}
        subtitleStore={subtitle}
      />,
    );
    setVoice({ state: "speaking", reply: "你好世界", replySeq: 1 });
    expect(begin).toHaveBeenCalledTimes(1);
    expect(appendChunk).toHaveBeenCalledWith("你好世界");
  });

  it("voice 离开 speaking → finish（自然结束 linger）", () => {
    const { store: status, setVoice } = makeFakeStatusStore({
      state: "speaking",
      reply: "回复",
      replySeq: 1,
    });
    const { store: subtitle, finish } = makeFakeSubtitleStore();
    render(
      <CaptionLayer
        statusStore={status}
        hudStore={hudStore}
        subtitleStore={subtitle}
      />,
    );
    finish.mockClear();
    setVoice({ state: "idle" });
    expect(finish).toHaveBeenCalledTimes(1);
  });

  it("相同 replySeq 重复 speaking 不重复驱动字幕", () => {
    const { store: status, setVoice } = makeFakeStatusStore({
      state: "speaking",
      reply: "回复",
      replySeq: 1,
    });
    const { store: subtitle, begin } = makeFakeSubtitleStore();
    render(
      <CaptionLayer
        statusStore={status}
        hudStore={hudStore}
        subtitleStore={subtitle}
      />,
    );
    begin.mockClear();
    // 同 replySeq 再次推 speaking（粘性快照）
    setVoice({ state: "speaking", reply: "回复", replySeq: 1 });
    expect(begin).not.toHaveBeenCalled();
  });
});

describe("CaptionLayer 字幕渲染", () => {
  it("subtitleStore.visible=true 时渲染字幕文本", () => {
    const { store: status } = makeFakeStatusStore({ state: "idle" });
    const { store: subtitle, setState } = makeFakeSubtitleStore();
    render(
      <CaptionLayer
        statusStore={status}
        hudStore={hudStore}
        subtitleStore={subtitle}
      />,
    );
    expect(screen.queryByTestId("caption-subtitle")).toBeNull();
    setState({ visible: true, text: "显示中的字幕" });
    const sub = screen.getByTestId("caption-subtitle");
    expect(sub.textContent).toContain("显示中的字幕");
  });
});

describe("CaptionLayer 打断 glyph", () => {
  it("speaking 时字幕区注册为 active zone", () => {
    const { store: status } = makeFakeStatusStore({ state: "speaking", reply: "x", replySeq: 1 });
    const { store: subtitle } = makeFakeSubtitleStore({ visible: true, text: "字幕" });
    const { registry, registerZone } = makeFakeZoneRegistry();
    render(
      <CaptionLayer
        statusStore={status}
        hudStore={hudStore}
        subtitleStore={subtitle}
        registry={registry}
      />,
    );
    expect(registerZone).toHaveBeenCalledWith(
      "caption-subtitle",
      expect.objectContaining({ width: expect.any(Number) }),
    );
  });

  it("非 speaking 时不注册字幕分区", () => {
    const { store: status } = makeFakeStatusStore({ state: "idle" });
    const { store: subtitle } = makeFakeSubtitleStore();
    const { registry, registerZone } = makeFakeZoneRegistry();
    render(
      <CaptionLayer
        statusStore={status}
        hudStore={hudStore}
        subtitleStore={subtitle}
        registry={registry}
      />,
    );
    expect(registerZone).not.toHaveBeenCalledWith(
      "caption-subtitle",
      expect.anything(),
    );
  });

  it("speaking + hover 字幕区 → 打断 glyph 显影（square 图标）", () => {
    const { store: status } = makeFakeStatusStore({ state: "speaking", reply: "x", replySeq: 1 });
    const { store: subtitle } = makeFakeSubtitleStore({ visible: true, text: "字幕" });
    const { registry } = makeFakeZoneRegistry();
    render(
      <CaptionLayer
        statusStore={status}
        hudStore={hudStore}
        subtitleStore={subtitle}
        registry={registry}
      />,
    );
    expect(screen.queryByTestId("caption-interrupt")).toBeNull();
    fireEvent.pointerEnter(screen.getByTestId("caption-subtitle"));
    expect(screen.getByTestId("caption-interrupt")).toBeInTheDocument();
  });

  it("点击打断 glyph → interruptSpeaking + subtitleStore.hide", () => {
    const { store: status } = makeFakeStatusStore({ state: "speaking", reply: "x", replySeq: 1 });
    const { store: subtitle, hide } = makeFakeSubtitleStore({ visible: true, text: "字幕" });
    const { registry } = makeFakeZoneRegistry();
    render(
      <CaptionLayer
        statusStore={status}
        hudStore={hudStore}
        subtitleStore={subtitle}
        registry={registry}
      />,
    );
    fireEvent.pointerEnter(screen.getByTestId("caption-subtitle"));
    fireEvent.click(screen.getByTestId("caption-interrupt"));
    expect(interruptSpeaking).toHaveBeenCalledTimes(1);
    expect(hide).toHaveBeenCalledTimes(1);
  });

  it("打断后 voice 离开 speaking 不再 finish（hide 已抢先）", () => {
    const { store: status, setVoice } = makeFakeStatusStore({
      state: "speaking",
      reply: "x",
      replySeq: 1,
    });
    const { store: subtitle, finish } = makeFakeSubtitleStore({
      visible: true,
      text: "字幕",
    });
    const { registry } = makeFakeZoneRegistry();
    render(
      <CaptionLayer
        statusStore={status}
        hudStore={hudStore}
        subtitleStore={subtitle}
        registry={registry}
      />,
    );
    fireEvent.pointerEnter(screen.getByTestId("caption-subtitle"));
    fireEvent.click(screen.getByTestId("caption-interrupt"));
    finish.mockClear();
    setVoice({ state: "wake_listening" });
    expect(finish).not.toHaveBeenCalled();
  });
});

describe("CaptionLayer 睡眠态", () => {
  it("睡眠态不注册字幕分区、不显字幕内容", () => {
    hudStore.setSleeping(true);
    const { store: status } = makeFakeStatusStore({ state: "speaking", reply: "x", replySeq: 1 });
    const { store: subtitle } = makeFakeSubtitleStore({ visible: true, text: "字幕" });
    const { registry, registerZone } = makeFakeZoneRegistry();
    render(
      <CaptionLayer
        statusStore={status}
        hudStore={hudStore}
        subtitleStore={subtitle}
        registry={registry}
      />,
    );
    expect(registerZone).not.toHaveBeenCalledWith("caption-subtitle", expect.anything());
    expect(screen.queryByTestId("caption-subtitle")).toBeNull();
  });
});

describe("CaptionLayer 字幕显影/渐隐过渡（三阶段：streaming→final_show→fading_out→hidden）", () => {
  it("streaming 态（visible=true, fadingOut=false）加 --visible 类（opacity:1）", () => {
    const { store: status } = makeFakeStatusStore({ state: "speaking", reply: "x", replySeq: 1 });
    const { store: subtitle, setState } = makeFakeSubtitleStore();
    render(
      <CaptionLayer
        statusStore={status}
        hudStore={hudStore}
        subtitleStore={subtitle}
      />,
    );
    expect(screen.queryByTestId("caption-subtitle")).toBeNull();
    // streaming：visible=true, isFinal=false, fadingOut=false
    setState({ visible: true, isFinal: false, fadingOut: false, text: "显影中" });
    const sub = screen.getByTestId("caption-subtitle");
    expect(sub).toHaveClass("caption-subtitle");
    expect(sub).toHaveClass("caption-subtitle--visible");
    expect(sub).toHaveAttribute("data-revealed", "true");
    expect(sub).toHaveAttribute("data-fading", "false");
  });

  it("final_show 态（isFinal=true, fadingOut=false）保持 --visible 类（文字完整展示）", () => {
    const { store: status } = makeFakeStatusStore({ state: "speaking", reply: "x", replySeq: 1 });
    const { store: subtitle, setState } = makeFakeSubtitleStore();
    render(
      <CaptionLayer
        statusStore={status}
        hudStore={hudStore}
        subtitleStore={subtitle}
      />,
    );
    setState({ visible: true, isFinal: true, fadingOut: false, text: "完整文字" });
    const sub = screen.getByTestId("caption-subtitle");
    expect(sub).toHaveClass("caption-subtitle--visible");
    expect(sub).toHaveAttribute("data-revealed", "true");
    expect(sub).toHaveAttribute("data-fading", "false");
  });

  it("fading_out 态（fadingOut=true）移除 --visible 类（触发 opacity:0 CSS 渐隐）", () => {
    const { store: status } = makeFakeStatusStore({ state: "speaking", reply: "x", replySeq: 1 });
    const { store: subtitle, setState } = makeFakeSubtitleStore();
    render(
      <CaptionLayer
        statusStore={status}
        hudStore={hudStore}
        subtitleStore={subtitle}
      />,
    );
    setState({ visible: true, isFinal: false, fadingOut: false, text: "显影中" });
    expect(screen.getByTestId("caption-subtitle")).toHaveClass("caption-subtitle--visible");
    // 进入 fading_out：fadingOut=true（仍 visible，DOM 保留，CSS 过渡渐隐）
    setState({ visible: true, isFinal: true, fadingOut: true, text: "显影中" });
    const sub = screen.getByTestId("caption-subtitle");
    expect(sub).toHaveClass("caption-subtitle");
    expect(sub).not.toHaveClass("caption-subtitle--visible");
    expect(sub).toHaveAttribute("data-revealed", "false");
    expect(sub).toHaveAttribute("data-fading", "true");
  });

  it("hidden（visible=false）后元素卸载，无悬挂类", () => {
    const { store: status } = makeFakeStatusStore({ state: "speaking", reply: "x", replySeq: 1 });
    const { store: subtitle, setState } = makeFakeSubtitleStore();
    render(
      <CaptionLayer
        statusStore={status}
        hudStore={hudStore}
        subtitleStore={subtitle}
      />,
    );
    setState({ visible: true, isFinal: false, fadingOut: false, text: "显影中" });
    expect(screen.getByTestId("caption-subtitle")).toBeInTheDocument();
    setState({ visible: false, isFinal: false, fadingOut: false, text: "" });
    expect(screen.queryByTestId("caption-subtitle")).toBeNull();
  });
});
