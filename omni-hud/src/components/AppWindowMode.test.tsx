/**
 * App 窗口形态切换测试（M12 灵动岛双形态 TDD）。
 *
 * 验证 App.tsx 根据 statusStore.voice.windowMode 渲染对应布局：
 * - windowMode === "mini" → 渲染 MiniBar，不渲染 Full 槽位（FieldStage/CaptionLayer/WellZone）；
 * - windowMode === "full" / null → 渲染 Full 布局，不渲染 MiniBar。
 *
 * 模拟方式：替换 statusRuntime 的 getStatusStore，注入可控 fake store，
 * 使 voice.windowMode 可在测试中切换。不碰真实 IPC / WebGL / 定时器。
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

// 静止桩 store——subtitleStore / zoneRegistryRuntime / statusRuntime 经运行时
// 单例注入真实定时器与 IPC，布局测试替换为静止桩避免异步更新。
const subtitleState = { visible: false, text: "", isFinal: false };
const zonesList: readonly never[] = [];

function makeFakeStatusStore(windowMode: WindowMode | null): {
  store: StatusStore;
  setWindowMode(mode: WindowMode | null): void;
} {
  let voice: VoiceStatus = { ...EMPTY_VOICE_STATUS, available: true, windowMode };
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
    setWindowMode(mode) {
      voice = { ...voice, windowMode: mode };
      state = { ...state, voice };
      act(() => {
        for (const listener of [...listeners]) listener();
      });
    },
  };
}

let currentFake: { store: StatusStore; setWindowMode: (mode: WindowMode | null) => void };

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

// M13.5 AgentPanel 集成：mock agentRuntime 返回静止 store，避免单例污染与
// bindAgentSync 把 fake statusStore 的 speaking 事件同步到 messages。
const agentState = { messages: [] as readonly never[], currentToolCalls: [] as readonly never[] };
vi.mock("../store/agentRuntime", () => ({
  getAgentStore: () => ({
    getState: () => agentState,
    subscribe: () => () => {},
    addUserMessage: () => {},
    addAssistantMessage: () => {},
    addToolCall: () => {},
    updateToolCall: () => {},
    clearSession: () => {},
  }),
  bindAgentSync: () => () => {},
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

// Mock invoke 以验证 set_window_mode 调用。
const invokeMock = vi.fn().mockResolvedValue(undefined);
vi.mock("@tauri-apps/api/core", () => ({
  invoke: (cmd: string, args?: unknown) => invokeMock(cmd, args),
}));

// M22.2：mock hudStore 以可控 wallpaperMode（默认 false，测试可切换）。
// M22.5：扩展 wallpaperAwake 标记（唤醒浮出）。
// 注意：getState 必须返回稳定引用（同一对象），否则 useSyncExternalStore
// 检测到 snapshot 变化无限重渲染 → Maximum update depth exceeded。
let wallpaperModeFlag = false;
let wallpaperAwakeFlag = false;
let wallpaperAwakeSeq = 0;
const hudListeners = new Set<() => void>();
let cachedHudState: {
  reducedMotion: boolean;
  sleeping: boolean;
  fieldMode: "space";
  cinemaMode: "off";
  wallpaperMode: boolean;
  wallpaperAwake: boolean;
  wallpaperAwakeSeq: number;
};
function rebuildHudState(): void {
  cachedHudState = {
    reducedMotion: false,
    sleeping: false,
    fieldMode: "space",
    cinemaMode: "off",
    wallpaperMode: wallpaperModeFlag,
    wallpaperAwake: wallpaperAwakeFlag,
    wallpaperAwakeSeq,
  };
}
rebuildHudState();
vi.mock("../store/hudStore", () => ({
  createHudStore: () => ({
    getState: () => cachedHudState,
    subscribe: (listener: () => void) => {
      hudListeners.add(listener);
      return () => {
        hudListeners.delete(listener);
      };
    },
    setReducedMotion: () => {},
    setSleeping: () => {},
    toggleSleeping: () => false,
    setFieldMode: () => {},
    toggleFieldMode: () => "space" as const,
    setCinemaMode: () => {},
    setWallpaperMode: (flag: boolean) => {
      wallpaperModeFlag = flag;
      if (!flag) {
        wallpaperAwakeFlag = false; // 退出壁纸模式同步清 awake
        wallpaperAwakeSeq = 0; // 重置 seq，下次唤醒从 1 起算
      }
      rebuildHudState();
      act(() => {
        for (const listener of [...hudListeners]) listener();
      });
    },
    toggleWallpaperMode: () => {
      wallpaperModeFlag = !wallpaperModeFlag;
      if (!wallpaperModeFlag) {
        wallpaperAwakeFlag = false;
        wallpaperAwakeSeq = 0;
      }
      rebuildHudState();
      act(() => {
        for (const listener of [...hudListeners]) listener();
      });
      return wallpaperModeFlag;
    },
    wakeWallpaper: () => {
      wallpaperAwakeFlag = true;
      wallpaperAwakeSeq += 1; // 自增 seq 驱动 effect 重跑（重置 2s 倒计时）
      rebuildHudState();
      act(() => {
        for (const listener of [...hudListeners]) listener();
      });
    },
    sleepWallpaper: () => {
      wallpaperAwakeFlag = false;
      rebuildHudState();
      act(() => {
        for (const listener of [...hudListeners]) listener();
      });
    },
  }),
}));

import { App } from "../App";

beforeEach(() => {
  invokeMock.mockClear();
  wallpaperModeFlag = false;
  wallpaperAwakeFlag = false;
  wallpaperAwakeSeq = 0;
  rebuildHudState();
  hudListeners.clear();
});

/** 测试辅助：设置 wallpaperMode 并重建 cachedHudState；渲染后调用需通知订阅者
 *  以触发重渲染（包在 act 中刷新 React 更新）。渲染前调用时无订阅者，act 空转。 */
