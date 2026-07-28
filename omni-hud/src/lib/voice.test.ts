/**
 * voice 桥接测试（M7.4）：interruptSpeaking() 封装 Tauri voice_interrupt command。
 * 沿用 window.test.ts 的 mock invoke 模式；非 Tauri 环境静默降级为 no-op。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

import { invoke } from "@tauri-apps/api/core";

import { CMD_VOICE_INTERRUPT, interruptSpeaking } from "./voice";
import { isTauri } from "./window";

const mockInvoke = vi.mocked(invoke);

function stubTauriRuntime(present: boolean): void {
  const w = window as unknown as Record<string, unknown>;
  if (present) {
    w.__TAURI_INTERNALS__ = {};
  } else {
    delete w.__TAURI_INTERNALS__;
  }
}

describe("interruptSpeaking 桥接", () => {
  beforeEach(() => {
    mockInvoke.mockReset();
  });

  it("Tauri 环境下下发 voice_interrupt command（无参数）", async () => {
    stubTauriRuntime(true);
    await interruptSpeaking();
    expect(mockInvoke).toHaveBeenCalledTimes(1);
    expect(mockInvoke).toHaveBeenCalledWith(CMD_VOICE_INTERRUPT);
  });

  it("invoke 抛错时静默降级：不向调用方抛错", async () => {
    stubTauriRuntime(true);
    mockInvoke.mockRejectedValueOnce(new Error("IPC closed"));
    await expect(interruptSpeaking()).resolves.toBeUndefined();
    expect(mockInvoke).toHaveBeenCalledTimes(1);
  });

  it("非 Tauri 环境静默降级：不调用 invoke、不抛错", async () => {
    stubTauriRuntime(false);
    await expect(interruptSpeaking()).resolves.toBeUndefined();
    expect(mockInvoke).not.toHaveBeenCalled();
  });

  it("CMD_VOICE_INTERRUPT 与 Rust command 名对齐", () => {
    expect(CMD_VOICE_INTERRUPT).toBe("voice_interrupt");
  });

  it("isTauri 桥接沿用 window.ts 同源判定（不重复实现）", () => {
    stubTauriRuntime(true);
    expect(isTauri()).toBe(true);
    stubTauriRuntime(false);
    expect(isTauri()).toBe(false);
  });
});
