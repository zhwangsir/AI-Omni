/**
 * zoneRegistry 运行时单例（M7.4）：注入真实 setInteractiveZones 作为 sink。
 * 独立成模块便于组件测试经 vi.mock 整体替换——真实 IPC 不进入 jsdom 测试。
 */
import { setInteractiveZones } from "../lib/window";
import { createZoneRegistry, type ZoneRegistry } from "./zoneRegistry";

let singleton: ZoneRegistry | null = null;

export function getZoneRegistry(): ZoneRegistry {
  singleton ??= createZoneRegistry({ sink: (zones) => void setInteractiveZones(zones) });
  return singleton;
}
