import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

import { invoke } from "@tauri-apps/api/core";

import { isTauri, setAlwaysOnTop, setClickThrough, setInteractiveZones } from "../lib/window";

const mockInvoke = vi.mocked(invoke);

function stubTauriRuntime(present: boolean): void {
  const w = window as unknown as Record<string, unknown>;
  if (present) {
    w.__TAURI_INTERNALS__ = {};
  } else {
    delete w.__TAURI_INTERNALS__;
  }
}

describe("Tauri 窗口桥接", () => {
  beforeEach(() => {
    mockInvoke.mockReset();
  });

  it("Tauri 环境下 setClickThrough(true) 下发 set_click_through ignore:true", async () => {
    stubTauriRuntime(true);
    await setClickThrough(true);
    expect(mockInvoke).toHaveBeenCalledTimes(1);
    expect(mockInvoke).toHaveBeenCalledWith("set_click_through", { ignore: true });
  });

  it("setClickThrough(false) 关闭穿透", async () => {
    stubTauriRuntime(true);
    await setClickThrough(false);
    expect(mockInvoke).toHaveBeenCalledWith("set_click_through", { ignore: false });
  });

  it("setAlwaysOnTop 下发 set_always_on_top", async () => {
    stubTauriRuntime(true);
    await setAlwaysOnTop(false);
    expect(mockInvoke).toHaveBeenCalledWith("set_always_on_top", { flag: false });
  });

  it("非 Tauri 环境（纯浏览器）静默降级：不抛错、不下发 command", async () => {
    stubTauriRuntime(false);
    await expect(setClickThrough(true)).resolves.toBeUndefined();
    await expect(setAlwaysOnTop(true)).resolves.toBeUndefined();
    expect(mockInvoke).not.toHaveBeenCalled();
  });

  it("Tauri 环境下 setInteractiveZones 下发 set_interactive_zones（窗口坐标系矩形）", async () => {
    stubTauriRuntime(true);
    const zones = [
      { x: 800, y: 900, width: 320, height: 180 },
      { x: 0, y: 0, width: 100, height: 100 },
    ];
    await setInteractiveZones(zones);
    expect(mockInvoke).toHaveBeenCalledTimes(1);
    expect(mockInvoke).toHaveBeenCalledWith("set_interactive_zones", { zones });
  });

  it("setInteractiveZones 空数组 = 全穿透（休眠态只留声井由调用侧表达）", async () => {
    stubTauriRuntime(true);
    await setInteractiveZones([]);
    expect(mockInvoke).toHaveBeenCalledWith("set_interactive_zones", { zones: [] });
  });

  it("非 Tauri 环境 setInteractiveZones 静默降级", async () => {
    stubTauriRuntime(false);
    await expect(
      setInteractiveZones([{ x: 0, y: 0, width: 10, height: 10 }]),
    ).resolves.toBeUndefined();
    expect(mockInvoke).not.toHaveBeenCalled();
  });

  it("isTauri 反映运行时标记", () => {
    stubTauriRuntime(true);
    expect(isTauri()).toBe(true);
    stubTauriRuntime(false);
    expect(isTauri()).toBe(false);
  });
});
