/**
 * 状态轮询运行时单例（M4.3）：Tauri IPC 数据源 + 默认轮询节奏。
 * 独立成模块便于渲染测试经 vi.mock 整体替换——
 * 真实定时器与 IPC 不进入 jsdom 组件测试。
 */
import { createTauriSource } from "../data/tauriSource";
import { createStatusStore, type StatusStore } from "./statusStore";

let singleton: StatusStore | null = null;

export function getStatusStore(): StatusStore {
  singleton ??= createStatusStore({ source: createTauriSource() });
  return singleton;
}
