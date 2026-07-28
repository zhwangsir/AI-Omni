/**
 * WellZone 组件测试（M7.4 TDD）：声井 + 召唤控制环。
 *
 * 覆盖：
 * - 容器渲染 + 分区注册（zoneRegistry 接到 well rect）；
 * - hover 进出 → 控制环显隐；
 * - 语音状态点：可用 accent 色 / 不可用灰；
 * - 主题点：每主题一点，点击调 themeStore.setTheme；
 * - 睡眠切换：唤醒态显 Moon 点击入睡、睡眠态显 Sun 点击唤醒；
 * - 井心点击 → caption 卡（当前状态 + 最近回复摘要）显隐；
 * - 睡眠态：仅留声井分区、控制环收窄为唤醒入口；
 * - 卸载注销分区。
 *
 * 全 fake：statusStore / hudStore / themeStore / zoneRegistry 均注入桩，
 * 不触碰 Tauri IPC / 真实定时器。
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EMPTY_HOME_SUMMARY, EMPTY_SYSTEM_STATS, EMPTY_VOICE_STATUS, type VoiceStatus } from "../data/sources";
import type { Space } from "../space/createSpace";
import { THEMES } from "../theme/themes";
import { createHudStore, type HudStore } from "../store/hudStore";
import type { StatusState, StatusStore } from "../store/statusStore";
import type { ThemeStore } from "../theme/themeStore";
import type { ZoneRegistry } from "../store/zoneRegistry";

import { WellZone } from "./WellZone";

// ---- ResizeObserver polyfill（useRegisteredZone 依赖） --------------------
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
(globalThis as unknown as { ResizeObserver: typeof ResizeObserverStub }).ResizeObserver =
  ResizeObserverStub;

// ---- fake stores ---------------------------------------------------------

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

function makeFakeThemeStore(): {
  store: ThemeStore;
  setTheme: ReturnType<typeof vi.fn>;
} {
  const setTheme = vi.fn();
  let state = { themeId: THEMES[0]!.id, theme: THEMES[0]! };
  const listeners = new Set<() => void>();
  const store = {
    getState: () => state,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    setTheme: (id: string) => {
      setTheme(id);
      const theme = THEMES.find((t) => t.id === id);
      if (theme) {
        state = { themeId: theme.id, theme };
        act(() => {
          for (const listener of [...listeners]) listener();
        });
      }
    },
    cycleTheme: () => {},
  } as unknown as ThemeStore;
  return { store, setTheme };
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

/** 空 space ref（场景未就绪）——给既有不关心 morph 的测试用，避免无谓创建 fake。 */
const NULL_SPACE_REF = { current: null as Space | null };

/** fake Space：捕获 morphTo / releaseShape 调用供断言。 */
function makeFakeSpace(): {
  space: Space;
  morphTo: ReturnType<typeof vi.fn>;
  releaseShape: ReturnType<typeof vi.fn>;
} {
  const morphTo = vi.fn();
  const releaseShape = vi.fn();
  const space = { morphTo, releaseShape } as unknown as Space;
  return { space, morphTo, releaseShape };
}

function makeSpaceRef(space: Space | null): { current: Space | null } {
  return { current: space };
}

let hudStore: HudStore;

