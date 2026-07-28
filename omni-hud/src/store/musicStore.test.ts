/**
 * musicStore 测试（M17.10 TDD）。
 *
 * 经 ``deps.invoker`` 依赖注入 fake 调用器，不 mock Tauri 模块。
 * 覆盖：初始状态 / fetchPlayerState 成功失败 / play/pause/next 等 action 调用
 * 正确 tool+args / startLogin 轮询状态机 / stopLoginPolling / subscribe 通知。
 *
 * 后端 to_state_dict 契约来自 omni_music/player.py；Song 来自 models.py。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  EMPTY_MUSIC_STATE,
  createMusicStore,
  type MusicInvoker,
  type MusicToolResult,
} from "./musicStore";

/** 构造一个合法的 Song dict（IPC 边界原始数据，snake_case）。 */
function makeSongDict(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "s1",
    name: "晴天",
    artists: ["周杰伦"],
    album: "叶惠美",
    duration_s: 240,
    url: "http://example.com/qingtian.mp3",
    lyrics: null,
    cover_url: "http://example.com/cover.jpg",
    source: "netease",
    ...overrides,
  };
}

/** 构造一个合法的 PlayerState dict（to_state_dict 输出）。 */
function makePlayerStateDict(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    queue: [makeSongDict()],
    current_index: 0,
    state: "playing",
    repeat_mode: "sequence",
    position_s: 30,
    current_song: makeSongDict(),
    ...overrides,
  };
}

/** fake invoker：按 tool 名分派预设结果，记录所有调用。 */
interface FakeInvokerOptions {
  /** tool → 返回结果（ok + data 或 error）。 */
  results?: Record<string, MusicToolResult<unknown>>;
  /** tool → 结果序列（按调用顺序消费）。 */
  sequences?: Record<string, MusicToolResult<unknown>[]>;
  /** 默认结果（未匹配 tool 时）。 */
  defaultResult?: MusicToolResult<unknown>;
}

function makeFakeInvoker(opts: FakeInvokerOptions = {}): {
  invoker: MusicInvoker;
  calls: { tool: string; args?: Record<string, unknown> }[];
} {
  const calls: { tool: string; args?: Record<string, unknown> }[] = [];
  const seqCounters: Record<string, number> = {};
  const invoker: MusicInvoker = async (tool, args) => {
    calls.push({ tool, args });
    // 先查 sequences
    const seq = opts.sequences?.[tool];
    if (seq !== undefined) {
      const idx = seqCounters[tool] ?? 0;
      seqCounters[tool] = idx + 1;
      const result = seq[Math.min(idx, seq.length - 1)];
      if (result !== undefined) return result;
    }
    // 再查 results
    const result = opts.results?.[tool];
    if (result !== undefined) return result;
    // 默认
    return opts.defaultResult ?? { ok: false, error: { code: "E_NO_MOCK", message: `未 mock tool: ${tool}` } };
  };
  return { invoker, calls };
}

const okPlayerState = (overrides: Record<string, unknown> = {}): MusicToolResult<unknown> => ({
  ok: true,
  data: makePlayerStateDict(overrides),
});

describe("musicStore 初始状态", () => {
  it("createMusicStore 返回 EMPTY_MUSIC_STATE 副本", () => {
    const { invoker } = makeFakeInvoker();
    const store = createMusicStore({ invoker });
    const state = store.getState();
    expect(state.playerState).toBeNull();
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
    expect(state.loginQr).toBeNull();
    expect(state.loginStatus).toBe("idle");
  });

  it("EMPTY_MUSIC_STATE 是冻结的初始快照", () => {
    expect(EMPTY_MUSIC_STATE.playerState).toBeNull();
    expect(EMPTY_MUSIC_STATE.loginStatus).toBe("idle");
  });
});

