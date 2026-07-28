/**
 * FieldStage 组件测试（M7.3 TDD 红）：
 * - 订阅 statusStore.voice.state + hudStore.reducedMotion → resolveFieldState → 引擎参数注入；
 * - 进入 wake_listening/recording 触发一次声井 addRipple（状态未变不重复）；
 * - speaking 渲染底部流线 canvas；idle 不渲染；
 * - reducedMotion 静态降级：无波纹、无流线、setField 推 reduced 参数；
 * - 卸载清理：无报错、流线动画帧取消。
 * 全部 mock：Space 句柄 vi.fn，不碰真实 WebGL。
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EMPTY_HOME_SUMMARY, EMPTY_SYSTEM_STATS, EMPTY_VOICE_STATUS } from "../data/sources";
import { WELL_POSITION } from "../field/fieldState";
import type { Space } from "../space/createSpace";
import { createHudStore, type HudStore } from "../store/hudStore";
import type { StatusState, StatusStore } from "../store/statusStore";

import { FieldStage } from "./FieldStage";

/** 可控 fake StatusStore：仅实现 FieldStage 消费的契约面。 */
function makeFakeStatusStore(initialState: StatusState["voice"]["state"]): {
  store: StatusStore;
  setVoice(state: StatusState["voice"]["state"]): void;
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

/** fake Space：捕获 setField / addRipple 调用供断言。 */
function makeFakeSpace(): {
  space: Space;
  setField: ReturnType<typeof vi.fn>;
  addRipple: ReturnType<typeof vi.fn>;
} {
  const setField = vi.fn();
  const addRipple = vi.fn(() => true);
  const space = {
    setField,
    addRipple,
  } as unknown as Space;
  return { space, setField, addRipple };
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

describe("FieldStage 引擎参数注入", () => {
  it("挂载即推送当前 voice.state 的场参数（null → idle 等价 dim=0.8）", () => {
    const { store } = makeFakeStatusStore(null);
    const { space, setField } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    render(
      <FieldStage spaceRef={spaceRef} statusStore={store} hudStore={hudStore} />,
    );
    expect(setField).toHaveBeenCalledTimes(1);
    const params = setField.mock.calls[0]![0];
    expect(params.dimFactor).toBe(0.8);
    expect(params.attractor).toBeNull();
    expect(params.orbit).toBeNull();
    expect(params.flowline).toBeNull();
    expect(params.ripple).toBeNull();
  });

  it("voice.state 变 speaking → setField 推送 speaking 参数（满亮 + flowline + 强闪烁/辉光）", () => {
    const { store, setVoice } = makeFakeStatusStore(null);
    const { space, setField } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    render(
      <FieldStage spaceRef={spaceRef} statusStore={store} hudStore={hudStore} />,
    );
    setField.mockClear();
    setVoice("speaking");
    expect(setField).toHaveBeenCalledTimes(1);
    const params = setField.mock.calls[0]![0];
    expect(params.dimFactor).toBe(1);
    expect(params.particleShape).toBe("sphere");
    expect(params.flowline).not.toBeNull();
    expect(params.flickerIntensity).toBeGreaterThan(0.3);
    expect(params.flickerSpeed).toBeGreaterThan(2);
    expect(params.glowBoost).toBeGreaterThan(0.1);
  });

  it("voice.state 变 thinking/transcribing → setField 推送思考球体参数（柔和闪烁 + 无轨道/倾向）", () => {
    const { store, setVoice } = makeFakeStatusStore(null);
    const { space, setField } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    render(
      <FieldStage spaceRef={spaceRef} statusStore={store} hudStore={hudStore} />,
    );
    setField.mockClear();
    setVoice("thinking");
    const params = setField.mock.calls[0]![0];
    expect(params.particleShape).toBe("sphere");
    expect(params.helixRotSpeed).toBe(0);
    expect(params.pulseStrength).toBe(0);
    expect(params.flickerIntensity).toBeGreaterThan(0.1);
    expect(params.flickerSpeed).toBeGreaterThan(0.8);
    expect(params.orbit).toBeNull();
    expect(params.attractor).toBeNull();
  });

  it("状态未变化时不重复推送 setField（去重）", () => {
    const { store, setVoice } = makeFakeStatusStore("idle");
    const { space, setField } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    render(
      <FieldStage spaceRef={spaceRef} statusStore={store} hudStore={hudStore} />,
    );
    setField.mockClear();
    setVoice("idle"); // 同值
    expect(setField).not.toHaveBeenCalled();
  });
});

describe("FieldStage 声井波纹触发（进入聆听态一次性）", () => {
  it("进入 wake_listening 触发一次 addRipple（声井位置 + 慢速时长）", () => {
    const { store, setVoice } = makeFakeStatusStore(null);
    const { space, addRipple } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    render(
      <FieldStage spaceRef={spaceRef} statusStore={store} hudStore={hudStore} />,
    );
    setVoice("wake_listening");
    expect(addRipple).toHaveBeenCalledTimes(1);
    const arg = addRipple.mock.calls[0]![0];
    expect(arg.x).toBe(WELL_POSITION.x);
    expect(arg.y).toBe(WELL_POSITION.y);
    expect(arg.z).toBe(WELL_POSITION.z);
    expect(arg.durationMs).toBeGreaterThan(0);
  });

  it("进入 recording 也触发一次 addRipple", () => {
    const { store, setVoice } = makeFakeStatusStore(null);
    const { space, addRipple } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    render(
      <FieldStage spaceRef={spaceRef} statusStore={store} hudStore={hudStore} />,
    );
    setVoice("recording");
    expect(addRipple).toHaveBeenCalledTimes(1);
  });

  it("wake_listening 持续期间不重复触发 addRipple（状态未变）", () => {
    const { store, setVoice } = makeFakeStatusStore("wake_listening");
    const { space, addRipple } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    render(
      <FieldStage spaceRef={spaceRef} statusStore={store} hudStore={hudStore} />,
    );
    addRipple.mockClear();
    setVoice("wake_listening"); // 同值
    expect(addRipple).not.toHaveBeenCalled();
  });

  it("从 wake_listening 切到 recording 再触发一次（状态变化的进入边）", () => {
    const { store, setVoice } = makeFakeStatusStore("wake_listening");
    const { space, addRipple } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    render(
      <FieldStage spaceRef={spaceRef} statusStore={store} hudStore={hudStore} />,
    );
    addRipple.mockClear();
    setVoice("recording");
    expect(addRipple).toHaveBeenCalledTimes(1);
  });

  it("从 recording 切到 idle 不触发 addRipple（idle 无波纹）", () => {
    const { store, setVoice } = makeFakeStatusStore("recording");
    const { space, addRipple } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    render(
      <FieldStage spaceRef={spaceRef} statusStore={store} hudStore={hudStore} />,
    );
    addRipple.mockClear();
    setVoice("idle");
    expect(addRipple).not.toHaveBeenCalled();
  });
});

describe("FieldStage speaking 底部流线", () => {
  it("speaking 时渲染流线 canvas（data-testid=field-flowline）", () => {
    const { store, setVoice } = makeFakeStatusStore(null);
    const { space } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    render(
      <FieldStage spaceRef={spaceRef} statusStore={store} hudStore={hudStore} />,
    );
    expect(screen.queryByTestId("field-flowline")).toBeNull();
    setVoice("speaking");
    expect(screen.getByTestId("field-flowline")).toBeInTheDocument();
  });

  it("从 speaking 切回 idle 流线 canvas 卸载", () => {
    const { store, setVoice } = makeFakeStatusStore("speaking");
    const { space } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    render(
      <FieldStage spaceRef={spaceRef} statusStore={store} hudStore={hudStore} />,
    );
    expect(screen.getByTestId("field-flowline")).toBeInTheDocument();
    setVoice("idle");
    expect(screen.queryByTestId("field-flowline")).toBeNull();
  });

  it("流线层不拦截指针、aria-hidden（不遮挡字幕与交互）", () => {
    const { store } = makeFakeStatusStore("speaking");
    const { space } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    render(
      <FieldStage spaceRef={spaceRef} statusStore={store} hudStore={hudStore} />,
    );
    const canvas = screen.getByTestId("field-flowline");
    expect(canvas.style.pointerEvents).toBe("none");
    expect(canvas).toHaveAttribute("aria-hidden", "true");
  });
});

describe("FieldStage reducedMotion 静态降级", () => {
  it("reducedMotion=true 时进入 wake_listening 不触发 addRipple", () => {
    const { store, setVoice } = makeFakeStatusStore(null);
    const { space, addRipple } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    hudStore.setReducedMotion(true);
    render(
      <FieldStage spaceRef={spaceRef} statusStore={store} hudStore={hudStore} />,
    );
    setVoice("wake_listening");
    expect(addRipple).not.toHaveBeenCalled();
  });

  it("reducedMotion=true 时 speaking 不渲染流线 canvas", () => {
    const { store, setVoice } = makeFakeStatusStore(null);
    const { space } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    hudStore.setReducedMotion(true);
    render(
      <FieldStage spaceRef={spaceRef} statusStore={store} hudStore={hudStore} />,
    );
    setVoice("speaking");
    expect(screen.queryByTestId("field-flowline")).toBeNull();
  });

  it("reducedMotion 切换时 setField 推送 reduced 参数（无附属行为）", () => {
    const { store } = makeFakeStatusStore("wake_listening");
    const { space, setField } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    render(
      <FieldStage spaceRef={spaceRef} statusStore={store} hudStore={hudStore} />,
    );
    setField.mockClear();
    hudStore.setReducedMotion(true);
    expect(setField).toHaveBeenCalled();
    const params = setField.mock.calls.at(-1)![0];
    expect(params.ripple).toBeNull();
    expect(params.attractor).toBeNull();
    expect(params.orbit).toBeNull();
    expect(params.flowline).toBeNull();
  });
});

describe("FieldStage 卸载清理", () => {
  it("卸载时不抛错且无悬挂引用（流线动画帧取消）", () => {
    const { store } = makeFakeStatusStore("speaking");
    const { space } = makeFakeSpace();
    const spaceRef = makeSpaceRef(space);
    const { unmount } = render(
      <FieldStage spaceRef={spaceRef} statusStore={store} hudStore={hudStore} />,
    );
    expect(() => unmount()).not.toThrow();
  });

  it("spaceRef 为 null（场景未就绪）时挂载不抛错", () => {
    const { store } = makeFakeStatusStore(null);
    const spaceRef = makeSpaceRef(null);
    expect(() =>
      render(
        <FieldStage spaceRef={spaceRef} statusStore={store} hudStore={hudStore} />,
      ),
    ).not.toThrow();
  });

  it("spaceRef 为 null 时进入 wake_listening 静默跳过 addRipple（不抛错）", () => {
    const { store, setVoice } = makeFakeStatusStore(null);
    const spaceRef = makeSpaceRef(null);
    render(
      <FieldStage spaceRef={spaceRef} statusStore={store} hudStore={hudStore} />,
    );
    expect(() => setVoice("wake_listening")).not.toThrow();
  });
});
