/**
 * Tauri 窗口桥接：点击穿透与置顶切换的 command 封装。
 * 浏览器环境（无 __TAURI_INTERNALS__）下全部静默降级为 no-op，
 * 保证 vitest / 纯 web 预览不依赖真实 Tauri 运行时。
 */
import { invoke } from "@tauri-apps/api/core";

export const CMD_SET_CLICK_THROUGH = "set_click_through";
export const CMD_SET_ALWAYS_ON_TOP = "set_always_on_top";
export const CMD_SET_INTERACTIVE_ZONES = "set_interactive_zones";

/**
 * 交互分区（M7.1）：窗口坐标系（CSS 逻辑像素）矩形。
 * 与 Rust zones::Rect 字段一一对应（serde 同名反序列化）。
 */
export interface InteractiveZone {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

/** 是否运行在 Tauri 桌面壳内。 */
export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/**
 * 切换点击穿透：ignore = true 时鼠标事件穿透到桌面（HUD 默认行为），
 * false 时 HUD 接收交互（hover 进入交互区）。
 */
export async function setClickThrough(ignore: boolean): Promise<void> {
  if (!isTauri()) return;
  await invoke(CMD_SET_CLICK_THROUGH, { ignore });
}

/** 运行时切换窗口置顶。 */
export async function setAlwaysOnTop(flag: boolean): Promise<void> {
  if (!isTauri()) return;
  await invoke(CMD_SET_ALWAYS_ON_TOP, { flag });
}

/**
 * 下发交互分区（M7.1）：覆盖式更新——Rust 鼠标轮询在光标落入任一分区时
 * 关闭穿透（分区可交互），否则保持穿透。空数组 = 全穿透（默认态）；
 * 休眠态「只留声井」由调用侧下单分区表达，布局语义不落在桥接层。
 */
export async function setInteractiveZones(zones: readonly InteractiveZone[]): Promise<void> {
  if (!isTauri()) return;
  await invoke(CMD_SET_INTERACTIVE_ZONES, { zones: [...zones] });
}