describe("musicStore subscribe", () => {
  it("状态变化时通知 listener", async () => {
    const { invoker } = makeFakeInvoker({
      results: { music_get_player_state: okPlayerState() },
    });
    const store = createMusicStore({ invoker });
    const listener = vi.fn();
    const unsub = store.subscribe(listener);
    await store.fetchPlayerState();
    expect(listener).toHaveBeenCalled();
    unsub();
  });

  it("unsubscribe 后不再通知", async () => {
    const { invoker } = makeFakeInvoker({
      results: { music_get_player_state: okPlayerState() },
    });
    const store = createMusicStore({ invoker });
    const listener = vi.fn();
    const unsub = store.subscribe(listener);
    unsub();
    await store.fetchPlayerState();
    expect(listener).not.toHaveBeenCalled();
  });
});

describe("fetchPlayerState", () => {
  it("成功：归一化后写入 playerState", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: { music_get_player_state: okPlayerState() },
    });
    const store = createMusicStore({ invoker });
    await store.fetchPlayerState();
    expect(calls[0]?.tool).toBe("music_get_player_state");
    const ps = store.getState().playerState;
    expect(ps).not.toBeNull();
    expect(ps?.state).toBe("playing");
    expect(ps?.current_index).toBe(0);
    expect(ps?.repeat_mode).toBe("sequence");
    expect(ps?.position_s).toBe(30);
    expect(ps?.current_song?.name).toBe("晴天");
    expect(ps?.current_song?.artists).toEqual(["周杰伦"]);
    expect(ps?.current_song?.source).toBe("netease");
    expect(store.getState().error).toBeNull();
  });

  it("失败：写 error，playerState 保持 null", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        music_get_player_state: { ok: false, error: { code: "E_BACKEND", message: "后端挂了" } },
      },
    });
    const store = createMusicStore({ invoker });
    await store.fetchPlayerState();
    expect(store.getState().playerState).toBeNull();
    expect(store.getState().error).toBe("后端挂了");
  });

  it("数据非法（state 字段缺失）：写 error", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        music_get_player_state: { ok: true, data: { queue: [], current_index: 0 } },
      },
    });
    const store = createMusicStore({ invoker });
    await store.fetchPlayerState();
    expect(store.getState().playerState).toBeNull();
    expect(store.getState().error).toBe("播放器状态数据非法");
  });

  it("调用期间 isLoading=true，结束后 false", async () => {
    const { invoker } = makeFakeInvoker({
      results: { music_get_player_state: okPlayerState() },
    });
    const store = createMusicStore({ invoker });
    const promise = store.fetchPlayerState();
    // callTool 进入时 isLoading=true
    expect(store.getState().isLoading).toBe(true);
    await promise;
    expect(store.getState().isLoading).toBe(false);
  });
});

describe("play action", () => {
  it("带 songId：调 music_play + music_get_player_state", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: {
        music_play: { ok: true, data: null },
        music_get_player_state: okPlayerState({ state: "playing" }),
      },
    });
    const store = createMusicStore({ invoker });
    await store.play({ songId: "s1" });
    expect(calls.map((c) => c.tool)).toEqual(["music_play", "music_get_player_state"]);
    expect(calls[0]?.args).toEqual({ song_id: "s1" });
    expect(store.getState().playerState?.state).toBe("playing");
  });

  it("带 index：透传 index 参数", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: {
        music_play: { ok: true, data: null },
        music_get_player_state: okPlayerState(),
      },
    });
    const store = createMusicStore({ invoker });
    await store.play({ index: 2 });
    expect(calls[0]?.args).toEqual({ index: 2 });
  });

  it("带 keyword：透传 keyword 参数", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: {
        music_play: { ok: true, data: null },
        music_get_player_state: okPlayerState(),
      },
    });
    const store = createMusicStore({ invoker });
    await store.play({ keyword: "周杰伦" });
    expect(calls[0]?.args).toEqual({ keyword: "周杰伦" });
  });

  it("无参数：music_play 空 args", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: {
        music_play: { ok: true, data: null },
        music_get_player_state: okPlayerState(),
      },
    });
    const store = createMusicStore({ invoker });
    await store.play();
    expect(calls[0]?.args).toEqual({});
  });
});

