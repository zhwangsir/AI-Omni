/**
 * 交互分区协调器（M7.4）：多组件共享 setInteractiveZones 的统一入口。
 *
 * 背景与方案：setInteractiveZones 是覆盖式 API（接收完整 zones 列表），
 * 但 WellZone / CaptionLayer 等组件各自只知自身 Rect——若各组件直接调
 * setInteractiveZones 会互相覆盖。故引入本 store：组件 mount/unmount 时
 * registerZone(id, rect) / unregisterZone(id)，store 内部按 id 维护一个
 * 有序 Map，合并出完整列表后统一下发。
 *
 * 与 statusStore / themeStore 同款框架无关订阅模式；sink 注入便于测试
 * 替换为 mock（生产环境由 zoneRegistryRuntime 注入 setInteractiveZones）。
 * null rect 表示「槽位保留但不贡献分区」（如休眠态 WellZone 仅留井心点击区
 * 但暂未测量到几何时的占位）——不进入合并列表，但保留 id 以便后续覆盖注册。
 *
 * 幂等：同 id 同 Rect 不重复下发；Rect → null / null → Rect / Rect → Rect
 *（不同值）均视为变化触发下发。初始化不主动下发，由首个注册驱动。
 */
import type { InteractiveZone } from "../lib/window";

export interface ZoneRegistryDeps {
  /** 下发函数（生产环境为 setInteractiveZones）；缺省时仅维护状态不下发。 */
  readonly sink?: (zones: readonly InteractiveZone[]) => void;
}

export interface ZoneRegistry {
  /** 当前所有非 null 分区按注册顺序合并的列表（只读快照）。 */
  getZones: () => InteractiveZone[];
  subscribe: (listener: () => void) => () => void;
  /**
   * 注册或更新某 id 的分区。null = 槽位保留但不贡献分区。
   * 同 id 同 Rect 幂等不下发；任何实质变化触发完整列表下发。
   */
  registerZone: (id: string, rect: InteractiveZone | null) => void;
  /** 注销某 id；未知 id 幂等不抛错、不下发。 */
  unregisterZone: (id: string) => void;
}

function zonesEqual(a: InteractiveZone | null, b: InteractiveZone | null): boolean {
  if (a === null && b === null) return true;
  if (a === null || b === null) return false;
  return a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height;
}

export function createZoneRegistry(deps?: ZoneRegistryDeps): ZoneRegistry {
  const sink = deps?.sink;
  // 用 Map 而非 Record：保留插入顺序，zones 列表稳定便于断言与 IPC 去重。
  const slots = new Map<string, InteractiveZone | null>();
  const listeners = new Set<() => void>();

  const emit = (): void => {
    for (const listener of listeners) listener();
  };

  const flush = (): void => {
    if (sink === undefined) return;
    const zones: InteractiveZone[] = [];
    for (const rect of slots.values()) {
      if (rect !== null) zones.push(rect);
    }
    sink(zones);
  };

  return {
    getZones() {
      const zones: InteractiveZone[] = [];
      for (const rect of slots.values()) {
        if (rect !== null) zones.push(rect);
      }
      return zones;
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    registerZone(id, rect) {
      const prev = slots.get(id) ?? null;
      if (zonesEqual(prev, rect)) {
        // 同值幂等：但若是新 id（prev undefined）且 rect 为 null，不视作变化
        if (!slots.has(id) && rect === null) return;
        // 同 id 同 Rect 不下发
        return;
      }
      slots.set(id, rect);
      flush();
      emit();
    },
    unregisterZone(id) {
      if (!slots.delete(id)) return; // 未知 id 幂等
      flush();
      emit();
    },
  };
}
