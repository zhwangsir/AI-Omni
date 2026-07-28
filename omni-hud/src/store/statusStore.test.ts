/**
 * statusStore 轮询引擎测试（M4.3）。
 *
 * 全 fake：fake 数据源（依赖注入）+ fake timers，不触碰 Tauri/网络/硬件。
 * 验证点：立即拉取、按间隔轮询、失败线性退避（封顶 5x）、成功重置、
 * pause/resume（窗口隐藏冻结）、stop 丢弃进行中结果、start 幂等。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  EMPTY_HOME_SUMMARY,
  EMPTY_SYSTEM_STATS,
  EMPTY_VOICE_STATUS,
  VOICE_STATUS_EVENT,
  type HomeSummary,
  type HudDataSource,
  type HudSourceEvent,
  type HudSourceEventListener,
  type SystemStats,
  type VoiceStatus,
} from "../data/sources";
import { BACKOFF_MAX_FACTOR, VOICE_EVENT_FALLBACK_INTERVAL, createStatusStore } from "./statusStore";

const VOICE_OK: VoiceStatus = {
  available: true,
  state: "idle",
  running: true,
  fakeMode: true,
  reply: null,
  replySeq: null,
  windowMode: "mini",
  toolCalls: null,
};
const HOME_OK: HomeSummary = {
  available: true,
  demo: true,
  rooms: [{ name: "客厅", devices: [{ name: "客厅灯", stateText: "开启" }] }],
  stats: { devices: 3, rooms: 2 },
};
const SYS_OK: SystemStats = {
  available: true,
  cpuPercent: 12.5,
  memoryUsedBytes: 8_000_000_000,
  memoryTotalBytes: 16_000_000_000,
  networkRxBytesPerSec: 1024,
  networkTxBytesPerSec: 2048,
};

interface FakeSource {
  voiceStatus: ReturnType<typeof vi.fn<() => Promise<VoiceStatus>>>;
  homeSummary: ReturnType<typeof vi.fn<() => Promise<HomeSummary>>>;
  systemStats: ReturnType<typeof vi.fn<() => Promise<SystemStats>>>;
}

function makeSource(overrides?: Partial<{
  voice: () => Promise<VoiceStatus>;
  home: () => Promise<HomeSummary>;
  system: () => Promise<SystemStats>;
}>): FakeSource & HudDataSource {
  return {
    voiceStatus: vi.fn(overrides?.voice ?? (() => Promise.resolve(VOICE_OK))),
    homeSummary: vi.fn(overrides?.home ?? (() => Promise.resolve(HOME_OK))),
    systemStats: vi.fn(overrides?.system ?? (() => Promise.resolve(SYS_OK))),
  };
}

describe("statusStore 轮询引擎", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("start 后立即拉取三个通道并写入状态", async () => {
    const source = makeSource();
    const store = createStatusStore({ source });

    store.start();
    await vi.advanceTimersByTimeAsync(0);

    expect(source.voiceStatus).toHaveBeenCalledTimes(1);
    expect(source.homeSummary).toHaveBeenCalledTimes(1);
    expect(source.systemStats).toHaveBeenCalledTimes(1);

    const state = store.getState();
    expect(state.voice).toEqual(VOICE_OK);
    expect(state.home).toEqual(HOME_OK);
    expect(state.system).toEqual(SYS_OK);
    expect(state.running).toBe(true);
    expect(state.failures).toEqual({ voice: 0, home: 0, system: 0 });

    store.stop();
  });

  it("三个通道按各自间隔轮询", async () => {
    const source = makeSource();
    const store = createStatusStore({
      source,
      intervals: { voice: 1000, system: 2000, home: 5000 },
    });

    store.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(source.voiceStatus).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(1000); // t=1000
    expect(source.voiceStatus).toHaveBeenCalledTimes(2);
    expect(source.systemStats).toHaveBeenCalledTimes(1);
    expect(source.homeSummary).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(1000); // t=2000
    expect(source.voiceStatus).toHaveBeenCalledTimes(3);
    expect(source.systemStats).toHaveBeenCalledTimes(2);
    expect(source.homeSummary).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(3000); // t=5000：voice 0/1/2/3/4/5s 共 6 次
    expect(source.voiceStatus).toHaveBeenCalledTimes(6);
    expect(source.systemStats).toHaveBeenCalledTimes(3); // 0/2/4s
    expect(source.homeSummary).toHaveBeenCalledTimes(2);

    store.stop();
  });

  it("stop 冻结全部定时器，之后不再拉取", async () => {
    const source = makeSource();
    const store = createStatusStore({ source, intervals: { voice: 1000 } });

    store.start();
    await vi.advanceTimersByTimeAsync(1000);
    expect(source.voiceStatus).toHaveBeenCalledTimes(2);

    store.stop();
    expect(store.getState().running).toBe(false);

    await vi.advanceTimersByTimeAsync(60_000);
    expect(source.voiceStatus).toHaveBeenCalledTimes(2);
    expect(source.homeSummary).toHaveBeenCalledTimes(1);
  });

  it("start 幂等：重复调用不叠加定时器", async () => {
    const source = makeSource();
    const store = createStatusStore({ source, intervals: { voice: 1000 } });

    store.start();
    store.start();
    await vi.advanceTimersByTimeAsync(0);
    store.start();

    await vi.advanceTimersByTimeAsync(1000);
    expect(source.voiceStatus).toHaveBeenCalledTimes(2);

    store.stop();
  });

  it("连续失败按 (1+失败数)x 线性退避，封顶 BACKOFF_MAX_FACTOR 倍", async () => {
    expect(BACKOFF_MAX_FACTOR).toBe(5);
    const source = makeSource({ voice: () => Promise.resolve(EMPTY_VOICE_STATUS) });
    const store = createStatusStore({ source, intervals: { voice: 1000 } });

    store.start();
    await vi.advanceTimersByTimeAsync(0); // t=0，第 1 次失败 → 下次 +2000
    expect(source.voiceStatus).toHaveBeenCalledTimes(1);
    expect(store.getState().failures.voice).toBe(1);

    await vi.advanceTimersByTimeAsync(1999);
    expect(source.voiceStatus).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1); // t=2000，第 2 次失败 → +3000
    expect(source.voiceStatus).toHaveBeenCalledTimes(2);
    expect(store.getState().failures.voice).toBe(2);

    await vi.advanceTimersByTimeAsync(2999);
    expect(source.voiceStatus).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1); // t=5000，第 3 次失败 → +4000
    expect(source.voiceStatus).toHaveBeenCalledTimes(3);

    await vi.advanceTimersByTimeAsync(3999);
    expect(source.voiceStatus).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(1); // t=9000，第 4 次失败 → +5000（封顶）
    expect(source.voiceStatus).toHaveBeenCalledTimes(4);

    await vi.advanceTimersByTimeAsync(4999);
    expect(source.voiceStatus).toHaveBeenCalledTimes(4);
    await vi.advanceTimersByTimeAsync(1); // t=14000，第 5 次失败 → 仍 +5000
    expect(source.voiceStatus).toHaveBeenCalledTimes(5);

    await vi.advanceTimersByTimeAsync(4999);
    expect(source.voiceStatus).toHaveBeenCalledTimes(5);
    await vi.advanceTimersByTimeAsync(1); // t=19000
    expect(source.voiceStatus).toHaveBeenCalledTimes(6);

    store.stop();
  });

  it("一次成功后退避重置为基础间隔", async () => {
    const voice = vi
      .fn<() => Promise<VoiceStatus>>()
      .mockResolvedValueOnce(EMPTY_VOICE_STATUS) // t=0 失败 → +2000
      .mockResolvedValue(VOICE_OK);
    const source = makeSource({ voice });
    const store = createStatusStore({ source, intervals: { voice: 1000 } });

    store.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(store.getState().failures.voice).toBe(1);

    await vi.advanceTimersByTimeAsync(2000); // t=2000 成功 → 重置为 +1000
    expect(voice).toHaveBeenCalledTimes(2);
    expect(store.getState().failures.voice).toBe(0);
    expect(store.getState().voice).toEqual(VOICE_OK);

    await vi.advanceTimersByTimeAsync(1000); // t=3000
    expect(voice).toHaveBeenCalledTimes(3);

    store.stop();
  });

  it("pause 冻结轮询，resume 立即补一轮并恢复节奏", async () => {
    const source = makeSource();
    const store = createStatusStore({ source, intervals: { voice: 1000 } });

    store.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(source.voiceStatus).toHaveBeenCalledTimes(1);

    store.pause();
    expect(store.getState().paused).toBe(true);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(source.voiceStatus).toHaveBeenCalledTimes(1);

    store.resume();
    expect(store.getState().paused).toBe(false);
    await vi.advanceTimersByTimeAsync(0); // resume 立即补拉
    expect(source.voiceStatus).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(1000); // 恢复基础节奏
    expect(source.voiceStatus).toHaveBeenCalledTimes(3);

    store.stop();
  });

  it("stop 丢弃进行中的 fetch 结果，不再写入状态", async () => {
    // Promise executor 同步执行，定时器触发后 resolveVoice 必已被赋值；
    // 以 noop 初始化（而非 null）避免 TS 控制流把变量收窄成 null/never。
    let resolveVoice: (value: VoiceStatus) => void = () => {};
    const source = makeSource({
      voice: () =>
        new Promise<VoiceStatus>((resolve) => {
          resolveVoice = resolve;
        }),
    });
    const store = createStatusStore({ source });

    store.start();
    await vi.advanceTimersByTimeAsync(0); // 触发在途 fetch
    expect(source.voiceStatus).toHaveBeenCalledTimes(1);

    store.stop();
    resolveVoice(VOICE_OK); // stop 后才返回
    await vi.advanceTimersByTimeAsync(0);

    expect(store.getState().voice).toEqual(EMPTY_VOICE_STATUS);
  });

  it("数据源抛异常等价于不可用：计入失败并退避，不中断轮询", async () => {
    const source = makeSource({
      voice: () => Promise.reject(new Error("ipc down")),
    });
    const store = createStatusStore({ source, intervals: { voice: 1000 } });

    store.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(store.getState().failures.voice).toBe(1);
    expect(store.getState().voice).toEqual(EMPTY_VOICE_STATUS);

    await vi.advanceTimersByTimeAsync(2000); // 退避后仍在轮询
    expect(source.voiceStatus).toHaveBeenCalledTimes(2);
    expect(store.getState().failures.voice).toBe(2);

    store.stop();
  });

  it("状态写入时通知订阅者", async () => {
    const source = makeSource();
    const store = createStatusStore({ source });
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);

    store.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(listener).toHaveBeenCalled();

    const callsAfterStart = listener.mock.calls.length;
    unsubscribe();
    await vi.advanceTimersByTimeAsync(1000);
    expect(listener).toHaveBeenCalledTimes(callsAfterStart);

    store.stop();
  });

  it("初始状态为全空负载，未 start 前不发起任何请求", async () => {
    const source = makeSource();
    const store = createStatusStore({ source });

    expect(store.getState()).toEqual({
      voice: EMPTY_VOICE_STATUS,
      home: EMPTY_HOME_SUMMARY,
      system: EMPTY_SYSTEM_STATS,
      failures: { voice: 0, home: 0, system: 0 },
      running: false,
      paused: false,
    });

    await vi.advanceTimersByTimeAsync(60_000);
    expect(source.voiceStatus).not.toHaveBeenCalled();
  });
});

/**
 * voice-status 事件驱动（M5.4）：source 提供 subscribe 时，
 * voice 通道改由 Rust 状态文件事件推送驱动，轮询降为低频兜底。
 */