describe("pause / resume / stop / next / previous", () => {
  it("pause 调 music_pause 后刷新状态", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: {
        music_pause: { ok: true, data: null },
        music_get_player_state: okPlayerState({ state: "paused" }),
      },
    });
    const store = createMusicStore({ invoker });
    await store.pause();
    expect(calls.map((c) => c.tool)).toEqual(["music_pause", "music_get_player_state"]);
    expect(store.getState().playerState?.state).toBe("paused");
  });

  it("resume 调 music_resume", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: {
        music_resume: { ok: true, data: null },
        music_get_player_state: okPlayerState({ state: "playing" }),
      },
    });
    const store = createMusicStore({ invoker });
    await store.resume();
    expect(calls[0]?.tool).toBe("music_resume");
  });

  it("stop 调 music_stop", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: {
        music_stop: { ok: true, data: null },
        music_get_player_state: okPlayerState({ state: "stopped", position_s: 0 }),
      },
    });
    const store = createMusicStore({ invoker });
    await store.stop();
    expect(calls[0]?.tool).toBe("music_stop");
    expect(store.getState().playerState?.state).toBe("stopped");
  });

  it("next 调 music_next", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: {
        music_next: { ok: true, data: null },
        music_get_player_state: okPlayerState({ current_index: 1 }),
      },
    });
    const store = createMusicStore({ invoker });
    await store.next();
    expect(calls[0]?.tool).toBe("music_next");
  });

  it("previous 调 music_previous", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: {
        music_previous: { ok: true, data: null },
        music_get_player_state: okPlayerState(),
      },
    });
    const store = createMusicStore({ invoker });
    await store.previous();
    expect(calls[0]?.tool).toBe("music_previous");
  });
});

describe("seek action", () => {
  it("正常值：调 music_seek + position_s，不刷新状态", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: { music_seek: { ok: true, data: null } },
    });
    const store = createMusicStore({ invoker });
    await store.seek(120);
    expect(calls).toHaveLength(1);
    expect(calls[0]?.tool).toBe("music_seek");
    expect(calls[0]?.args).toEqual({ position_s: 120 });
  });

  it("负值：忽略，不调 invoker", async () => {
    const { invoker, calls } = makeFakeInvoker();
    const store = createMusicStore({ invoker });
    await store.seek(-5);
    expect(calls).toHaveLength(0);
  });

  it("NaN：忽略", async () => {
    const { invoker, calls } = makeFakeInvoker();
    const store = createMusicStore({ invoker });
    await store.seek(NaN);
    expect(calls).toHaveLength(0);
  });
});

describe("setRepeatMode", () => {
  it("调 music_set_repeat_mode + mode，后刷新状态", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: {
        music_set_repeat_mode: { ok: true, data: null },
        music_get_player_state: okPlayerState({ repeat_mode: "single" }),
      },
    });
    const store = createMusicStore({ invoker });
    await store.setRepeatMode("single");
    expect(calls[0]?.tool).toBe("music_set_repeat_mode");
    expect(calls[0]?.args).toEqual({ mode: "single" });
    expect(store.getState().playerState?.repeat_mode).toBe("single");
  });
});

