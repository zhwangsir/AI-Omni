/**
 * identityStore 测试。
 *
 * 覆盖：默认身份值 / loadIdentity 默认值行为 / getAssistantLabel / getIdleLabel。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_IDENTITY,
  getAssistantLabel,
  getIdleLabel,
  identityStore,
  loadIdentity,
} from "./identityStore";

describe("identityStore", () => {
  beforeEach(() => {
    identityStore.setState({ identity: DEFAULT_IDENTITY, loaded: false });
  });

  it("默认身份值正确：display_name=\"雪莉\"", () => {
    const state = identityStore.getState();
    expect(state.identity.display_name).toBe("雪莉");
    expect(state.identity.english_name).toBe("Sherry");
    expect(state.identity.wake_aliases).toEqual(["雪莉", "sherry"]);
    expect(state.identity.wake_response).toBe("我在");
    expect(state.identity.idle_label).toBe("雪莉 · 待命");
    expect(state.loaded).toBe(false);
  });

  it("loadIdentity 无 invoke 时使用默认值", async () => {
    await loadIdentity(undefined);
    const state = identityStore.getState();
    expect(state.loaded).toBe(true);
    expect(state.identity.display_name).toBe("雪莉");
    expect(state.identity.idle_label).toBe("雪莉 · 待命");
  });

  it("loadIdentity invoke 返回 ok 时合并身份数据", async () => {
    const fakeInvoke = vi.fn().mockResolvedValue({
      ok: true,
      data: {
        display_name: "测试助手",
        idle_label: "测试助手 · 待命",
      },
    });

    await loadIdentity(fakeInvoke);
    const state = identityStore.getState();
    expect(state.loaded).toBe(true);
    expect(state.identity.display_name).toBe("测试助手");
    expect(state.identity.idle_label).toBe("测试助手 · 待命");
    expect(state.identity.english_name).toBe("Sherry");
    expect(fakeInvoke).toHaveBeenCalledWith("get_assistant_identity");
  });

  it("loadIdentity invoke 返回非 ok 时使用默认值", async () => {
    const fakeInvoke = vi.fn().mockResolvedValue({
      ok: false,
      error: { code: "E_NOT_FOUND", message: "not found" },
    });

    await loadIdentity(fakeInvoke);
    const state = identityStore.getState();
    expect(state.loaded).toBe(true);
    expect(state.identity.display_name).toBe("雪莉");
  });

  it("loadIdentity invoke 抛异常时使用默认值", async () => {
    const fakeInvoke = vi.fn().mockRejectedValue(new Error("IPC failed"));

    await loadIdentity(fakeInvoke);
    const state = identityStore.getState();
    expect(state.loaded).toBe(true);
    expect(state.identity.display_name).toBe("雪莉");
  });

  it("loadIdentity 幂等：已 loaded 后不重复调用 invoke", async () => {
    const fakeInvoke = vi.fn().mockResolvedValue({
      ok: true,
      data: { display_name: "第一次" },
    });

    await loadIdentity(fakeInvoke);
    expect(fakeInvoke).toHaveBeenCalledTimes(1);

    const fakeInvoke2 = vi.fn().mockResolvedValue({
      ok: true,
      data: { display_name: "第二次" },
    });
    await loadIdentity(fakeInvoke2);
    expect(fakeInvoke2).not.toHaveBeenCalled();
    expect(identityStore.getState().identity.display_name).toBe("第一次");
  });

  it("getAssistantLabel 返回 \"用户\"/\"雪莉\"", () => {
    expect(getAssistantLabel("user")).toBe("用户");
    expect(getAssistantLabel("assistant")).toBe("雪莉");
  });

  it("getAssistantLabel 动态反映身份更新", async () => {
    expect(getAssistantLabel("assistant")).toBe("雪莉");

    identityStore.setState({
      identity: { ...DEFAULT_IDENTITY, display_name: "新名字" },
      loaded: true,
    });

    expect(getAssistantLabel("assistant")).toBe("新名字");
  });

  it("getIdleLabel 返回 \"雪莉 · 待命\"", () => {
    expect(getIdleLabel()).toBe("雪莉 · 待命");
  });

  it("subscribe 通知状态变化", () => {
    const listener = vi.fn();
    const unsub = identityStore.subscribe(listener);

    identityStore.setState({ loaded: true });
    expect(listener).toHaveBeenCalledTimes(1);

    unsub();
    identityStore.setState({ loaded: false });
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