describe("statusStore voice 事件驱动（M5.4）", () => {
  const VOICE_SPEAKING: VoiceStatus = {
    available: true,
    state: "speaking",
    running: true,
    fakeMode: true,
    reply: null,
    replySeq: null,
    windowMode: "full",
    toolCalls: null,
  };

  interface EventSourceHarness {
    source: HudDataSource & FakeSource;
    emitEvent: (event: HudSourceEvent) => void;
    unlisten: ReturnType<typeof vi.fn>;
    subscribeFn: ReturnType<typeof vi.fn<(l: HudSourceEventListener) => () => void>>;
  }

  function makeEventSource(overrides?: Parameters<typeof makeSource>[0]): EventSourceHarness {
    const base = makeSource(overrides);
    const unlisten = vi.fn();
    let captured: HudSourceEventListener | null = null;
    const subscribeFn = vi.fn((listener: HudSourceEventListener) => {
      captured = listener;
      return unlisten;
    });
    return {
      source: { ...base, subscribe: subscribeFn },
      emitEvent: (event) => captured?.(event),
      unlisten,
      subscribeFn,
    };
  }

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("start 时订阅源事件，voice-status 事件直接写状态并通知订阅者", async () => {
    const { source, emitEvent, subscribeFn } = makeEventSource();
    const store = createStatusStore({ source });
    const listener = vi.fn();
    store.subscribe(listener);

    store.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(subscribeFn).toHaveBeenCalledTimes(1);
    expect(store.getState().voice).toEqual(VOICE_OK); // 初始轮询一帧

    const callsBefore = listener.mock.calls.length;
    emitEvent({ type: VOICE_STATUS_EVENT, payload: VOICE_SPEAKING });

    expect(store.getState().voice).toEqual(VOICE_SPEAKING);
    expect(listener.mock.calls.length).toBeGreaterThan(callsBefore);
    store.stop();
  });

  it("事件到达清零 voice 失败计数（事件通道本身健康）", async () => {
    const voice = vi
      .fn<() => Promise<VoiceStatus>>()
      .mockResolvedValueOnce(EMPTY_VOICE_STATUS) // 初始轮询失败 → failures=1
      .mockResolvedValue(VOICE_OK);
    const { source, emitEvent } = makeEventSource({ voice });
    const store = createStatusStore({ source });

    store.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(store.getState().failures.voice).toBe(1);

    emitEvent({ type: VOICE_STATUS_EVENT, payload: VOICE_SPEAKING });
    expect(store.getState().failures.voice).toBe(0);
    expect(store.getState().voice).toEqual(VOICE_SPEAKING);
    store.stop();
  });

  it("事件驱动下 voice 轮询降为兜底间隔，不再按 1s 空转", async () => {
    const { source } = makeEventSource();
    const store = createStatusStore({
      source,
      intervals: { voice: 1000, system: 2000 },
      voiceEventFallbackMs: 5000,
    });

    store.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(source.voiceStatus).toHaveBeenCalledTimes(1); // 初始同步一帧
    expect(source.systemStats).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(1000); // t=1000：旧的 voice 1s 节奏不再生效
    expect(source.voiceStatus).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(1000); // t=2000：system 按自身 2s 节奏走
    expect(source.systemStats).toHaveBeenCalledTimes(2); // system 不受影响
    expect(source.voiceStatus).toHaveBeenCalledTimes(1); // voice 兜底仍未到期

    await vi.advanceTimersByTimeAsync(3000); // t=5000：兜底间隔到期
    expect(source.voiceStatus).toHaveBeenCalledTimes(2);
    store.stop();
  });

  it("默认兜底间隔为 VOICE_EVENT_FALLBACK_INTERVAL", async () => {
    expect(VOICE_EVENT_FALLBACK_INTERVAL).toBe(15_000);
    const { source } = makeEventSource();
    const store = createStatusStore({ source, intervals: { voice: 1000 } });

    store.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(source.voiceStatus).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(14_999);
    expect(source.voiceStatus).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(source.voiceStatus).toHaveBeenCalledTimes(2);
    store.stop();
  });

  it("非 voice 类型事件与畸形负载一律忽略，不写状态", async () => {
    const { source, emitEvent } = makeEventSource();
    const store = createStatusStore({ source });

    store.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(store.getState().voice).toEqual(VOICE_OK);

    emitEvent({ type: "home-summary", payload: VOICE_SPEAKING });
    emitEvent({ type: VOICE_STATUS_EVENT, payload: "garbage" });
    emitEvent({ type: VOICE_STATUS_EVENT, payload: { available: "yes" } });
    emitEvent({ type: VOICE_STATUS_EVENT, payload: null });

    expect(store.getState().voice).toEqual(VOICE_OK);
    store.stop();
  });

  it("pause 期间事件被丢弃，resume 立即补拉一轮", async () => {
    const { source, emitEvent } = makeEventSource();
    const store = createStatusStore({ source, intervals: { voice: 1000 } });

    store.start();
    await vi.advanceTimersByTimeAsync(0);
    store.pause();

    emitEvent({ type: VOICE_STATUS_EVENT, payload: VOICE_SPEAKING });
    expect(store.getState().voice).toEqual(VOICE_OK); // 仍是暂停前的值

    store.resume();
    await vi.advanceTimersByTimeAsync(0);
    expect(source.voiceStatus).toHaveBeenCalledTimes(2); // resume 兜底补帧
    store.stop();
  });

  it("stop 退订事件推送；之后即使 handler 被调用也丢弃", async () => {
    const { source, emitEvent, unlisten } = makeEventSource();
    const store = createStatusStore({ source });

    store.start();
    await vi.advanceTimersByTimeAsync(0);
    store.stop();
    expect(unlisten).toHaveBeenCalledTimes(1);

    emitEvent({ type: VOICE_STATUS_EVENT, payload: VOICE_SPEAKING }); // 防御：迟到事件
    expect(store.getState().voice).toEqual(VOICE_OK);
  });

  it("start 幂等：重复 start 不重复订阅", async () => {
    const { source, subscribeFn } = makeEventSource();
    const store = createStatusStore({ source });

    store.start();
    store.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(subscribeFn).toHaveBeenCalledTimes(1);
    store.stop();
  });

  it("source 不提供 subscribe 时维持原轮询节奏（回归保护）", async () => {
    const source = makeSource();
    const store = createStatusStore({ source, intervals: { voice: 1000 } });

    store.start();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1000);
    expect(source.voiceStatus).toHaveBeenCalledTimes(2); // 1s 节奏不变
    store.stop();
  });
});

