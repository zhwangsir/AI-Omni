/**
 * useRegisteredZone（M7.4）：把一个 DOM 元素的 Rect 注册到 zoneRegistry。
 *
 * 组件 mount 后用 useLayoutEffect 测量 ref.current.getBoundingClientRect()，
 * 注册到 registry；ResizeObserver 监听元素几何变化触发重新注册；
 * unmount 时注销。enabled=false 时注销并不再监听（如休眠态 WellZone 仅
 * 留井心点击区，由 WellZone 自行决定何时启用各分区）。
 *
 * 坐标系：getBoundingClientRect 返回的就是窗口逻辑坐标（与 Rust zones
 * 期望的 CSS 逻辑像素一致），无需换算。
 */
import { useLayoutEffect, type RefObject } from "react";

import type { InteractiveZone } from "../lib/window";
import { getZoneRegistry } from "./zoneRegistryRuntime";

export interface UseRegisteredZoneOptions {
  /** 是否启用注册；false 时立即注销并不监听。 */
  enabled?: boolean;
  /** 注入 registry（测试替换）；缺省走运行时单例。 */
  registry?: ReturnType<typeof getZoneRegistry>;
}

function rectFromElement(el: HTMLElement): InteractiveZone {
  const r = el.getBoundingClientRect();
  return { x: r.left, y: r.top, width: r.width, height: r.height };
}

export function useRegisteredZone(
  id: string,
  ref: RefObject<HTMLElement | null>,
  options: UseRegisteredZoneOptions = {},
): void {
  const enabled = options.enabled ?? true;
  const registry = options.registry ?? getZoneRegistry();

  useLayoutEffect(() => {
    if (!enabled) {
      // 切到 disabled：移除自身分区（若此前注册过）
      registry.unregisterZone(id);
      return;
    }
    const el = ref.current;
    if (el === null) return;

    const sync = (): void => {
      const current = ref.current;
      if (current === null) return;
      registry.registerZone(id, rectFromElement(current));
    };
    sync();

    // ResizeObserver 监听几何变化（窗口 resize / 内容布局变化）。
    const observer = new ResizeObserver(() => sync());
    observer.observe(el);

    return () => {
      observer.disconnect();
      registry.unregisterZone(id);
    };
  }, [id, enabled, registry, ref]);
}
