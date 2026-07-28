/**
 * HUD 布局骨架测试（M7.2 重写）：显影场四槽位。
 * 角色系统（Live2D / OpenTalking / StatusBar / ThemeSwitcher）已退役，
 * 布局锚点改为 ImmersiveSpace + FieldStage / CaptionLayer / WellZone 空壳。
 * createSpace / runtime / statusRuntime 全部 mock，不碰 WebGL / IPC / 定时器。
 *
 * M7.3/M7.4 填充后槽位不再是空壳：FieldStage 仍 aria-hidden（背景层），
 * CaptionLayer / WellZone 转为可交互内容层。原"空壳"断言收缩为只校验
 * FieldStage 的背景层语义（aria-hidden + idle 无文本）。
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// ResizeObserver polyfill（M7.4 useRegisteredZone 依赖，jsdom 不提供）。
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
(globalThis as unknown as { ResizeObserver: typeof ResizeObserverStub }).ResizeObserver =
  ResizeObserverStub;

// M4.3：状态轮询运行时含真实定时器与 IPC，布局测试整体替换为静止桩 store——
// start/stop 空操作、状态恒为全离线，不引入异步更新。
vi.mock("../store/statusRuntime", async () => {
  const { EMPTY_HOME_SUMMARY, EMPTY_SYSTEM_STATS, EMPTY_VOICE_STATUS } = await import(
    "../data/sources"
  );
  const state = {
    voice: EMPTY_VOICE_STATUS,
    home: EMPTY_HOME_SUMMARY,
    system: EMPTY_SYSTEM_STATS,
    failures: { voice: 0, home: 0, system: 0 },
    running: false,
    paused: false,
  };
  return {
    getStatusStore: () => ({
      getState: () => state,
      subscribe: () => () => {},
      start: () => {},
      stop: () => {},
      pause: () => {},
      resume: () => {},
    }),
  };
});

// M7.4：subtitleStore / zoneRegistryRuntime 经运行时单例注入真实定时器与 IPC，
// 布局测试替换为静止桩——字幕恒不可见、registry 空操作。
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

// M5.1：粒子背景层为 3D 沉浸空间（ImmersiveSpace 懒加载 three 运行时）。
// 布局测试以静止桩替换 createSpace / runtime，不触碰真实 WebGL。
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

import { App } from "../App";

describe("HUD 显影场骨架（M7.2）", () => {
  it("App 渲染 3D 沉浸空间 + 场语义 / 字幕 / 声井三槽位", () => {
    render(<App />);
    expect(screen.getByTestId("hud-root")).toBeInTheDocument();
    expect(screen.getByTestId("immersive-space")).toBeInTheDocument();
    expect(screen.getByTestId("field-stage")).toBeInTheDocument();
    expect(screen.getByTestId("caption-layer")).toBeInTheDocument();
    expect(screen.getByTestId("well-zone")).toBeInTheDocument();
  });

  it("3D 空间层不拦截指针，且在 DOM 顺序上位于内容层之下", () => {
    render(<App />);
    const root = screen.getByTestId("hud-root");
    const space = screen.getByTestId("immersive-space");
    const content = document.querySelector(".hud-content") as HTMLElement;
    expect(space.style.pointerEvents).toBe("none");
    expect(root.children[0]).toBe(space);
    expect(root.children[1]).toBe(content);
  });

  it("hud-root 不再有 data-interaction（窗口级穿透状态机退役，穿透归 Rust 分区轮询）", () => {
    render(<App />);
    expect(screen.getByTestId("hud-root")).not.toHaveAttribute("data-interaction");
  });

  it("FieldStage 背景层 aria-hidden 且 idle 无可见文本（M7.3 语义：场退至桌面之后）", () => {
    render(<App />);
    // M7.3/M7.4 填充后，CaptionLayer / WellZone 转为可交互内容层（非 aria-hidden）；
    // 仅 FieldStage 作为背景场语义层保留 aria-hidden + idle 状态无文本。
    const fieldStage = screen.getByTestId("field-stage");
    expect(fieldStage).toHaveAttribute("aria-hidden", "true");
    expect(fieldStage.textContent).toBe("");
  });

  it("布局中不出现 emoji（图标全部经 Icon.tsx / lucide 渲染为 svg）", () => {
    const { container } = render(<App />);
    const text = container.textContent ?? "";
    // 匹配常见 emoji 区段
    expect(text).not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u);
  });
});
