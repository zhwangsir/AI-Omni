/**
 * 系统状态轮询引擎（M4.3）：框架无关，订阅模式（与 hudStore 同款，
 * React 侧经 useSyncExternalStore 绑定）。
 *
 * 三个通道（voice / home / system）各自独立定时轮询 HudDataSource：
 * - start 立即拉一轮，之后按各自基础间隔调度；
 * - 拉取失败（available:false 或抛异常）计入连续失败数，下一次调度按
 *   (1 + 失败数)x 基础间隔线性退避，封顶 BACKOFF_MAX_FACTOR 倍；
 *   一次成功即重置回基础间隔——后端宕机时不至于每秒空转 IPC；
 * - pause（窗口隐藏）冻结全部定时器，resume 立即补一轮；
 * - stop 之后在途 fetch 的结果直接丢弃，不写状态。
 *
 * M5.4 voice 事件驱动：source 提供 subscribe 时，voice 通道改由
 * voice-status 事件推送驱动（事件到达直接写状态、清零失败计数），
 * 轮询降为低频兜底（voiceEventFallbackMs，默认 15s）——
 * 不再每秒 spawn CLI 进程；事件通道缺席（纯浏览器 / fake 源）时
 * 维持原 1s 轮询节奏不变。
 */
import {
  EMPTY_HOME_SUMMARY,
  EMPTY_SYSTEM_STATS,
  EMPTY_VOICE_STATUS,
  VOICE_STATUS_EVENT,
  isVoiceStatusPayload,
  type HomeSummary,
  type HudDataSource,
  type HudSourceEvent,
  type SystemStats,
  type VoiceStatus,
} from "../data/sources";

export type StatusChannel = "voice" | "home" | "system";

export interface StatusState {
  readonly voice: VoiceStatus;
  readonly home: HomeSummary;
  readonly system: SystemStats;
  /** 各通道连续失败次数（成功即清零），供 UI 呈现降级徽标与退避调度。 */
  readonly failures: Readonly<Record<StatusChannel, number>>;
  /** true = 轮询引擎已启动（pause 期间仍为 true）。 */
  readonly running: boolean;
  /** true = 已暂停（窗口隐藏），定时器冻结。 */
  readonly paused: boolean;
}

export type StatusIntervals = Readonly<Record<StatusChannel, number>>;

export interface StatusStoreDeps {
  readonly source: HudDataSource;
  /** 各通道基础轮询间隔（ms），缺省用 DEFAULT_INTERVALS。 */
  readonly intervals?: Partial<StatusIntervals>;
  /**
   * voice 事件驱动激活后的兜底轮询间隔（ms），缺省 VOICE_EVENT_FALLBACK_INTERVAL。
   * 仅在 source 提供 subscribe 时生效。
   */
  readonly voiceEventFallbackMs?: number;
}

export interface StatusStore {
  getState: () => StatusState;
  subscribe: (listener: () => void) => () => void;
  /** 启动轮询（幂等）：立即拉一轮并重置 paused。 */
  start: () => void;
  /** 停止轮询：清空全部定时器，在途结果被丢弃。 */
  stop: () => void;
  /** 暂停（窗口隐藏）：冻结定时器，保留 running 标记。 */
  pause: () => void;
  /** 恢复：立即补拉一轮并回到正常节奏。 */
  resume: () => void;
}

/** 失败退避的最大倍率：间隔最多放大到基础值的 5 倍。 */
export const BACKOFF_MAX_FACTOR = 5;

/** 默认轮询节奏：语音状态最敏感 1s，系统指标 2s，家庭摘要 10s。 */
export const DEFAULT_INTERVALS: StatusIntervals = {
  voice: 1000,
  system: 2000,
  home: 10_000,
};

/** voice 事件驱动激活后的兜底轮询间隔：事件推送为主，15s 轮询兜底防漏。 */
export const VOICE_EVENT_FALLBACK_INTERVAL = 15_000;

type TimerHandle = ReturnType<typeof setTimeout>;

interface ChannelFetchers {
  voice: (source: HudDataSource) => Promise<VoiceStatus>;
  home: (source: HudDataSource) => Promise<HomeSummary>;
  system: (source: HudDataSource) => Promise<SystemStats>;
}

const FETCHERS: ChannelFetchers = {
  voice: (source) => source.voiceStatus(),
  home: (source) => source.homeSummary(),
  system: (source) => source.systemStats(),
};

const CHANNELS: readonly StatusChannel[] = ["voice", "home", "system"];