function setWallpaperFlag(flag: boolean): void {
  wallpaperModeFlag = flag;
  if (!flag) {
    wallpaperAwakeFlag = false;
    wallpaperAwakeSeq = 0;
  }
  rebuildHudState();
  act(() => {
    for (const listener of [...hudListeners]) listener();
  });
}

/** 测试辅助：设置 wallpaperAwake 并重建 cachedHudState（渲染前调用，不通知）。 */
function setWallpaperAwake(flag: boolean): void {
  wallpaperAwakeFlag = flag;
  rebuildHudState();
}

/** 测试辅助：唤醒浮出——自增 seq + 置 awake=true + 通知（包 act）。
 *  seq 自增驱动 App.tsx 2s 渐回计时器 effect 重跑，支持重复唤醒重置倒计时。 */
function wakeWallpaper(): void {
  wallpaperAwakeFlag = true;
  wallpaperAwakeSeq += 1;
  rebuildHudState();
  act(() => {
    for (const listener of [...hudListeners]) listener();
  });
}

/** 测试辅助：结束唤醒浮出——清 awake + 通知（包 act）。 */
function sleepWallpaper(): void {
  wallpaperAwakeFlag = false;
  rebuildHudState();
  act(() => {
    for (const listener of [...hudListeners]) listener();
  });
}

