/**
 * interactions 点击交互编排测试（M5.3）：
 * - NDC 换算：中心 / 角落 / y 轴取反 / 非法输入
 * - 点击编排：波纹 + 脉冲 + 形状轮换聚集；保持后缓释；连续点击重置计时；
 *   场景未就绪静默跳过；cancel 取消未触发缓释
 * 全部 fake 依赖注入，不碰 React / three / 真实定时器。
 */
import { describe, expect, it, vi } from "vitest";

import {
  GATHER_HOLD_MS,
  MORPH_CYCLE,
  createClickGather,
  ndcFromClientPoint,
  type InteractionSpace,
} from "./interactions";
import type { ShapeKind } from "./shapes";

function makeSpaceStub() {
  return {
    addRippleAt: vi.fn<(x: number, y: number) => boolean>(() => true),
    pulseAttractor: vi.fn(),
    morphTo: vi.fn<(shape: ShapeKind) => void>(),
    releaseShape: vi.fn(),
  } satisfies InteractionSpace;
}

/** 手动定时器：capture 回调与句柄，测试自行触发。 */
function makeTimers() {
  const callbacks = new Map<number, () => void>();
  let nextHandle = 1;
  const setTimer = vi.fn((callback: () => void, _ms: number): unknown => {
    const handle = nextHandle++;
    callbacks.set(handle, callback);
    return handle;
  });
  const clearTimer = vi.fn((handle: unknown): void => {
    callbacks.delete(handle as number);
  });
  const fire = (handle: number): void => {
    callbacks.get(handle)?.();
    callbacks.delete(handle);
  };
  const lastHandle = (): number => nextHandle - 1;
  return { setTimer, clearTimer, fire, lastHandle };
}

describe("ndcFromClientPoint 像素 → NDC 换算", () => {
  it("视口中心映射为原点 (0, 0)", () => {
    expect(ndcFromClientPoint(190, 280, 380, 560)).toEqual({ x: 0, y: 0 });
  });

  it("角落映射：左上 (-1, 1)、右下 (1, -1)（y 轴屏幕向下取反）", () => {
    expect(ndcFromClientPoint(0, 0, 380, 560)).toEqual({ x: -1, y: 1 });
    expect(ndcFromClientPoint(380, 560, 380, 560)).toEqual({ x: 1, y: -1 });
  });

  it("一般点线性映射且 y 取反", () => {
    const p = ndcFromClientPoint(95, 140, 380, 560);
    expect(p.x).toBeCloseTo(-0.5, 6);
    expect(p.y).toBeCloseTo(0.5, 6);
  });

  it("非法视口尺寸（0 / 负 / 非有限）抛 RangeError", () => {
    expect(() => ndcFromClientPoint(0, 0, 0, 560)).toThrow(RangeError);
    expect(() => ndcFromClientPoint(0, 0, 380, -1)).toThrow(RangeError);
    expect(() => ndcFromClientPoint(0, 0, Number.NaN, 560)).toThrow(RangeError);
  });

  it("非有限指针坐标抛 RangeError", () => {
    expect(() => ndcFromClientPoint(Number.NaN, 0, 380, 560)).toThrow(RangeError);
    expect(() => ndcFromClientPoint(0, Number.POSITIVE_INFINITY, 380, 560)).toThrow(RangeError);
  });
});

describe("createClickGather 点击编排", () => {
  it("场景未就绪（null）时静默跳过：不调度缓释、不抛错", () => {
    const timers = makeTimers();
    const gather = createClickGather({
      getSpace: () => null,
      setTimer: timers.setTimer,
      clearTimer: timers.clearTimer,
    });
    expect(() => gather.click(0, 0)).not.toThrow();
    expect(timers.setTimer).not.toHaveBeenCalled();
  });

  it("点击触发波纹 + 脉冲 + 首个形状聚集，并按 holdMs 调度缓释", () => {
    const space = makeSpaceStub();
    const timers = makeTimers();
    const gather = createClickGather({
      getSpace: () => space,
      setTimer: timers.setTimer,
      clearTimer: timers.clearTimer,
    });
    gather.click(0.25, -0.5);
    expect(space.addRippleAt).toHaveBeenCalledWith(0.25, -0.5);
    expect(space.pulseAttractor).toHaveBeenCalledTimes(1);
    expect(space.morphTo).toHaveBeenCalledWith(MORPH_CYCLE[0]);
    expect(timers.setTimer).toHaveBeenCalledWith(expect.any(Function), GATHER_HOLD_MS);
  });

  it("形状按 MORPH_CYCLE 轮换（sphere → ring → helix → dna_helix → sphere）", () => {
    const space = makeSpaceStub();
    const timers = makeTimers();
    const gather = createClickGather({
      getSpace: () => space,
      setTimer: timers.setTimer,
      clearTimer: timers.clearTimer,
    });
    for (let i = 0; i < 5; i++) gather.click(0, 0);
    expect(space.morphTo.mock.calls.map((c) => c[0])).toEqual([
      "sphere",
      "ring",
      "helix",
      "dna_helix",
      "sphere",
    ]);
  });

  it("缓释计时触发后调用 releaseShape（取最新场景实例）", () => {
    const spaceA = makeSpaceStub();
    const spaceB = makeSpaceStub();
    let current: InteractionSpace | null = spaceA;
    const timers = makeTimers();
    const gather = createClickGather({
      getSpace: () => current,
      setTimer: timers.setTimer,
      clearTimer: timers.clearTimer,
    });
    gather.click(0, 0);
    current = spaceB; // 场景实例已更换（如画质档重建）
    timers.fire(timers.lastHandle());
    expect(spaceA.releaseShape).not.toHaveBeenCalled();
    expect(spaceB.releaseShape).toHaveBeenCalledTimes(1);
  });

  it("连续点击重置缓释计时：旧定时器被清除，仅最后一次生效", () => {
    const space = makeSpaceStub();
    const timers = makeTimers();
    const gather = createClickGather({
      getSpace: () => space,
      setTimer: timers.setTimer,
      clearTimer: timers.clearTimer,
    });
    gather.click(0, 0);
    const first = timers.lastHandle();
    gather.click(0.1, 0.1);
    const second = timers.lastHandle();
    expect(timers.clearTimer).toHaveBeenCalledWith(first);
    expect(second).not.toBe(first);
    timers.fire(second);
    expect(space.releaseShape).toHaveBeenCalledTimes(1);
  });

  it("cancel 清除未触发的缓释（卸载后不再触碰场景）", () => {
    const space = makeSpaceStub();
    const timers = makeTimers();
    const gather = createClickGather({
      getSpace: () => space,
      setTimer: timers.setTimer,
      clearTimer: timers.clearTimer,
    });
    gather.click(0, 0);
    const handle = timers.lastHandle();
    gather.cancel();
    expect(timers.clearTimer).toHaveBeenCalledWith(handle);
    // 取消后即使回调被误触发路径已不存在：定时器表已清空
    timers.fire(handle);
    expect(space.releaseShape).not.toHaveBeenCalled();
  });

  it("非法 holdMs（非正 / 非有限）抛 RangeError", () => {
    const timers = makeTimers();
    expect(() =>
      createClickGather({
        getSpace: () => null,
        setTimer: timers.setTimer,
        clearTimer: timers.clearTimer,
        holdMs: 0,
      }),
    ).toThrow(RangeError);
  });
});
