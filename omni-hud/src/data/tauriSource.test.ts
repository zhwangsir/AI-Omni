import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));

import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

import { createTauriSource } from "./tauriSource";
import { EMPTY_HOME_SUMMARY, EMPTY_SYSTEM_STATS, EMPTY_VOICE_STATUS, VOICE_STATUS_EVENT } from "./sources";

const mockInvoke = vi.mocked(invoke);
const mockListen = vi.mocked(listen);

function stubTauriRuntime(present: boolean): void {
  const w = window as unknown as Record<string, unknown>;
  if (present) {
    w.__TAURI_INTERNALS__ = {};
  } else {
    delete w.__TAURI_INTERNALS__;
  }
}

describe("Tauri IPC 数据源", () => {
  beforeEach(() => {
    mockInvoke.mockReset();
    mockListen.mockReset();
    stubTauriRuntime(true);
  });

  it("非 Tauri 环境全部降级为 unavailable，且不下发任何 command", async () => {
    stubTauriRuntime(false);
    const source = createTauriSource();
    await expect(source.voiceStatus()).resolves.toEqual(EMPTY_VOICE_STATUS);
    await expect(source.homeSummary()).resolves.toEqual(EMPTY_HOME_SUMMARY);
    await expect(source.systemStats()).resolves.toEqual(EMPTY_SYSTEM_STATS);
    expect(mockInvoke).not.toHaveBeenCalled();
  });

  it("voiceStatus 经 get_voice_status 拉取并做类型化映射", async () => {
    mockInvoke.mockResolvedValue({
      available: true,
      state: "speaking",
      running: true,
      fakeMode: true,
    });
    const status = await createTauriSource().voiceStatus();
    expect(mockInvoke).toHaveBeenCalledWith("get_voice_status");
    expect(status).toEqual({
      available: true,
      state: "speaking",
      running: true,
      fakeMode: true,
      reply: null,
      replySeq: null,
      windowMode: null,
      toolCalls: null,
    });
  });

  it("voiceStatus 收到未知管道状态时 state 归 null 但整体仍可用", async () => {
    mockInvoke.mockResolvedValue({
      available: true,
      state: "dancing",
      running: true,
      fakeMode: false,
    });
    const status = await createTauriSource().voiceStatus();
    expect(status.available).toBe(true);
    expect(status.state).toBeNull();
    expect(status.running).toBe(true);
  });

  it("voiceStatus 透传 reply（M6.3：speaking 边沿携带本轮回复文本）", async () => {
    mockInvoke.mockResolvedValue({
      available: true,
      state: "speaking",
      running: true,
      fakeMode: true,
      reply: "客厅灯已打开",
    });
    const status = await createTauriSource().voiceStatus();
    expect(status.reply).toBe("客厅灯已打开");
  });

  it("voiceStatus 的 reply 缺省或非字符串时归 null（兼容未升级的旧版 Rust）", async () => {
    mockInvoke.mockResolvedValue({ available: true, state: "idle", running: true, fakeMode: false });
    const missing = await createTauriSource().voiceStatus();
    expect(missing.reply).toBeNull();

    mockInvoke.mockResolvedValue({
      available: true,
      state: "idle",
      running: true,
      fakeMode: false,
      reply: 42,
    });
    const wrongType = await createTauriSource().voiceStatus();
    expect(wrongType.reply).toBeNull();
  });

  it("voiceStatus 透传 replySeq（M6.3 修复：回复轮次序号，非负整数）", async () => {
    mockInvoke.mockResolvedValue({
      available: true,
      state: "speaking",
      running: true,
      fakeMode: true,
      reply: "客厅灯已打开",
      replySeq: 3,
    });
    const status = await createTauriSource().voiceStatus();
    expect(status.replySeq).toBe(3);
  });

  it("voiceStatus 的 replySeq 缺省或非法（字符串/负数/小数/布尔）时归 null", async () => {
    const base = { available: true, state: "idle", running: true, fakeMode: false };

    mockInvoke.mockResolvedValue(base); // 缺省（旧版 Rust 未升级）
    expect((await createTauriSource().voiceStatus()).replySeq).toBeNull();

    mockInvoke.mockResolvedValue({ ...base, replySeq: "3" }); // 字符串
    expect((await createTauriSource().voiceStatus()).replySeq).toBeNull();

    mockInvoke.mockResolvedValue({ ...base, replySeq: -1 }); // 负数
    expect((await createTauriSource().voiceStatus()).replySeq).toBeNull();

    mockInvoke.mockResolvedValue({ ...base, replySeq: 1.5 }); // 小数
    expect((await createTauriSource().voiceStatus()).replySeq).toBeNull();

    mockInvoke.mockResolvedValue({ ...base, replySeq: true }); // 布尔
    expect((await createTauriSource().voiceStatus()).replySeq).toBeNull();
  });

  it("voiceStatus 透传 windowMode（M12：mini/full 形态切换）", async () => {
    mockInvoke.mockResolvedValue({
      available: true,
      state: "idle",
      running: false,
      fakeMode: false,
      windowMode: "mini",
    });
    const status = await createTauriSource().voiceStatus();
    expect(status.windowMode).toBe("mini");
  });

  it("voiceStatus 的 windowMode 缺省或非法时归 null（前端按 full 缺省）", async () => {
    const base = { available: true, state: "idle", running: true, fakeMode: false };
    mockInvoke.mockResolvedValue(base); // 缺省（旧版 Rust/Python 未升级）
    expect((await createTauriSource().voiceStatus()).windowMode).toBeNull();

    mockInvoke.mockResolvedValue({ ...base, windowMode: "unknown" }); // 非法值
    expect((await createTauriSource().voiceStatus()).windowMode).toBeNull();

    mockInvoke.mockResolvedValue({ ...base, windowMode: 42 }); // 非字符串
    expect((await createTauriSource().voiceStatus()).windowMode).toBeNull();
  });

  // ---- M13.2 toolCalls 透传（Agent 可视化） ---------------------------------

  it("voiceStatus 透传 toolCalls（M13.2：工具调用列表，camelCase 字段）", async () => {
    mockInvoke.mockResolvedValue({
      available: true,
      state: "tool_using",
      running: true,
      fakeMode: false,
      toolCalls: [
        {
          id: "seq1",
          toolName: "home_control_light",
          params: { room: "客厅" },
          result: null,
          status: "pending",
          timestamp: 1784662800.5,
        },
      ],
    });
    const status = await createTauriSource().voiceStatus();
    expect(status.toolCalls).not.toBeNull();
    expect(status.toolCalls).toHaveLength(1);
    const call = status.toolCalls![0];
    expect(call.id).toBe("seq1");
    expect(call.toolName).toBe("home_control_light");
    expect(call.params).toEqual({ room: "客厅" });
    expect(call.result).toBeNull();
    expect(call.status).toBe("pending");
    expect(call.timestamp).toBe(1784662800.5);
  });

  it("voiceStatus 的 toolCalls 缺省时归 null（旧版 Rust 兼容）", async () => {
    mockInvoke.mockResolvedValue({ available: true, state: "speaking", running: true, fakeMode: false });
    const status = await createTauriSource().voiceStatus();
    expect(status.toolCalls).toBeNull();
  });

  it("voiceStatus 的 toolCalls 为空数组时保留为 []（本轮工具链已结束）", async () => {
    mockInvoke.mockResolvedValue({
      available: true,
      state: "speaking",
      running: true,
      fakeMode: false,
      toolCalls: [],
    });
    const status = await createTauriSource().voiceStatus();
    expect(status.toolCalls).toEqual([]);
  });

  it("voiceStatus 的 toolCalls 非数组时归 null（容错降级）", async () => {
    const base = { available: true, state: "idle", running: true, fakeMode: false };
    for (const bad of ["string", 42, true, { x: 1 }]) {
      mockInvoke.mockResolvedValue({ ...base, toolCalls: bad });
      expect((await createTauriSource().voiceStatus()).toolCalls).toBeNull();
    }
  });

  it("voiceStatus 的 toolCalls 数组中非法元素被过滤，仅保留合法元素", async () => {
    mockInvoke.mockResolvedValue({
      available: true,
      state: "tool_using",
      running: true,
      fakeMode: false,
      toolCalls: [
        { id: "ok1", toolName: "good", params: {}, result: "done", status: "success", timestamp: 1.0 },
        {},
        { id: "x" },
        "string",
        42,
        null,
        { id: "ok2", toolName: "good2", params: { x: 1 }, result: null, status: "pending", timestamp: 2.0 },
        { id: "bad", toolName: "y", params: {}, result: null, status: "bogus", timestamp: 1.0 },
        { id: "bad2", toolName: "y", params: [], result: null, status: "pending", timestamp: 1.0 },
        { id: "bad3", toolName: "y", params: {}, result: null, status: "pending", timestamp: "not num" },
      ],
    });
    const status = await createTauriSource().voiceStatus();
    expect(status.toolCalls).not.toBeNull();
    expect(status.toolCalls).toHaveLength(2);
    expect(status.toolCalls![0].id).toBe("ok1");
    expect(status.toolCalls![0].status).toBe("success");
    expect(status.toolCalls![1].id).toBe("ok2");
    expect(status.toolCalls![1].status).toBe("pending");
  });

  it("voiceStatus 收到 Rust 降级负载（available:false）时原样返回空态", async () => {
    mockInvoke.mockResolvedValue({ available: false, state: null, running: false, fakeMode: false });
    const status = await createTauriSource().voiceStatus();
    expect(status).toEqual(EMPTY_VOICE_STATUS);
  });

  it("invoke 抛错 / 返回畸形负载时降级为 unavailable 空态", async () => {
    mockInvoke.mockRejectedValueOnce(new Error("command not found"));
    await expect(createTauriSource().voiceStatus()).resolves.toEqual(EMPTY_VOICE_STATUS);

    mockInvoke.mockResolvedValueOnce("not-an-object");
    await expect(createTauriSource().voiceStatus()).resolves.toEqual(EMPTY_VOICE_STATUS);
  });

  it("homeSummary 经 get_home_summary 拉取，房间/设备/统计与 demo 标记完整映射", async () => {
    mockInvoke.mockResolvedValue({
      available: true,
      demo: true,
      rooms: [
        {
          name: "客厅",
          devices: [
            { name: "客厅灯", stateText: "开启" },
            { name: "客厅空调", stateText: "制冷中（设定 26°C）" },
          ],
        },
        { name: "卧室", devices: [{ name: "卧室灯", stateText: "关闭" }] },
      ],
      stats: { devices: 14, rooms: 3 },
    });
    const summary = await createTauriSource().homeSummary();
    expect(mockInvoke).toHaveBeenCalledWith("get_home_summary");
    expect(summary.available).toBe(true);
    expect(summary.demo).toBe(true);
    expect(summary.rooms).toHaveLength(2);
    expect(summary.rooms[0]?.devices[0]).toEqual({ name: "客厅灯", stateText: "开启" });
    expect(summary.stats).toEqual({ devices: 14, rooms: 3 });
  });

  it("homeSummary 负载缺字段时按空态兜底，不抛错", async () => {
    mockInvoke.mockResolvedValue({ available: true });
    const summary = await createTauriSource().homeSummary();
    expect(summary).toEqual({ available: true, demo: false, rooms: [], stats: null });
  });

  it("systemStats 经 get_system_stats 拉取 CPU/内存/网络数值", async () => {
    mockInvoke.mockResolvedValue({
      available: true,
      cpuPercent: 42.5,
      memoryUsedBytes: 8_589_934_592,
      memoryTotalBytes: 17_179_869_184,
      networkRxBytesPerSec: 1024,
      networkTxBytesPerSec: 2048,
    });
    const stats = await createTauriSource().systemStats();
    expect(mockInvoke).toHaveBeenCalledWith("get_system_stats");
    expect(stats.cpuPercent).toBeCloseTo(42.5);
    expect(stats.memoryUsedBytes).toBe(8_589_934_592);
    expect(stats.networkTxBytesPerSec).toBe(2048);
  });

  it("systemStats 数值缺失或类型错误时降级为 unavailable 空态", async () => {
    mockInvoke.mockResolvedValue({ available: true, cpuPercent: "high" });
    await expect(createTauriSource().systemStats()).resolves.toEqual(EMPTY_SYSTEM_STATS);
  });
});