describe("App 窗口形态切换（M12）", () => {
  it("windowMode=null（缺省）渲染 Full 布局，不渲染 MiniBar", () => {
    currentFake = makeFakeStatusStore(null);
    render(<App />);
    expect(screen.getByTestId("hud-root")).toBeInTheDocument();
    expect(screen.getByTestId("field-stage")).toBeInTheDocument();
    expect(screen.queryByTestId("mini-bar")).toBeNull();
  });

  it("windowMode=full 渲染 Full 布局，不渲染 MiniBar", () => {
    currentFake = makeFakeStatusStore("full");
    render(<App />);
    expect(screen.getByTestId("field-stage")).toBeInTheDocument();
    expect(screen.getByTestId("caption-layer")).toBeInTheDocument();
    expect(screen.getByTestId("well-zone")).toBeInTheDocument();
    expect(screen.queryByTestId("mini-bar")).toBeNull();
  });

  it("windowMode=full 时渲染 AgentPanel（M13.6 集成）", () => {
    currentFake = makeFakeStatusStore("full");
    render(<App />);
    expect(screen.getByTestId("agent-panel")).toBeInTheDocument();
  });

  it("windowMode=mini 渲染 MiniBar，不渲染 Full 槽位", () => {
    currentFake = makeFakeStatusStore("mini");
    render(<App />);
    expect(screen.getByTestId("mini-bar")).toBeInTheDocument();
    expect(screen.queryByTestId("field-stage")).toBeNull();
    expect(screen.queryByTestId("caption-layer")).toBeNull();
    expect(screen.queryByTestId("well-zone")).toBeNull();
  });

  it("windowMode=mini 时不渲染 AgentPanel（M13.6 集成）", () => {
    currentFake = makeFakeStatusStore("mini");
    render(<App />);
    expect(screen.queryByTestId("agent-panel")).toBeNull();
  });

  it("windowMode 从 full 切到 mini 时卸载 Full 槽位、挂载 MiniBar", () => {
    currentFake = makeFakeStatusStore("full");
    render(<App />);
    expect(screen.getByTestId("field-stage")).toBeInTheDocument();
    expect(screen.queryByTestId("mini-bar")).toBeNull();

    currentFake.setWindowMode("mini");
    expect(screen.getByTestId("mini-bar")).toBeInTheDocument();
    expect(screen.queryByTestId("field-stage")).toBeNull();
  });

  it("windowMode 从 mini 切到 full 时卸载 MiniBar、挂载 Full 槽位", () => {
    currentFake = makeFakeStatusStore("mini");
    render(<App />);
    expect(screen.getByTestId("mini-bar")).toBeInTheDocument();

    currentFake.setWindowMode("full");
    expect(screen.queryByTestId("mini-bar")).toBeNull();
    expect(screen.getByTestId("field-stage")).toBeInTheDocument();
  });
});

describe("App 壁纸模式渲染（M22.2）", () => {
  it("windowMode=wallpaper 渲染 Full 布局（同 full），不渲染 MiniBar", () => {
    currentFake = makeFakeStatusStore("wallpaper");
    render(<App />);
    expect(screen.getByTestId("field-stage")).toBeInTheDocument();
    expect(screen.getByTestId("caption-layer")).toBeInTheDocument();
    expect(screen.getByTestId("well-zone")).toBeInTheDocument();
    expect(screen.queryByTestId("mini-bar")).toBeNull();
  });

  it("windowMode=wallpaper 时 hud-root 带 hud-root-wallpaper class 与 data-window-mode", () => {
    currentFake = makeFakeStatusStore("wallpaper");
    render(<App />);
    const root = screen.getByTestId("hud-root");
    expect(root.className).toContain("hud-root-wallpaper");
    expect(root.getAttribute("data-window-mode")).toBe("wallpaper");
  });

  it("windowMode=full 时 hud-root 不带 hud-root-wallpaper class", () => {
    currentFake = makeFakeStatusStore("full");
    render(<App />);
    const root = screen.getByTestId("hud-root");
    expect(root.className).not.toContain("hud-root-wallpaper");
    expect(root.getAttribute("data-window-mode")).toBe("full");
  });

  it("windowMode=wallpaper 时 invoke('set_window_mode', {mode:'wallpaper'}) 被调用", () => {
    currentFake = makeFakeStatusStore("wallpaper");
    render(<App />);
    expect(invokeMock).toHaveBeenCalledWith("set_window_mode", { mode: "wallpaper" });
  });

  it("windowMode 从 wallpaper 切到 full（活跃态浮出）时卸载 wallpaper class", () => {
    currentFake = makeFakeStatusStore("wallpaper");
    render(<App />);
    expect(screen.getByTestId("hud-root").className).toContain("hud-root-wallpaper");

    currentFake.setWindowMode("full");
    expect(screen.getByTestId("hud-root").className).not.toContain("hud-root-wallpaper");
    expect(screen.getByTestId("hud-root").getAttribute("data-window-mode")).toBe("full");
  });
});

