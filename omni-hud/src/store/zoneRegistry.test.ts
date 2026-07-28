/**
 * zoneRegistry 测试（M7.4）：交互分区协调器。
 * 多个组件（WellZone / CaptionLayer）各自 register/unregister 自身 Rect，
 * store 合并后统一下发 setInteractiveZones（覆盖式，非增量）。
 * 全 fake：setInteractiveZones 注入 mock，不触碰 Tauri IPC。
 */
import { describe, expect, it, vi } from "vitest";

import type { InteractiveZone } from "../lib/window";
import { createZoneRegistry } from "./zoneRegistry";

const ZONE_A: InteractiveZone = { x: 0, y: 0, width: 100, height: 100 };
const ZONE_B: InteractiveZone = { x: 800, y: 900, width: 320, height: 180 };

describe("zoneRegistry 交互分区协调器", () => {
  it("初始为空：无组件注册时不下发，但首次订阅可触发一次空下发（同步 IPC 状态）", () => {
    const sink = vi.fn();
    const registry = createZoneRegistry({ sink });
    expect(registry.getZones()).toEqual([]);
    // 初始化不主动下发——避免无组件时反复 IPC；由首个注册驱动下发
    expect(sink).not.toHaveBeenCalled();
  });

  it("registerZone 把分区加入并下发完整列表", () => {
    const sink = vi.fn();
    const registry = createZoneRegistry({ sink });
    registry.registerZone("well", ZONE_B);
    expect(registry.getZones()).toEqual([ZONE_B]);
    expect(sink).toHaveBeenCalledWith([ZONE_B]);
    expect(sink).toHaveBeenCalledTimes(1);
  });

  it("多个组件注册：合并后一次性下发完整列表（非增量）", () => {
    const sink = vi.fn();
    const registry = createZoneRegistry({ sink });
    registry.registerZone("well", ZONE_B);
    registry.registerZone("caption", ZONE_A);
    expect(registry.getZones()).toEqual([ZONE_B, ZONE_A]);
    // 第二次注册触发第二次下发，参数是合并后的完整列表
    expect(sink).toHaveBeenLastCalledWith([ZONE_B, ZONE_A]);
    expect(sink).toHaveBeenCalledTimes(2);
  });

  it("registerZone 同 id 覆盖旧 Rect（rect 变化时更新）", () => {
    const sink = vi.fn();
    const registry = createZoneRegistry({ sink });
    registry.registerZone("well", ZONE_B);
    const next: InteractiveZone = { x: 810, y: 910, width: 320, height: 180 };
    registry.registerZone("well", next);
    expect(registry.getZones()).toEqual([next]);
    expect(sink).toHaveBeenLastCalledWith([next]);
  });

  it("registerZone 同 id 同 Rect 不重复下发（幂等）", () => {
    const sink = vi.fn();
    const registry = createZoneRegistry({ sink });
    registry.registerZone("well", ZONE_B);
    registry.registerZone("well", ZONE_B);
    expect(sink).toHaveBeenCalledTimes(1);
  });

  it("unregisterZone 移除分区并下发更新后的列表", () => {
    const sink = vi.fn();
    const registry = createZoneRegistry({ sink });
    registry.registerZone("well", ZONE_B);
    registry.registerZone("caption", ZONE_A);
    sink.mockClear();
    registry.unregisterZone("well");
    expect(registry.getZones()).toEqual([ZONE_A]);
    expect(sink).toHaveBeenCalledWith([ZONE_A]);
  });

  it("unregisterZone 未知 id 不抛错、不下发（幂等）", () => {
    const sink = vi.fn();
    const registry = createZoneRegistry({ sink });
    registry.unregisterZone("nonexistent");
    expect(sink).not.toHaveBeenCalled();
    expect(registry.getZones()).toEqual([]);
  });

  it("registerZone 接收 null = 槽位保留但不贡献分区（休眠态占位）", () => {
    const sink = vi.fn();
    const registry = createZoneRegistry({ sink });
    registry.registerZone("well", null);
    expect(registry.getZones()).toEqual([]);
    // null 不算变化触发下发——从 null 到 null 幂等；从空到 null 也视作无变化
    expect(sink).not.toHaveBeenCalled();
    // 但后续组件覆盖注册真实 Rect 时正常下发
    registry.registerZone("well", ZONE_B);
    expect(sink).toHaveBeenCalledWith([ZONE_B]);
  });

  it("从 Rect 切到 null 视为变化：下发移除后的列表", () => {
    const sink = vi.fn();
    const registry = createZoneRegistry({ sink });
    registry.registerZone("well", ZONE_B);
    sink.mockClear();
    registry.registerZone("well", null);
    expect(registry.getZones()).toEqual([]);
    expect(sink).toHaveBeenCalledWith([]);
  });

  it("通知订阅者 zones 变化（用于 React useSyncExternalStore）", () => {
    const registry = createZoneRegistry({ sink: () => {} });
    const listener = vi.fn();
    const unsubscribe = registry.subscribe(listener);
    registry.registerZone("well", ZONE_B);
    expect(listener).toHaveBeenCalledTimes(1);
    registry.unregisterZone("well");
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
    registry.registerZone("well", ZONE_B);
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("sink 缺省时仍能维护状态（无 IPC 环境降级，不抛错）", () => {
    const registry = createZoneRegistry();
    registry.registerZone("well", ZONE_B);
    expect(registry.getZones()).toEqual([ZONE_B]);
  });
});