describe("Tauri 事件订阅（voice-status 推送，M5.4）", () => {
  beforeEach(() => {
    mockInvoke.mockReset();
    mockListen.mockReset();
    stubTauriRuntime(true);
  });

  type EventHandler = (event: { payload: unknown }) => void;

  /** 捕获 listen 注册的回调，返回手动触发器与 unlisten mock。 */
  function captureHandler(): { fire: EventHandler; unlisten: ReturnType<typeof vi.fn> } {
    const unlisten = vi.fn();
    let handler: EventHandler | null = null;
    mockListen.mockImplementation((_event, cb) => {
      handler = cb as EventHandler;
      return Promise.resolve(unlisten);
    });
    return {
      unlisten,
      fire: (event) => handler?.(event),
    };
  }

  it("非 Tauri 环境返回 noop 退订，不注册任何监听", () => {
    stubTauriRuntime(false);
    const source = createTauriSource();
    const unsubscribe = source.subscribe?.(vi.fn());
    expect(mockListen).not.toHaveBeenCalled();
    expect(typeof unsubscribe).toBe("function");
    expect(() => unsubscribe?.()).not.toThrow();
  });

  it("Tauri 环境经 listen 订阅 voice-status，事件负载归一化后送达", async () => {
    const { fire } = captureHandler();
    const listener = vi.fn();
    createTauriSource().subscribe?.(listener);
    await vi.waitFor(() => expect(mockListen).toHaveBeenCalledWith(VOICE_STATUS_EVENT, expect.any(Function)));

    fire({ payload: { available: true, state: "speaking", running: true, fakeMode: true } });
    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith({
      type: VOICE_STATUS_EVENT,
      payload: { available: true, state: "speaking", running: true, fakeMode: true, reply: null, replySeq: null, windowMode: null, toolCalls: null },
    });
  });

  it("voice-status 事件透传 reply（M6.3：speaking 携带本轮回复）", async () => {
    const { fire } = captureHandler();
    const listener = vi.fn();
    createTauriSource().subscribe?.(listener);
    await vi.waitFor(() => expect(mockListen).toHaveBeenCalled());

    fire({
      payload: { available: true, state: "speaking", running: true, fakeMode: true, reply: "本轮回复" },
    });
    expect(listener).toHaveBeenCalledWith({
      type: VOICE_STATUS_EVENT,
      payload: {
        available: true,
        state: "speaking",
        running: true,
        fakeMode: true,
        reply: "本轮回复",
        replySeq: null,
        windowMode: null,
        toolCalls: null,
      },
    });
  });

  it("畸形事件负载归一化为 unavailable 空态，不抛错", async () => {
    const { fire } = captureHandler();
    const listener = vi.fn();
    createTauriSource().subscribe?.(listener);
    await vi.waitFor(() => expect(mockListen).toHaveBeenCalled());

    fire({ payload: "garbage" });
    fire({ payload: { available: true, state: "dancing", running: 1 } });
    expect(listener).toHaveBeenCalledTimes(2);
    expect(listener).toHaveBeenNthCalledWith(1, { type: VOICE_STATUS_EVENT, payload: EMPTY_VOICE_STATUS });
    // state 无法识别归 null、running 非布尔归 false，但 available:true 保留
    expect(listener).toHaveBeenNthCalledWith(2, {
      type: VOICE_STATUS_EVENT,
      payload: { available: true, state: null, running: false, fakeMode: false, reply: null, replySeq: null, windowMode: null, toolCalls: null },
    });
  });

  it("退订函数调用 listen 返回的 unlisten", async () => {
    const { unlisten } = captureHandler();
    const source = createTauriSource();
    const unsubscribe = source.subscribe?.(vi.fn());
    await vi.waitFor(() => expect(mockListen).toHaveBeenCalled());

    unsubscribe?.();
    await vi.waitFor(() => expect(unlisten).toHaveBeenCalledTimes(1));
  });

  it("listen 尚未 resolve 即退订：resolve 后立即反注册，不留悬挂监听", async () => {
    const unlisten = vi.fn();
    let resolveListen: (u: () => void) => void = () => {};
    mockListen.mockImplementation(
      () =>
        new Promise<() => void>((resolve) => {
          resolveListen = resolve;
        }),
    );
    const source = createTauriSource();
    const unsubscribe = source.subscribe?.(vi.fn());

    unsubscribe?.(); // listen promise 仍 pending
    resolveListen(unlisten); // 之后 resolve → 必须立刻 unlisten
    await vi.waitFor(() => expect(unlisten).toHaveBeenCalledTimes(1));
  });

  it("listen 拒绝（watcher 未启动等）时静默降级，不抛错", async () => {
    mockListen.mockRejectedValue(new Error("event channel down"));
    const source = createTauriSource();
    const unsubscribe = source.subscribe?.(vi.fn());
    expect(typeof unsubscribe).toBe("function");
    // 给被拒绝的 promise 一个 settle 的机会；期间不得抛出未处理异常
    await Promise.resolve();
    expect(() => unsubscribe?.()).not.toThrow();
  });
});