describe("startLogin 扫码登录", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("成功发起：loginQr 写入，loginStatus=waiting", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: {
        music_get_login_qr: {
          ok: true,
          data: { key: "k1", qr_url: "http://qr.png", source: "netease" },
        },
      },
    });
    const store = createMusicStore({ invoker, loginPollMs: 1000 });
    const promise = store.startLogin();
    await vi.advanceTimersByTimeAsync(0);
    await promise;
    expect(calls[0]?.tool).toBe("music_get_login_qr");
    expect(store.getState().loginQr).toEqual({ key: "k1", qr_url: "http://qr.png", source: "netease" });
    expect(store.getState().loginStatus).toBe("waiting");
  });

  it("发起失败：loginStatus 回 idle，写 error", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        music_get_login_qr: { ok: false, error: { code: "E_LOGIN", message: "发起失败" } },
      },
    });
    const store = createMusicStore({ invoker });
    await store.startLogin();
    expect(store.getState().loginStatus).toBe("idle");
    expect(store.getState().error).toBe("发起失败");
    expect(store.getState().loginQr).toBeNull();
  });

  it("二维码数据非法：loginStatus=idle，写 error", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        music_get_login_qr: { ok: true, data: { key: "k1" } }, // 缺 qr_url / source
      },
    });
    const store = createMusicStore({ invoker });
    await store.startLogin();
    expect(store.getState().loginStatus).toBe("idle");
    expect(store.getState().error).toBe("二维码数据非法");
  });

  it("轮询推进状态：waiting → scanned → confirmed，confirmed 后停止轮询", async () => {
    const { invoker, calls } = makeFakeInvoker({
      sequences: {
        music_get_login_qr: [
          { ok: true, data: { key: "k1", qr_url: "http://qr.png", source: "netease" } },
        ],
        music_check_login_status: [
          { ok: true, data: { status: "scanned" } },
          { ok: true, data: { status: "confirmed" } },
        ],
      },
    });
    const store = createMusicStore({ invoker, loginPollMs: 1000 });
    await store.startLogin();
    expect(store.getState().loginStatus).toBe("waiting");

    // 第一次轮询 → scanned
    await vi.advanceTimersByTimeAsync(1000);
    expect(store.getState().loginStatus).toBe("scanned");

    // 第二次轮询 → confirmed，停止
    await vi.advanceTimersByTimeAsync(1000);
    expect(store.getState().loginStatus).toBe("confirmed");

    // 再推进时间，不应再调 check_login_status
    const checkCallsBefore = calls.filter((c) => c.tool === "music_check_login_status").length;
    await vi.advanceTimersByTimeAsync(3000);
    const checkCallsAfter = calls.filter((c) => c.tool === "music_check_login_status").length;
    expect(checkCallsAfter).toBe(checkCallsBefore);
  });

  it("轮询到 expired：停止轮询", async () => {
    const { invoker } = makeFakeInvoker({
      sequences: {
        music_get_login_qr: [
          { ok: true, data: { key: "k1", qr_url: "http://qr.png", source: "netease" } },
        ],
        music_check_login_status: [{ ok: true, data: { status: "expired" } }],
      },
    });
    const store = createMusicStore({ invoker, loginPollMs: 500 });
    await store.startLogin();
    await vi.advanceTimersByTimeAsync(500);
    expect(store.getState().loginStatus).toBe("expired");
    // 再推进，不会改变状态（已停止）
    await vi.advanceTimersByTimeAsync(2000);
    expect(store.getState().loginStatus).toBe("expired");
  });

  it("stopLoginPolling：清定时器，waiting → idle", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: {
        music_get_login_qr: {
          ok: true,
          data: { key: "k1", qr_url: "http://qr.png", source: "netease" },
        },
      },
    });
    const store = createMusicStore({ invoker, loginPollMs: 1000 });
    await store.startLogin();
    expect(store.getState().loginStatus).toBe("waiting");

    store.stopLoginPolling();
    expect(store.getState().loginStatus).toBe("idle");

    // 推进时间，不应再轮询
    const checkCallsBefore = calls.filter((c) => c.tool === "music_check_login_status").length;
    await vi.advanceTimersByTimeAsync(3000);
    const checkCallsAfter = calls.filter((c) => c.tool === "music_check_login_status").length;
    expect(checkCallsAfter).toBe(checkCallsBefore);
  });

  it("stopLoginPolling 在 confirmed 状态下不改状态（已终止）", async () => {
    const { invoker } = makeFakeInvoker({
      sequences: {
        music_get_login_qr: [
          { ok: true, data: { key: "k1", qr_url: "http://qr.png", source: "netease" } },
        ],
        music_check_login_status: [{ ok: true, data: { status: "confirmed" } }],
      },
    });
    const store = createMusicStore({ invoker, loginPollMs: 500 });
    await store.startLogin();
    await vi.advanceTimersByTimeAsync(500);
    expect(store.getState().loginStatus).toBe("confirmed");
    store.stopLoginPolling();
    expect(store.getState().loginStatus).toBe("confirmed");
  });
});