describe("App 壁纸模式与语音推导合并（M22.2 wallpaperMode + voiceWindowMode）", () => {
  it("wallpaperMode=true + voice=mini → 渲染 wallpaper 形态（非 mini）", () => {
    setWallpaperFlag(true);
    currentFake = makeFakeStatusStore("mini");
    render(<App />);
    // wallpaperMode=true 把 mini 覆盖为 wallpaper：渲染 Full 布局而非 MiniBar
    expect(screen.queryByTestId("mini-bar")).toBeNull();
    expect(screen.getByTestId("field-stage")).toBeInTheDocument();
    const root = screen.getByTestId("hud-root");
    expect(root.className).toContain("hud-root-wallpaper");
    expect(root.getAttribute("data-window-mode")).toBe("wallpaper");
  });

  it("wallpaperMode=true + voice=full（活跃态）→ 渲染 full 形态（浮出非壁纸）", () => {
    setWallpaperFlag(true);
    currentFake = makeFakeStatusStore("full");
    render(<App />);
    // 活跃态优先：wallpaperMode 让位于 voice=full
    const root = screen.getByTestId("hud-root");
    expect(root.className).not.toContain("hud-root-wallpaper");
    expect(root.getAttribute("data-window-mode")).toBe("full");
  });

  it("wallpaperMode=true + voice=null（缺省）→ 渲染 full 形态（安全态优先）", () => {
    setWallpaperFlag(true);
    currentFake = makeFakeStatusStore(null);
    render(<App />);
    // null 缺省按 full 处理（安全态），wallpaperMode 不把 null 当 mini 覆盖
    const root = screen.getByTestId("hud-root");
    expect(root.getAttribute("data-window-mode")).toBe("full");
  });

  it("wallpaperMode=false + voice=mini → 渲染 mini 形态（不沉到壁纸层）", () => {
    setWallpaperFlag(false);
    currentFake = makeFakeStatusStore("mini");
    render(<App />);
    // wallpaperMode=false：沿用 M12 mini 形态，不触发壁纸模式
    expect(screen.getByTestId("mini-bar")).toBeInTheDocument();
    expect(screen.queryByTestId("field-stage")).toBeNull();
  });

  it("voice 从 mini→full→mini（wallpaperMode=true）：wallpaper→full→wallpaper", () => {
    setWallpaperFlag(true);
    currentFake = makeFakeStatusStore("mini");
    render(<App />);
    // idle → wallpaper
    expect(screen.getByTestId("hud-root").getAttribute("data-window-mode")).toBe("wallpaper");
    // 唤醒 → full（浮出）
    currentFake.setWindowMode("full");
    expect(screen.getByTestId("hud-root").getAttribute("data-window-mode")).toBe("full");
    // 回 idle → wallpaper（渐回壁纸态）
    currentFake.setWindowMode("mini");
    expect(screen.getByTestId("hud-root").getAttribute("data-window-mode")).toBe("wallpaper");
  });
});