export function createStatusStore(deps: StatusStoreDeps): StatusStore {
  const intervals: StatusIntervals = { ...DEFAULT_INTERVALS, ...deps.intervals };
  const voiceEventFallbackMs = deps.voiceEventFallbackMs ?? VOICE_EVENT_FALLBACK_INTERVAL;
  let state: StatusState = {
    voice: EMPTY_VOICE_STATUS,
    home: EMPTY_HOME_SUMMARY,
    system: EMPTY_SYSTEM_STATS,
    failures: { voice: 0, home: 0, system: 0 },
    running: false,
    paused: false,
  };
  const listeners = new Set<() => void>();
  const timers: Record<StatusChannel, TimerHandle | null> = {
    voice: null,
    home: null,
    system: null,
  };
  /** M5.4：voice 事件订阅句柄与事件驱动标记（subscribe 缺席时维持纯轮询）。 */
  let unsubscribeEvents: (() => void) | null = null;
  let voiceEventDriven = false;

  const emit = (): void => {
    for (const listener of listeners) listener();
  };

  const clearTimer = (channel: StatusChannel): void => {
    const handle = timers[channel];
    if (handle !== null) {
      clearTimeout(handle);
      timers[channel] = null;
    }
  };

  const clearAllTimers = (): void => {
    for (const channel of CHANNELS) clearTimer(channel);
  };

  /** 通道当前生效的基础间隔：voice 事件驱动时降为低频兜底。 */
  const baseInterval = (channel: StatusChannel): number =>
    channel === "voice" && voiceEventDriven ? voiceEventFallbackMs : intervals[channel];

  const schedule = (channel: StatusChannel, delay: number): void => {
    clearTimer(channel);
    if (!state.running || state.paused) return;
    timers[channel] = setTimeout(() => {
      timers[channel] = null;
      void tick(channel);
    }, delay);
  };

  async function tick(channel: StatusChannel): Promise<void> {
    let result: VoiceStatus | HomeSummary | SystemStats;
    try {
      result = await FETCHERS[channel](deps.source);
    } catch {
      result = unavailableOf(channel);
    }
    // stop / pause 之后的迟到结果直接丢弃，不写状态、不再调度。
    if (!state.running || state.paused) return;

    const failures = result.available ? 0 : state.failures[channel] + 1;
    state = applyResult(state, channel, result, failures);
    emit();

    const factor = Math.min(1 + failures, BACKOFF_MAX_FACTOR);
    schedule(channel, baseInterval(channel) * factor);
  }

  /**
   * voice-status 事件入口：事件即权威快照，直接写 voice 并清零失败计数
   * （事件到达本身证明推送通道健康）。stop/pause 期间与畸形负载一律丢弃。
   */
  const handleSourceEvent = (event: HudSourceEvent): void => {
    if (!state.running || state.paused) return;
    if (event.type !== VOICE_STATUS_EVENT || !isVoiceStatusPayload(event.payload)) return;
    state = {
      ...state,
      voice: event.payload,
      failures: { ...state.failures, voice: 0 },
    };
    emit();
  };

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    start() {
      if (state.running) return;
      state = { ...state, running: true, paused: false };
      voiceEventDriven = typeof deps.source.subscribe === "function";
      if (voiceEventDriven) {
        unsubscribeEvents = deps.source.subscribe!(handleSourceEvent);
      }
      emit();
      for (const channel of CHANNELS) schedule(channel, 0);
    },
    stop() {
      if (!state.running) return;
      clearAllTimers();
      unsubscribeEvents?.();
      unsubscribeEvents = null;
      voiceEventDriven = false;
      state = { ...state, running: false, paused: false };
      emit();
    },
    pause() {
      if (!state.running || state.paused) return;
      clearAllTimers();
      state = { ...state, paused: true };
      emit();
    },
    resume() {
      if (!state.running || !state.paused) return;
      state = { ...state, paused: false };
      emit();
      for (const channel of CHANNELS) schedule(channel, 0);
    },
  };
}

function unavailableOf(channel: StatusChannel): VoiceStatus | HomeSummary | SystemStats {
  switch (channel) {
    case "voice":
      return EMPTY_VOICE_STATUS;
    case "home":
      return EMPTY_HOME_SUMMARY;
    case "system":
      return EMPTY_SYSTEM_STATS;
  }
}

/** 通道类型安全的状态合并：计算属性会丢类型，按通道分派。 */
function applyResult(
  prev: StatusState,
  channel: StatusChannel,
  result: VoiceStatus | HomeSummary | SystemStats,
  failures: number,
): StatusState {
  const base: StatusState = {
    ...prev,
    failures: { ...prev.failures, [channel]: failures },
  };
  switch (channel) {
    case "voice":
      return { ...base, voice: result as VoiceStatus };
    case "home":
      return { ...base, home: result as HomeSummary };
    case "system":
      return { ...base, system: result as SystemStats };
  }
}
