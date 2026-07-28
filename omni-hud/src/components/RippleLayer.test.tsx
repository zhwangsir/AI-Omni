/**
 * RippleLayer / useRipples 测试（M4.4）。
 * 点击内容区从点击中心扩散多层同心圆；到期自动清除；
 * reducedMotion 下完全不产生波纹；波纹层不拦截指针。
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// jsdom 未实现 PointerEvent 构造器，用 MouseEvent 携带 pointerdown 类型派发，
// React 按事件类型名分发，效果等价。
function pointerDown(target: Element, clientX: number, clientY: number): void {
  act(() => {
    target.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, clientX, clientY }));
  });
}

import { RIPPLE_DURATION_MS, RIPPLE_LAYER_STAGGER_MS, RIPPLE_LAYERS } from "../ripple/ripple";
import { RippleLayer, useRipples } from "./RippleLayer";

function Host({ reducedMotion = false }: { reducedMotion?: boolean }) {
  const { ripples, spawnRipple } = useRipples(reducedMotion);
  return (
    <div
      data-testid="host"
      onPointerDown={(e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        spawnRipple(e.clientX - rect.left, e.clientY - rect.top);
      }}
    >
      <RippleLayer ripples={ripples} />
    </div>
  );
}

describe("RippleLayer 水波纹", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("点击后从点击位置生成波纹，包含多层同心圆", () => {
    render(<Host />);
    const host = screen.getByTestId("host");
    pointerDown(host, 40, 24);
    const ripple = screen.getByTestId("ripple-layer").querySelector("[data-ripple]");
    expect(ripple).not.toBeNull();
    const rings = ripple!.querySelectorAll("[data-ripple-ring]");
    expect(rings).toHaveLength(RIPPLE_LAYERS);
    // 波纹中心定位在点击处
    const first = rings[0] as HTMLElement;
    expect(first.style.left).toBe("40px");
    expect(first.style.top).toBe("24px");
  });

  it("多层同心圆错峰启动（animationDelay 递增）", () => {
    render(<Host />);
    pointerDown(screen.getByTestId("host"), 10, 10);
    const rings = screen
      .getByTestId("ripple-layer")
      .querySelectorAll<HTMLElement>("[data-ripple-ring]");
    const delays = [...rings].map((r) => parseFloat(r.style.animationDelay || "0"));
    expect(delays[0]).toBe(0);
    expect(delays[1]).toBeCloseTo(RIPPLE_LAYER_STAGGER_MS / 1000);
  });

  it("波纹扩散结束后自动从 DOM 清除", () => {
    render(<Host />);
    pointerDown(screen.getByTestId("host"), 10, 10);
    expect(screen.getByTestId("ripple-layer").querySelector("[data-ripple]")).not.toBeNull();
    act(() => {
      vi.advanceTimersByTime(RIPPLE_DURATION_MS + RIPPLE_LAYER_STAGGER_MS * RIPPLE_LAYERS + 200);
    });
    expect(screen.getByTestId("ripple-layer").querySelector("[data-ripple]")).toBeNull();
  });

  it("reducedMotion 下点击不产生任何波纹（动画纪律降级）", () => {
    render(<Host reducedMotion />);
    pointerDown(screen.getByTestId("host"), 10, 10);
    expect(screen.getByTestId("ripple-layer").querySelector("[data-ripple]")).toBeNull();
  });

  it("波纹层不拦截指针、不对辅助技术暴露", () => {
    render(<Host />);
    const layer = screen.getByTestId("ripple-layer");
    expect(layer.style.pointerEvents).toBe("none");
    expect(layer).toHaveAttribute("aria-hidden", "true");
  });

  it("连续点击生成多个并存波纹", () => {
    render(<Host />);
    const host = screen.getByTestId("host");
    pointerDown(host, 10, 10);
    pointerDown(host, 60, 30);
    expect(screen.getByTestId("ripple-layer").querySelectorAll("[data-ripple]")).toHaveLength(2);
  });
});
