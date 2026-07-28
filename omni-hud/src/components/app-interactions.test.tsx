/**
 * App 交互接线测试（M5.3 建，M7.2 随新骨架重写）：
 * - 内容层 pointerdown → 3D 空间 addRippleAt（NDC 换算）+ pulseAttractor + morphTo；
 *   成形保持后 releaseShape 缓释；卸载时取消未触发缓释
 * - bindSpaceMood：voice.state 变化 → setMood 推送（speaking → 流速 ×2.0 / bloom +0.15）
 * createSpace / runtime / statusRuntime 全部 mock，不碰 WebGL / IPC。
 */
import { act, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EMPTY_HOME_SUMMARY, EMPTY_SYSTEM_STATS, EMPTY_VOICE_STATUS } from "../data/sources";
import { MOOD_TABLE } from "../space/mood";
import type { StatusState } from "../store/statusStore";

// ResizeObserver polyfill（M7.4 useRegisteredZone 依赖，jsdom 不提供）。
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
(globalThis as unknown as { ResizeObserver: typeof ResizeObserverStub }).ResizeObserver =
  ResizeObserverStub;

// ---- fake createSpace 模块：捕获场景 stub 供断言 ----
const addRippleAtMock = vi.fn<(x: number, y: number) => boolean>(() => true);
const pulseAttractorMock = vi.fn();
const morphToMock = vi.fn();
const releaseShapeMock = vi.fn();
const setMoodMock = vi.fn();
const createSpaceMock = vi.fn((..._args: unknown[]) => ({
  dispose: () => {},
  applyTheme: () => {},
  setReducedMotion: () => {},
  setPointer: () => {},
  setQuality: () => {},
  resize: () => {},
  addRippleAt: addRippleAtMock,
  pulseAttractor: pulseAttractorMock,
  morphTo: morphToMock,
  releaseShape: releaseShapeMock,
  setMood: setMoodMock,
  setField: () => {},
}));

vi.mock("../space/createSpace", () => ({
  createSpace: (...args: unknown[]) => createSpaceMock(...args),
  PLACEHOLDER_POINT_COUNT: 50,
}));

vi.mock("../space/runtime", () => ({
  loadSpaceRuntime: () => ({ three: {}, postfx: undefined }),
}));

// M7.4：subtitleStore / zoneRegistryRuntime 经运行时单例注入真实定时器与 IPC，
// 交互测试替换为静止桩——字幕恒不可见、registry 空操作，不干扰场景 mock 断言。
// getState / getZones 必须返回稳定引用（useSyncExternalStore 契约），否则触发无限渲染。
const subtitleState = { visible: false, text: "", isFinal: false };
const zonesList: readonly never[] = [];
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

// ---- 可控 statusStore：测试手动推送 voice.state ----
// getState 必须返回稳定引用（useSyncExternalStore 契约），仅在推送时重建。
const statusListeners = new Set<() => void>();
let currentStatus: StatusState = {
  voice: { ...EMPTY_VOICE_STATUS, available: true, state: null },
  home: EMPTY_HOME_SUMMARY,
  system: EMPTY_SYSTEM_STATS,
  failures: { voice: 0, home: 0, system: 0 },
  running: true,
  paused: false,
};

vi.mock("../store/statusRuntime", () => ({
  getStatusStore: () => ({
    getState: (): StatusState => currentStatus,
    subscribe: (listener: () => void) => {
      statusListeners.add(listener);
      return () => {
        statusListeners.delete(listener);
      };
    },
    start: () => {},
    stop: () => {},
    pause: () => {},
    resume: () => {},
  }),
}));

import { App } from "../App";

// jsdom 未实现 PointerEvent 构造器：用 MouseEvent 携带 pointerdown 类型派发（同 RippleLayer.test）。
function pointerDown(target: Element, clientX: number, clientY: number): void {
  act(() => {
    target.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, clientX, clientY }));
  });
}

const pushVoiceState = (state: StatusState["voice"]["state"]): void => {
  currentStatus = {
    ...currentStatus,
    voice: { ...currentStatus.voice, state },
  };
  act(() => {
    for (const listener of statusListeners) listener();
  });
};