beforeEach(() => {
  hudStore = createHudStore();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("WellZone 容器与分区注册", () => {
  it("渲染 data-testid=well-zone 容器", () => {
    const { store: status } = makeFakeStatusStore();
    const { store: theme } = makeFakeThemeStore();
    render(<WellZone statusStore={status} hudStore={hudStore} themeStore={theme} spaceRef={NULL_SPACE_REF} />);
    expect(screen.getByTestId("well-zone")).toBeInTheDocument();
  });

  it("挂载即注册 well 分区（即使休眠态也保留声井点击区）", () => {
    const { store: status } = makeFakeStatusStore();
    const { store: theme } = makeFakeThemeStore();
    const { registry, registerZone } = makeFakeZoneRegistry();
    render(
      <WellZone
        statusStore={status}
        hudStore={hudStore}
        themeStore={theme}
        registry={registry}
        spaceRef={NULL_SPACE_REF}
      />,
    );
    expect(registerZone).toHaveBeenCalledWith(
      "well",
      expect.objectContaining({ width: expect.any(Number), height: expect.any(Number) }),
    );
  });

  it("卸载时注销 well 分区", () => {
    const { store: status } = makeFakeStatusStore();
    const { store: theme } = makeFakeThemeStore();
    const { registry, unregisterZone } = makeFakeZoneRegistry();
    const { unmount } = render(
      <WellZone
        statusStore={status}
        hudStore={hudStore}
        themeStore={theme}
        registry={registry}
        spaceRef={NULL_SPACE_REF}
      />,
    );
    unmount();
    expect(unregisterZone).toHaveBeenCalledWith("well");
  });
});

describe("WellZone 控制环显隐", () => {
  it("默认控制环不可见（无 hover）", () => {
    const { store: status } = makeFakeStatusStore();
    const { store: theme } = makeFakeThemeStore();
    render(<WellZone statusStore={status} hudStore={hudStore} themeStore={theme} spaceRef={NULL_SPACE_REF} />);
    expect(screen.queryByTestId("well-ring")).toBeNull();
  });

  it("pointer enter 控制环显影；pointer leave 收起", () => {
    const { store: status } = makeFakeStatusStore();
    const { store: theme } = makeFakeThemeStore();
    const { registry } = makeFakeZoneRegistry();
    render(
      <WellZone
        statusStore={status}
        hudStore={hudStore}
        themeStore={theme}
        registry={registry}
        spaceRef={NULL_SPACE_REF}
      />,
    );
    const zone = screen.getByTestId("well-zone");
    fireEvent.pointerEnter(zone);
    expect(screen.getByTestId("well-ring")).toBeInTheDocument();
    fireEvent.pointerLeave(zone);
    expect(screen.queryByTestId("well-ring")).toBeNull();
  });
});

describe("WellZone 语音状态点", () => {
  it("管道可用时状态点使用 accent 色（data-state 反映 voice.state）", () => {
    const { store: status } = makeFakeStatusStore({ available: true, state: "speaking" });
    const { store: theme } = makeFakeThemeStore();
    const { registry } = makeFakeZoneRegistry();
    render(
      <WellZone
        statusStore={status}
        hudStore={hudStore}
        themeStore={theme}
        registry={registry}
        spaceRef={NULL_SPACE_REF}
      />,
    );
    fireEvent.pointerEnter(screen.getByTestId("well-zone"));
    const dot = screen.getByTestId("well-status-dot");
    expect(dot).toHaveAttribute("data-state", "speaking");
    expect(dot).toHaveAttribute("data-available", "true");
  });

  it("管道不可用时状态点为灰（data-available=false）", () => {
    const { store: status } = makeFakeStatusStore({ available: false, state: null });
    const { store: theme } = makeFakeThemeStore();
    const { registry } = makeFakeZoneRegistry();
    render(
      <WellZone
        statusStore={status}
        hudStore={hudStore}
        themeStore={theme}
        registry={registry}
        spaceRef={NULL_SPACE_REF}
      />,
    );
    fireEvent.pointerEnter(screen.getByTestId("well-zone"));
    const dot = screen.getByTestId("well-status-dot");
    expect(dot).toHaveAttribute("data-available", "false");
  });
});

describe("WellZone 主题点", () => {
  it("控制环内每主题一个点，点击切换主题", () => {
    const { store: status } = makeFakeStatusStore();
    const { store: theme, setTheme } = makeFakeThemeStore();
    const { registry } = makeFakeZoneRegistry();
    render(
      <WellZone
        statusStore={status}
        hudStore={hudStore}
        themeStore={theme}
        registry={registry}
        spaceRef={NULL_SPACE_REF}
      />,
    );
    fireEvent.pointerEnter(screen.getByTestId("well-zone"));
    const dots = screen.getAllByTestId("well-theme-dot");
    expect(dots).toHaveLength(THEMES.length);
    // 当前主题标记为 active
    expect(dots[0]).toHaveAttribute("data-active", "true");
    // 点击第二主题
    fireEvent.click(dots[1]!);
    expect(setTheme).toHaveBeenCalledWith(THEMES[1]!.id);
  });
});

describe("WellZone 睡眠切换", () => {
  it("唤醒态显 Moon 图标，点击进入睡眠", () => {
    const { store: status } = makeFakeStatusStore();
    const { store: theme } = makeFakeThemeStore();
    const { registry } = makeFakeZoneRegistry();
    render(
      <WellZone
        statusStore={status}
        hudStore={hudStore}
        themeStore={theme}
        registry={registry}
        spaceRef={NULL_SPACE_REF}
      />,
    );
    fireEvent.pointerEnter(screen.getByTestId("well-zone"));
    const toggle = screen.getByTestId("well-sleep-toggle");
    expect(toggle).toHaveAttribute("data-sleeping", "false");
    fireEvent.click(toggle);
    expect(hudStore.getState().sleeping).toBe(true);
  });

  it("睡眠态显 Sun 图标，点击唤醒", () => {
    hudStore.setSleeping(true);
    const { store: status } = makeFakeStatusStore();
    const { store: theme } = makeFakeThemeStore();
    const { registry } = makeFakeZoneRegistry();
    render(
      <WellZone
        statusStore={status}
        hudStore={hudStore}
        themeStore={theme}
        registry={registry}
        spaceRef={NULL_SPACE_REF}
      />,
    );
    fireEvent.pointerEnter(screen.getByTestId("well-zone"));
    const toggle = screen.getByTestId("well-sleep-toggle");
    expect(toggle).toHaveAttribute("data-sleeping", "true");
    fireEvent.click(toggle);
    expect(hudStore.getState().sleeping).toBe(false);
  });
});

describe("WellZone 井心 caption 卡", () => {
  it("点击井心显影 caption 卡，再点收起", () => {
    const { store: status } = makeFakeStatusStore({ available: true, state: "idle", reply: "你好" });
    const { store: theme } = makeFakeThemeStore();
    const { registry } = makeFakeZoneRegistry();
    render(
      <WellZone
        statusStore={status}
        hudStore={hudStore}
        themeStore={theme}
        registry={registry}
        spaceRef={NULL_SPACE_REF}
      />,
    );
    fireEvent.pointerEnter(screen.getByTestId("well-zone"));
    expect(screen.queryByTestId("well-caption-card")).toBeNull();
    fireEvent.click(screen.getByTestId("well-center"));
    expect(screen.getByTestId("well-caption-card")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("well-center"));
    expect(screen.queryByTestId("well-caption-card")).toBeNull();
  });

  it("caption 卡显示当前语音状态与最近回复摘要", () => {
    const { store: status } = makeFakeStatusStore({
      available: true,
      state: "speaking",
      reply: "这是回复正文",
    });
    const { store: theme } = makeFakeThemeStore();
    const { registry } = makeFakeZoneRegistry();
    render(
      <WellZone
        statusStore={status}
        hudStore={hudStore}
        themeStore={theme}
        registry={registry}
        spaceRef={NULL_SPACE_REF}
      />,
    );
    fireEvent.pointerEnter(screen.getByTestId("well-zone"));
    fireEvent.click(screen.getByTestId("well-center"));
    const card = screen.getByTestId("well-caption-card");
    expect(card.textContent).toContain("speaking");
    expect(card.textContent).toContain("这是回复正文");
  });

  it("caption 卡展开时注册额外分区（卡区可交互）", () => {
    const { store: status } = makeFakeStatusStore({ reply: "摘要" });
    const { store: theme } = makeFakeThemeStore();
    const { registry, registerZone } = makeFakeZoneRegistry();
    render(
      <WellZone
        statusStore={status}
        hudStore={hudStore}
        themeStore={theme}
        registry={registry}
        spaceRef={NULL_SPACE_REF}
      />,
    );
    fireEvent.pointerEnter(screen.getByTestId("well-zone"));
    registerZone.mockClear();
    fireEvent.click(screen.getByTestId("well-center"));
    expect(registerZone).toHaveBeenCalledWith(
      "well-caption",
      expect.objectContaining({ width: expect.any(Number) }),
    );
  });
});

describe("WellZone 睡眠态行为", () => {
  it("睡眠态控制环收窄：仅显唤醒入口（无主题点 / 无状态点 / 无井心）", () => {
    hudStore.setSleeping(true);
    const { store: status } = makeFakeStatusStore();
    const { store: theme } = makeFakeThemeStore();
    const { registry } = makeFakeZoneRegistry();
    render(
      <WellZone
        statusStore={status}
        hudStore={hudStore}
        themeStore={theme}
        registry={registry}
        spaceRef={NULL_SPACE_REF}
      />,
    );
    fireEvent.pointerEnter(screen.getByTestId("well-zone"));
    expect(screen.getByTestId("well-sleep-toggle")).toBeInTheDocument();
    expect(screen.queryAllByTestId("well-theme-dot")).toHaveLength(0);
    expect(screen.queryByTestId("well-status-dot")).toBeNull();
    expect(screen.queryByTestId("well-center")).toBeNull();
  });
});

describe("WellZone 粒子聚集控制环（spec §五）", () => {
  it("hover 进入 → spaceRef.morphTo 被调（参数为 ring 形状）", () => {
    const { store: status } = makeFakeStatusStore();
    const { store: theme } = makeFakeThemeStore();
    const { registry } = makeFakeZoneRegistry();
    const { space, morphTo } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    render(
      <WellZone
        statusStore={status}
        hudStore={hudStore}
        themeStore={theme}
        registry={registry}
        spaceRef={spaceRef}
      />,
    );
    fireEvent.pointerEnter(screen.getByTestId("well-zone"));
    expect(morphTo).toHaveBeenCalledTimes(1);
    expect(morphTo).toHaveBeenCalledWith("ring");
  });

  it("hover 离开 → spaceRef.releaseShape 被调（环散开恢复自由流场）", () => {
    const { store: status } = makeFakeStatusStore();
    const { store: theme } = makeFakeThemeStore();
    const { registry } = makeFakeZoneRegistry();
    const { space, morphTo, releaseShape } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    render(
      <WellZone
        statusStore={status}
        hudStore={hudStore}
        themeStore={theme}
        registry={registry}
        spaceRef={spaceRef}
      />,
    );
    const zone = screen.getByTestId("well-zone");
    fireEvent.pointerEnter(zone);
    fireEvent.pointerLeave(zone);
    expect(morphTo).toHaveBeenCalledTimes(1);
    expect(releaseShape).toHaveBeenCalledTimes(1);
  });

  it("reducedMotion=true → hover 不调 morphTo / releaseShape（静态降级空操作）", () => {
    hudStore.setReducedMotion(true);
    const { store: status } = makeFakeStatusStore();
    const { store: theme } = makeFakeThemeStore();
    const { registry } = makeFakeZoneRegistry();
    const { space, morphTo, releaseShape } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    render(
      <WellZone
        statusStore={status}
        hudStore={hudStore}
        themeStore={theme}
        registry={registry}
        spaceRef={spaceRef}
      />,
    );
    const zone = screen.getByTestId("well-zone");
    fireEvent.pointerEnter(zone);
    fireEvent.pointerLeave(zone);
    expect(morphTo).not.toHaveBeenCalled();
    expect(releaseShape).not.toHaveBeenCalled();
  });

  it("spaceRef.current 为 null（场景未就绪）→ hover 不抛错（静默跳过）", () => {
    const { store: status } = makeFakeStatusStore();
    const { store: theme } = makeFakeThemeStore();
    const { registry } = makeFakeZoneRegistry();
    const spaceRef = makeSpaceRef(null);
    render(
      <WellZone
        statusStore={status}
        hudStore={hudStore}
        themeStore={theme}
        registry={registry}
        spaceRef={spaceRef}
      />,
    );
    const zone = screen.getByTestId("well-zone");
    expect(() => {
      fireEvent.pointerEnter(zone);
      fireEvent.pointerLeave(zone);
    }).not.toThrow();
  });

  it("hover 进出循环 → morphTo / releaseShape 交替调用（每次进出各一次）", () => {
    const { store: status } = makeFakeStatusStore();
    const { store: theme } = makeFakeThemeStore();
    const { registry } = makeFakeZoneRegistry();
    const { space, morphTo, releaseShape } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    render(
      <WellZone
        statusStore={status}
        hudStore={hudStore}
        themeStore={theme}
        registry={registry}
        spaceRef={spaceRef}
      />,
    );
    const zone = screen.getByTestId("well-zone");
    fireEvent.pointerEnter(zone);
    fireEvent.pointerLeave(zone);
    fireEvent.pointerEnter(zone);
    fireEvent.pointerLeave(zone);
    expect(morphTo).toHaveBeenCalledTimes(2);
    expect(releaseShape).toHaveBeenCalledTimes(2);
  });
});
