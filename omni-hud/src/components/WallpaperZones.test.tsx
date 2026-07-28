/**
 * WallpaperZones 测试（M22.3 TDD）：壁纸模式专属交互分区注册。
 *
 * 验证：
 * - 壁纸模式挂载时注册 3 个分区（右下控制条 / 左边缘 / 右边缘）；
 * - 非壁纸模式（full / mini）不挂载、不注册；
 * - 双击唤醒区在壁纸模式可触发 onWake 回调；
 * - 分区几何随窗口尺寸自适应（ResizeObserver 驱动）。
 */
import { act, render, screen, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WallpaperZones } from "./WallpaperZones";
import type { InteractiveZone } from "../lib/window";
import type { ZoneRegistry } from "../store/zoneRegistry";

// ResizeObserver polyfill（useRegisteredZone 依赖）。
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
(globalThis as unknown as { ResizeObserver: typeof ResizeObserverStub }).ResizeObserver =
  ResizeObserverStub;

function makeFakeZoneRegistry(): {
  registry: ZoneRegistry;
  registerZone: ReturnType<typeof vi.fn>;
  unregisterZone: ReturnType<typeof vi.fn>;
  getZonesSnapshot: () => InteractiveZone[];
} {
  const slots = new Map<string, InteractiveZone | null>();
  const registerZone = vi.fn((id: string, rect: InteractiveZone | null) => {
    slots.set(id, rect);
  });
  const unregisterZone = vi.fn((id: string) => {
    slots.delete(id);
  });
  const getZonesSnapshot = () => {
    const zones: InteractiveZone[] = [];
    for (const rect of slots.values()) {
      if (rect !== null) zones.push(rect);
    }
    return zones;
  };
  const registry = {
    getZones: getZonesSnapshot,
    subscribe: () => () => {},
    registerZone,
    unregisterZone,
  } as unknown as ZoneRegistry;
  return { registry, registerZone, unregisterZone, getZonesSnapshot };
}

describe("WallpaperZones 分区注册（M22.3）", () => {
  beforeEach(() => {
    // getBoundingClientRect 桩：返回非零几何，让 useRegisteredZone 能注册有效分区。
    Element.prototype.getBoundingClientRect = vi.fn(() => ({
      x: 0,
      y: 0,
      width: 100,
      height: 100,
      top: 0,
      left: 0,
      right: 100,
      bottom: 100,
      toJSON: () => ({}),
    })) as never;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("wallpaperMode=true 时挂载 3 个分区（control-bar / left-edge / right-edge）", () => {
    const { registry, registerZone } = makeFakeZoneRegistry();
    render(
      <WallpaperZones
        wallpaperMode={true}
        registry={registry}
        onWake={() => {}}
      />,
    );
    // 3 个分区注册调用
    expect(registerZone).toHaveBeenCalledWith(
      "wallpaper-control-bar",
      expect.objectContaining({ x: expect.any(Number), y: expect.any(Number) }),
    );
    expect(registerZone).toHaveBeenCalledWith(
      "wallpaper-left-edge",
      expect.objectContaining({ x: expect.any(Number) }),
    );
    expect(registerZone).toHaveBeenCalledWith(
      "wallpaper-right-edge",
      expect.objectContaining({ x: expect.any(Number) }),
    );
  });

  it("wallpaperMode=false 时不注册任何分区", () => {
    const { registry, registerZone } = makeFakeZoneRegistry();
    render(
      <WallpaperZones
        wallpaperMode={false}
        registry={registry}
        onWake={() => {}}
      />,
    );
    expect(registerZone).not.toHaveBeenCalled();
  });

  it("卸载时注销所有已注册分区", () => {
    const { registry, unregisterZone } = makeFakeZoneRegistry();
    const { unmount } = render(
      <WallpaperZones
        wallpaperMode={true}
        registry={registry}
        onWake={() => {}}
      />,
    );
    unmount();
    expect(unregisterZone).toHaveBeenCalledWith("wallpaper-control-bar");
    expect(unregisterZone).toHaveBeenCalledWith("wallpaper-left-edge");
    expect(unregisterZone).toHaveBeenCalledWith("wallpaper-right-edge");
  });

  it("wallpaperMode 从 true→false 时注销全部分区", () => {
    const { registry, unregisterZone } = makeFakeZoneRegistry();
    const { rerender } = render(
      <WallpaperZones
        wallpaperMode={true}
        registry={registry}
        onWake={() => {}}
      />,
    );
    rerender(
      <WallpaperZones
        wallpaperMode={false}
        registry={registry}
        onWake={() => {}}
      />,
    );
    expect(unregisterZone).toHaveBeenCalledWith("wallpaper-control-bar");
    expect(unregisterZone).toHaveBeenCalledWith("wallpaper-left-edge");
    expect(unregisterZone).toHaveBeenCalledWith("wallpaper-right-edge");
  });
});

describe("WallpaperZones 双击唤醒（M22.3）", () => {
  beforeEach(() => {
    Element.prototype.getBoundingClientRect = vi.fn(() => ({
      x: 0,
      y: 0,
      width: 1920,
      height: 1080,
      top: 0,
      left: 0,
      right: 1920,
      bottom: 1080,
      toJSON: () => ({}),
    })) as never;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("wallpaperMode=true 时双击唤醒区触发 onWake 回调", () => {
    const { registry } = makeFakeZoneRegistry();
    const onWake = vi.fn();
    render(
      <WallpaperZones
        wallpaperMode={true}
        registry={registry}
        onWake={onWake}
      />,
    );
    const wakeZone = screen.getByTestId("wallpaper-wake-zone");
    act(() => {
      fireEvent.doubleClick(wakeZone);
    });
    expect(onWake).toHaveBeenCalledTimes(1);
  });

  it("wallpaperMode=false 时不渲染唤醒区（不响应双击）", () => {
    const { registry } = makeFakeZoneRegistry();
    const onWake = vi.fn();
    render(
      <WallpaperZones
        wallpaperMode={false}
        registry={registry}
        onWake={onWake}
      />,
    );
    expect(screen.queryByTestId("wallpaper-wake-zone")).toBeNull();
  });
});

describe("WallpaperZones 控制条交互（M22.3）", () => {
  beforeEach(() => {
    Element.prototype.getBoundingClientRect = vi.fn(() => ({
      x: 0,
      y: 0,
      width: 240,
      height: 60,
      top: 0,
      left: 0,
      right: 240,
      bottom: 60,
      toJSON: () => ({}),
    })) as never;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("wallpaperMode=true 时渲染控制条（含壁纸模式退出按钮）", () => {
    const { registry } = makeFakeZoneRegistry();
    render(
      <WallpaperZones
        wallpaperMode={true}
        registry={registry}
        onWake={() => {}}
      />,
    );
    expect(screen.getByTestId("wallpaper-control-bar")).toBeInTheDocument();
    expect(screen.getByTestId("wallpaper-exit-button")).toBeInTheDocument();
  });

  it("点击退出按钮触发 onExitWallpaper 回调", () => {
    const { registry } = makeFakeZoneRegistry();
    const onExitWallpaper = vi.fn();
    render(
      <WallpaperZones
        wallpaperMode={true}
        registry={registry}
        onWake={() => {}}
        onExitWallpaper={onExitWallpaper}
      />,
    );
    const exitBtn = screen.getByTestId("wallpaper-exit-button");
    act(() => {
      fireEvent.click(exitBtn);
    });
    expect(onExitWallpaper).toHaveBeenCalledTimes(1);
  });
});