beforeEach(() => {
  currentStatus = {
    voice: { ...EMPTY_VOICE_STATUS, available: true, state: null },
    home: EMPTY_HOME_SUMMARY,
    system: EMPTY_SYSTEM_STATS,
    failures: { voice: 0, home: 0, system: 0 },
    running: true,
    paused: false,
  };
  statusListeners.clear();
  addRippleAtMock.mockClear();
  pulseAttractorMock.mockClear();
  morphToMock.mockClear();
  releaseShapeMock.mockClear();
  setMoodMock.mockClear();
  createSpaceMock.mockClear();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("App 点击交互 → 3D 空间", () => {
  it("pointerdown 触发 addRippleAt（像素 → NDC 换算）+ 脉冲 + 首个形状聚集", async () => {
    render(<App />);
    await waitFor(() => expect(createSpaceMock).toHaveBeenCalledTimes(1));
    const content = document.querySelector(".hud-content") as HTMLElement;
    pointerDown(content, 190, 280);
    expect(addRippleAtMock).toHaveBeenCalledTimes(1);
    const [nx, ny] = addRippleAtMock.mock.calls[0]!;
    expect(nx).toBeCloseTo((190 / window.innerWidth) * 2 - 1, 6);
    expect(ny).toBeCloseTo(-((280 / window.innerHeight) * 2 - 1), 6);
    expect(pulseAttractorMock).toHaveBeenCalledTimes(1);
    expect(morphToMock).toHaveBeenCalledWith("sphere");
  });

  it("连续点击轮换形状；成形保持后缓释 releaseShape", async () => {
    render(<App />);
    await waitFor(() => expect(createSpaceMock).toHaveBeenCalledTimes(1));
    const content = document.querySelector(".hud-content") as HTMLElement;
    vi.useFakeTimers(); // 先接管 setTimeout：clickGather 的缓释计时才可推进
    pointerDown(content, 10, 10);
    pointerDown(content, 20, 20);
    expect(morphToMock.mock.calls.map((c) => c[0])).toEqual(["sphere", "ring"]);
    act(() => {
      vi.advanceTimersByTime(2000); // > GATHER_HOLD_MS(1400)
    });
    expect(releaseShapeMock).toHaveBeenCalledTimes(1); // 旧计时已被重置，只缓释一次
  });

  it("卸载时取消未触发的缓释，不再触碰场景", async () => {
    const { unmount } = render(<App />);
    await waitFor(() => expect(createSpaceMock).toHaveBeenCalledTimes(1));
    const content = document.querySelector(".hud-content") as HTMLElement;
    pointerDown(content, 10, 10);
    unmount();
    vi.useFakeTimers();
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(releaseShapeMock).not.toHaveBeenCalled();
  });
});

describe("App 语音氛围接线（bindSpaceMood）", () => {
  it("voice.state → speaking 时 setMood 推送 speaking 映射（流速 ×2.0 / bloom +0.15）", async () => {
    render(<App />);
    await waitFor(() => expect(createSpaceMock).toHaveBeenCalledTimes(1));
    pushVoiceState("speaking");
    expect(setMoodMock).toHaveBeenCalledWith(MOOD_TABLE.speaking);
    expect(MOOD_TABLE.speaking).toEqual({ flowScale: 2.0, bloomBoost: 0.15 });
  });

  it("voice.state 回到 idle 时 setMood 推送平静基线", async () => {
    render(<App />);
    await waitFor(() => expect(createSpaceMock).toHaveBeenCalledTimes(1));
    pushVoiceState("speaking");
    setMoodMock.mockClear();
    pushVoiceState("idle");
    expect(setMoodMock).toHaveBeenCalledWith({ flowScale: 1, bloomBoost: 0 });
  });

  it("状态未变化时不重复推送（bindSpaceMood 去重）", async () => {
    render(<App />);
    await waitFor(() => expect(createSpaceMock).toHaveBeenCalledTimes(1));
    pushVoiceState("speaking");
    expect(setMoodMock).toHaveBeenCalledTimes(1);
    pushVoiceState("speaking"); // 同值再推：监听器触发但映射未变
    expect(setMoodMock).toHaveBeenCalledTimes(1);
  });
});