/**
 * voice.reply 字段贯通（M6.3）：omni_voice 进入 speaking 时把本轮回复写进
 * 状态文件，Rust watcher 透传，statusStore 原样承载——opentalkingBridge
 * 凭 reply 驱动 OpenTalking 开口。离开 speaking 后 reply 归 null。
 */
describe("statusStore voice.reply 贯通（M6.3）", () => {
  const SPEAKING_WITH_REPLY: VoiceStatus = {
    available: true,
    state: "speaking",
    running: true,
    fakeMode: true,
    reply: "本轮回复文本",
    replySeq: null,
    windowMode: "full",
    toolCalls: null,
  };

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("轮询路径透传 reply（fetcher 结果直写状态）", async () => {
    const source = makeSource({ voice: () => Promise.resolve(SPEAKING_WITH_REPLY) });
    const store = createStatusStore({ source });

    store.start();
    await vi.advanceTimersByTimeAsync(0);

    expect(store.getState().voice).toEqual(SPEAKING_WITH_REPLY);
    expect(store.getState().voice.reply).toBe("本轮回复文本");
    store.stop();
  });

  it("voice-status 事件透传 reply：speaking 携带回复、离开 speaking 归 null", async () => {
    const base = makeSource();
    const unlisten = vi.fn();
    let captured: HudSourceEventListener | null = null;
    const source: HudDataSource = {
      ...base,
      subscribe: (listener) => {
        captured = listener;
        return unlisten;
      },
    };
    // 包进函数体调用：顶层调用点 TS 会把 captured 收窄为 null（闭包赋值不可见）。
    const emitEvent = (event: HudSourceEvent): void => {
      captured?.(event);
    };
    const store = createStatusStore({ source });

    store.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(store.getState().voice.reply).toBeNull(); // VOICE_OK 不带回复

    emitEvent({ type: VOICE_STATUS_EVENT, payload: SPEAKING_WITH_REPLY });
    expect(store.getState().voice.reply).toBe("本轮回复文本");

    emitEvent({ type: VOICE_STATUS_EVENT, payload: VOICE_OK }); // 离开 speaking，无 reply
    expect(store.getState().voice.reply).toBeNull();
    store.stop();
  });

  it("事件负载 reply 类型非法（非 string|null）时整帧丢弃，不写状态", async () => {
    const base = makeSource();
    let captured: HudSourceEventListener | null = null;
    const source: HudDataSource = {
      ...base,
      subscribe: (listener) => {
        captured = listener;
        return () => {};
      },
    };
    const emitEvent = (event: HudSourceEvent): void => {
      captured?.(event);
    };
    const store = createStatusStore({ source });

    store.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(store.getState().voice).toEqual(VOICE_OK);

    // 防御：IPC 边界漏归一化的畸形负载（reply: 123）不得污染 store。
    emitEvent({
      type: VOICE_STATUS_EVENT,
      payload: { ...SPEAKING_WITH_REPLY, reply: 123 } as unknown as VoiceStatus,
    });
    expect(store.getState().voice).toEqual(VOICE_OK);
    store.stop();
  });

  it("事件负载 replySeq 类型非法（非 number|null）时整帧丢弃，不写状态", async () => {
    const base = makeSource();
    let captured: HudSourceEventListener | null = null;
    const source: HudDataSource = {
      ...base,
      subscribe: (listener) => {
        captured = listener;
        return () => {};
      },
    };
    const emitEvent = (event: HudSourceEvent): void => {
      captured?.(event);
    };
    const store = createStatusStore({ source });

    store.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(store.getState().voice).toEqual(VOICE_OK);

    // 防御：replySeq 应为非负整数或 null，字符串等畸形值被守卫拒绝。
    emitEvent({
      type: VOICE_STATUS_EVENT,
      payload: { ...SPEAKING_WITH_REPLY, replySeq: "abc" } as unknown as VoiceStatus,
    });
    expect(store.getState().voice).toEqual(VOICE_OK);
    store.stop();
  });

  it("EMPTY_VOICE_STATUS 的 reply 为 null（空载语义一致）", () => {
    expect(EMPTY_VOICE_STATUS.reply).toBeNull();
  });
});