describe("App 壁纸模式唤醒浮出（M22.5 wallpaperAwake）", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("wallpaperMode=true + voice=mini + wallpaperAwake=true → 渲染 full 形态（浮出）", () => {
    setWallpaperFlag(true);
    setWallpaperAwake(true);
    currentFake = makeFakeStatusStore("mini");
    render(<App />);
    // 唤醒浮出：wallpaperAwake=true 把 wallpaper 覆盖为 full（浮到 screenSaver level）
    const root = screen.getByTestId("hud-root");
    expect(root.getAttribute("data-window-mode")).toBe("full");
    expect(root.className).not.toContain("hud-root-wallpaper");
  });

  it("wallpaperMode=true + voice=mini + wallpaperAwake=false → 渲染 wallpaper 形态（沉）", () => {
    setWallpaperFlag(true);
    setWallpaperAwake(false);
    currentFake = makeFakeStatusStore("mini");
    render(<App />);
    // 未唤醒：保持壁纸态（沉到 desktopIcon level）
    const root = screen.getByTestId("hud-root");
    expect(root.getAttribute("data-window-mode")).toBe("wallpaper");
    expect(root.className).toContain("hud-root-wallpaper");
  });

  it("wallpaperMode=true + voice=full + wallpaperAwake=true → 仍渲染 full（voice 优先）", () => {
    setWallpaperFlag(true);
    setWallpaperAwake(true);
    currentFake = makeFakeStatusStore("full");
    render(<App />);
    // voice=full 活跃态优先于 wallpaperAwake，windowMode=full
    const root = screen.getByTestId("hud-root");
    expect(root.getAttribute("data-window-mode")).toBe("full");
  });

  it("wallpaperAwake 从 true→false：windowMode 从 full 切回 wallpaper", () => {
    setWallpaperFlag(true);
    currentFake = makeFakeStatusStore("mini");
    render(<App />);
    // 唤醒 → full
    wakeWallpaper();
    expect(screen.getByTestId("hud-root").getAttribute("data-window-mode")).toBe("full");
    // 2s 后渐回壁纸态 → sleepWallpaper
    sleepWallpaper();
    expect(screen.getByTestId("hud-root").getAttribute("data-window-mode")).toBe("wallpaper");
  });

  it("wallpaperAwake=true 时 invoke('set_window_mode', {mode:'full'}) 被调用（浮到 screenSaver level）", () => {
    setWallpaperFlag(true);
    currentFake = makeFakeStatusStore("mini");
    render(<App />);
    invokeMock.mockClear();
    // 唤醒浮出 → windowMode 切到 full → invoke set_window_mode
    wakeWallpaper();
    expect(invokeMock).toHaveBeenCalledWith("set_window_mode", { mode: "full" });
  });

  it("唤醒浮出 2s 后自动 sleepWallpaper（渐回壁纸态）", async () => {
    setWallpaperFlag(true);
    currentFake = makeFakeStatusStore("mini");
    render(<App />);
    // 唤醒 → full
    wakeWallpaper();
    expect(screen.getByTestId("hud-root").getAttribute("data-window-mode")).toBe("full");
    // 快进 2s → 自动 sleepWallpaper → wallpaper
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByTestId("hud-root").getAttribute("data-window-mode")).toBe("wallpaper");
  });

  it("唤醒浮出后再次双击唤醒重置 2s 计时器（不提前渐回）", async () => {
    setWallpaperFlag(true);
    currentFake = makeFakeStatusStore("mini");
    render(<App />);
    wakeWallpaper();
    // 快进 1.5s（接近 2s 但未到）
    act(() => {
      vi.advanceTimersByTime(1500);
    });
    expect(screen.getByTestId("hud-root").getAttribute("data-window-mode")).toBe("full");
    // 再次唤醒 → 重置计时器
    wakeWallpaper();
    act(() => {
      vi.advanceTimersByTime(1500);
    });
    // 重置后 1.5s 仍为 full（如果没重置此时已渐回 wallpaper）
    expect(screen.getByTestId("hud-root").getAttribute("data-window-mode")).toBe("full");
    // 再过 0.5s（总 2s 后）渐回
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(screen.getByTestId("hud-root").getAttribute("data-window-mode")).toBe("wallpaper");
  });

  it("卸载时清除 2s 计时器（不触发 sleepWallpaper 导致状态泄漏）", () => {
    setWallpaperFlag(true);
    currentFake = makeFakeStatusStore("mini");
    const { unmount } = render(<App />);
    wakeWallpaper();
    expect(wallpaperAwakeFlag).toBe(true);
    unmount();
    // 快进 2s —— unmount 后计时器已清除，不会调 sleepWallpaper
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    // wallpaperAwakeFlag 仍为 true（计时器未触发 sleepWallpaper）
    expect(wallpaperAwakeFlag).toBe(true);
  });

  it("退出壁纸模式时同步清 wallpaperAwake（不残留浮出态）", () => {
    setWallpaperFlag(true);
    setWallpaperAwake(true);
    currentFake = makeFakeStatusStore("mini");
    render(<App />);
    expect(screen.getByTestId("hud-root").getAttribute("data-window-mode")).toBe("full");
    // 退出壁纸模式 → wallpaperAwake 同步清零 → windowMode 回 voice 推导
    setWallpaperFlag(false);
    // voice=mini + wallpaperMode=false → mini 形态
    expect(screen.getByTestId("mini-bar")).toBeInTheDocument();
    expect(wallpaperAwakeFlag).toBe(false);
  });
});
