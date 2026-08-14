/**
 * AudioPlayer 组件测试（M17.10 TDD）。
 *
 * 覆盖：隐藏 audio 元素 / current_song.url 变化设置 src / state 变化 play/pause /
 * stopped 归零 currentTime / timeupdate 推送 seek（节流）/ ended 调 next /
 * position_s 变化超阈值 seek（避免反馈环）。
 *
 * jsdom 未完整实现媒体播放，mock HTMLAudioElement.prototype.play 返回 resolved。
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { MusicState, MusicStore, PlayerStateContract, Song } from "../../store/musicStore";
import { AudioPlayer } from "./AudioPlayer";

function makeSong(url: string | null): Song {
  return {
    id: "s1",
    name: "晴天",
    source: "netease",
    artists: ["周杰伦"],
    album: null,
    duration_s: 240,
    url,
    lyrics: null,
    cover_url: null,
  };
}

function makePlayerState(overrides: Partial<PlayerStateContract> = {}): PlayerStateContract {
  const song = overrides.current_song !== undefined ? overrides.current_song : makeSong("http://example.com/a.mp3");
  return {
    queue: overrides.queue ?? (song ? [song] : []),
    current_index: 0,
    state: "playing",
    repeat_mode: "sequence",
    position_s: 0,
    current_song: song,
    ...overrides,
  };
}

function makeFakeStore(initial: Partial<MusicState> = {}): {
  store: MusicStore;
  actions: Record<string, ReturnType<typeof vi.fn>>;
  setState: (patch: Partial<MusicState>) => void;
} {
  let state: MusicState = {
    playerState: null,
    isLoading: false,
    error: null,
    loginQr: null,
    loginStatus: "idle",
    onlineResults: null,
    ...initial,
  };
  const listeners = new Set<() => void>();
  const actions = {
    fetchPlayerState: vi.fn(async () => {}),
    play: vi.fn(async () => {}),
    pause: vi.fn(async () => {}),
    resume: vi.fn(async () => {}),
    stop: vi.fn(async () => {}),
    next: vi.fn(async () => {}),
    previous: vi.fn(async () => {}),
    seek: vi.fn(async () => {}),
    setRepeatMode: vi.fn(async () => {}),
    startLogin: vi.fn(async () => {}),
    stopLoginPolling: vi.fn(),
  };
  const store = {
    getState: () => state,
    subscribe: (l: () => void) => {
      listeners.add(l);
      return () => {
        listeners.delete(l);
      };
    },
    ...actions,
  } as unknown as MusicStore;
  return {
    store,
    actions,
    setState(patch) {
      state = { ...state, ...patch };
      act(() => {
        for (const l of [...listeners]) l();
      });
    },
  };
}

let playSpy: ReturnType<typeof vi.spyOn>;
let pauseSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  // jsdom 的 play() 默认 reject（autoplay policy），mock 为 resolve
  playSpy = vi.spyOn(HTMLAudioElement.prototype, "play").mockResolvedValue(undefined);
  pauseSpy = vi.spyOn(HTMLAudioElement.prototype, "pause").mockImplementation(() => {});
  // jsdom 未实现 HTMLMediaElement.prototype.load，mock 为 no-op 避免抛错
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AudioPlayer 基础渲染", () => {
  it("渲染 hidden audio 元素", () => {
    const { store } = makeFakeStore({ playerState: makePlayerState() });
    render(<AudioPlayer store={store} />);
    const audio = screen.getByTestId("audio-player");
    expect(audio.tagName).toBe("AUDIO");
    expect((audio as HTMLAudioElement).hidden).toBe(true);
  });

  it("无 playerState 时也渲染 audio 元素（不崩溃）", () => {
    const { store } = makeFakeStore({ playerState: null });
    render(<AudioPlayer store={store} />);
    expect(screen.getByTestId("audio-player")).toBeInTheDocument();
  });
});

describe("AudioPlayer current_song.url 变化", () => {
  it("有 url 时设置 audio.src", () => {
    const { store } = makeFakeStore({ playerState: makePlayerState() });
    render(<AudioPlayer store={store} />);
    const audio = screen.getByTestId("audio-player") as HTMLAudioElement;
    expect(audio.src).toBe("http://example.com/a.mp3");
  });

  it("url 变化时更新 audio.src", () => {
    const { store, setState } = makeFakeStore({ playerState: makePlayerState() });
    render(<AudioPlayer store={store} />);
    const audio = screen.getByTestId("audio-player") as HTMLAudioElement;
    expect(audio.src).toBe("http://example.com/a.mp3");

    const newSong = makeSong("http://example.com/b.mp3");
    setState({
      playerState: makePlayerState({ current_song: newSong, queue: [newSong] }),
    });
    expect(audio.src).toBe("http://example.com/b.mp3");
  });

  it("url 为 null 时清空 src", () => {
    const song = makeSong(null);
    const { store } = makeFakeStore({
      playerState: makePlayerState({ current_song: song, queue: [song] }),
    });
    render(<AudioPlayer store={store} />);
    const audio = screen.getByTestId("audio-player") as HTMLAudioElement;
    expect(audio.src).toBe("");
  });
});

describe("AudioPlayer state 变化", () => {
  it("state=playing 调 audio.play()", () => {
    const { store } = makeFakeStore({ playerState: makePlayerState({ state: "playing" }) });
    render(<AudioPlayer store={store} />);
    expect(playSpy).toHaveBeenCalled();
  });

  it("state=paused 调 audio.pause()", () => {
    const { store } = makeFakeStore({ playerState: makePlayerState({ state: "paused" }) });
    render(<AudioPlayer store={store} />);
    // 初始渲染 paused → pause 调用
    expect(pauseSpy).toHaveBeenCalled();
  });

  it("从 playing 切到 paused 调 pause", () => {
    const { store, setState } = makeFakeStore({ playerState: makePlayerState({ state: "playing" }) });
    render(<AudioPlayer store={store} />);
    playSpy.mockClear();
    pauseSpy.mockClear();

    setState({ playerState: makePlayerState({ state: "paused" }) });
    expect(pauseSpy).toHaveBeenCalled();
  });

  it("从 paused 切到 playing 调 play", () => {
    const { store, setState } = makeFakeStore({ playerState: makePlayerState({ state: "paused" }) });
    render(<AudioPlayer store={store} />);
    playSpy.mockClear();

    setState({ playerState: makePlayerState({ state: "playing" }) });
    expect(playSpy).toHaveBeenCalled();
  });

  it("state=stopped 归零 currentTime", () => {
    const { store, setState } = makeFakeStore({ playerState: makePlayerState({ state: "playing", position_s: 30 }) });
    render(<AudioPlayer store={store} />);
    const audio = screen.getByTestId("audio-player") as HTMLAudioElement;
    // 模拟 audio 已播放到 30s
    Object.defineProperty(audio, "currentTime", { writable: true, value: 30 });

    setState({ playerState: makePlayerState({ state: "stopped", position_s: 0 }) });
    expect(audio.currentTime).toBe(0);
    expect(pauseSpy).toHaveBeenCalled();
  });
});

describe("AudioPlayer timeupdate 推送", () => {
  it("timeupdate 事件触发 store.seek（首次必推送）", () => {
    const { store, actions } = makeFakeStore({ playerState: makePlayerState({ state: "playing" }) });
    render(<AudioPlayer store={store} />);
    const audio = screen.getByTestId("audio-player") as HTMLAudioElement;
    Object.defineProperty(audio, "currentTime", { writable: true, value: 45 });

    act(() => {
      audio.dispatchEvent(new Event("timeupdate"));
    });
    expect(actions.seek).toHaveBeenCalledWith(45);
  });
});

describe("AudioPlayer ended 事件", () => {
  it("ended 事件调 store.next", () => {
    const { store, actions } = makeFakeStore({ playerState: makePlayerState({ state: "playing" }) });
    render(<AudioPlayer store={store} />);
    const audio = screen.getByTestId("audio-player") as HTMLAudioElement;
    act(() => {
      audio.dispatchEvent(new Event("ended"));
    });
    expect(actions.next).toHaveBeenCalled();
  });
});

describe("AudioPlayer position_s seek", () => {
  it("position_s 与 currentTime 差距超阈值时 seek", () => {
    const { store, setState } = makeFakeStore({
      playerState: makePlayerState({ state: "playing", position_s: 0 }),
    });
    render(<AudioPlayer store={store} />);
    const audio = screen.getByTestId("audio-player") as HTMLAudioElement;
    Object.defineProperty(audio, "currentTime", { writable: true, value: 2 });

    // position_s 跳到 60（差距 58 > 1.5）→ 应 seek
    setState({ playerState: makePlayerState({ state: "playing", position_s: 60 }) });
    expect(audio.currentTime).toBe(60);
  });

  it("position_s 与 currentTime 差距小于阈值时不 seek（避免反馈环）", () => {
    const { store, setState } = makeFakeStore({
      playerState: makePlayerState({ state: "playing", position_s: 10 }),
    });
    render(<AudioPlayer store={store} />);
    const audio = screen.getByTestId("audio-player") as HTMLAudioElement;
    // 设 currentTime 接近 position_s
    Object.defineProperty(audio, "currentTime", { writable: true, value: 10.5 });

    // position_s 微调到 11（差距 0.5 < 1.5）→ 不 seek
    setState({ playerState: makePlayerState({ state: "playing", position_s: 11 }) });
    expect(audio.currentTime).toBe(10.5); // 保持原值
  });
});
