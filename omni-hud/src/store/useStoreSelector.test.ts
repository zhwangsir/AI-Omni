import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useStoreSelector, type StoreLike } from "./useStoreSelector";
import { createHudStore } from "./hudStore";

describe("useStoreSelector", () => {
  function createCounterStore(): StoreLike<{ count: number; label: string }> & { increment(): void; setLabel(l: string): void } {
    let state = { count: 0, label: "test" };
    const listeners = new Set<() => void>();
    const emit = () => listeners.forEach(l => l());
    return {
      getState: () => state,
      subscribe(l) { listeners.add(l); return () => listeners.delete(l); },
      increment() { state = { ...state, count: state.count + 1 }; emit(); },
      setLabel(l) { if (state.label === l) return; state = { ...state, label: l }; emit(); },
    };
  }

  it("订阅单个字段，初始值正确", () => {
    const store = createCounterStore();
    const { result } = renderHook(() => useStoreSelector(store, s => s.count));
    expect(result.current).toBe(0);
  });

  it("字段变化时触发重渲染，返回新值", () => {
    const store = createCounterStore();
    const { result } = renderHook(() => useStoreSelector(store, s => s.count));
    expect(result.current).toBe(0);
    act(() => store.increment());
    expect(result.current).toBe(1);
  });

  it("未订阅的字段变化时不触发重渲染", () => {
    const store = createCounterStore();
    let renderCount = 0;
    const { result } = renderHook(() => {
      renderCount++;
      return useStoreSelector(store, s => s.count);
    });
    expect(result.current).toBe(0);
    const rendersAfterMount = renderCount;
    act(() => store.setLabel("changed"));
    expect(renderCount).toBe(rendersAfterMount);
    expect(result.current).toBe(0);
  });

  it("selector 返回相同值时不重渲染（Object.is 比较）", () => {
    const store = createHudStore();
    let renderCount = 0;
    renderHook(() => {
      renderCount++;
      return useStoreSelector(store, s => s.reducedMotion);
    });
    const rendersAfterMount = renderCount;
    act(() => store.setReducedMotion(false));
    expect(renderCount).toBe(rendersAfterMount);
  });

  it("自定义 isEqual 支持对象切片比较", () => {
    const store = createHudStore();
    let renderCount = 0;
    const selector = (s: ReturnType<typeof store.getState>) => ({
      reducedMotion: s.reducedMotion,
      sleeping: s.sleeping,
    });
    const isEqual = (a: { reducedMotion: boolean; sleeping: boolean }, b: { reducedMotion: boolean; sleeping: boolean }) =>
      a.reducedMotion === b.reducedMotion && a.sleeping === b.sleeping;
    const { result } = renderHook(() => {
      renderCount++;
      return useStoreSelector(store, selector, isEqual);
    });
    expect(result.current).toEqual({ reducedMotion: false, sleeping: false });
    const rendersAfterMount = renderCount;
    act(() => store.setFieldMode("shelf"));
    expect(renderCount).toBe(rendersAfterMount);
  });
});
