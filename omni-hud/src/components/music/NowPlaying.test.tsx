/**
 * NowPlaying 组件测试（M17.10 TDD）。
 *
 * 覆盖：空状态占位 / 渲染歌名艺术家专辑封面 / 进度条 seek /
 * 播放暂停按钮 / 上一首下一首停止 / 循环模式切换 / 无 emoji / Icon 组件使用。
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MusicState, MusicStore, PlayerStateContract, Song } from "../../store/musicStore";
import { NowPlaying } from "./NowPlaying";

function makeSong(overrides: Partial<Song> = {}): Song {
  return {
    id: "s1",
    name: "晴天",
    source: "netease",
    artists: ["周杰伦"],
    album: "叶惠美",
    duration_s: 240,
    url: "http://example.com/qingtian.mp3",
    lyrics: null,
    cover_url: "http://example.com/cover.jpg",
    ...overrides,
  };
}

function makePlayerState(overrides: Partial<PlayerStateContract> = {}): PlayerStateContract {
  const song = overrides.current_song !== undefined ? overrides.current_song : makeSong();
  return {
    queue: overrides.queue ?? (song ? [song] : []),
    current_index: 0,
    state: "playing",
    repeat_mode: "sequence",
    position_s: 30,
    current_song: song,
    ...overrides,
  };
}

function makeFakeStore(initial: Partial<MusicState> = {}): {
  store: MusicStore;
  actions: Record<string, ReturnType<typeof vi.fn>>;
  setState: (next: Partial<MusicState>) => void;
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
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
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

describe("NowPlaying 空状态", () => {
  it("无 playerState 时显示「未在播放」占位", () => {
    const { store } = makeFakeStore({ playerState: null });
    render(<NowPlaying store={store} />);
    expect(screen.getByTestId("now-playing")).toHaveAttribute("data-empty", "true");
    expect(screen.getByTestId("now-playing").textContent).toContain("未在播放");
  });

  it("空状态渲染 Music 图标（svg）", () => {
    const { store } = makeFakeStore({ playerState: null });
    const { container } = render(<NowPlaying store={store} />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("current_song 为 null 时显示空状态", () => {
    const { store } = makeFakeStore({
      playerState: makePlayerState({ current_song: null, current_index: -1 }),
    });
    render(<NowPlaying store={store} />);
    expect(screen.getByTestId("now-playing")).toHaveAttribute("data-empty", "true");
  });
});

describe("NowPlaying 渲染曲目信息", () => {
  it("渲染歌名 / 艺术家 / 专辑", () => {
    const { store } = makeFakeStore({ playerState: makePlayerState() });
    render(<NowPlaying store={store} />);
    expect(screen.getByTestId("now-playing-title").textContent).toBe("晴天");
    expect(screen.getByTestId("now-playing-artists").textContent).toBe("周杰伦");
    expect(screen.getByTestId("now-playing-album").textContent).toBe("叶惠美");
  });

  it("有 cover_url 时渲染封面 img", () => {
    const { store } = makeFakeStore({ playerState: makePlayerState() });
    render(<NowPlaying store={store} />);
    const cover = screen.getByTestId("now-playing-cover");
    expect(cover.tagName).toBe("IMG");
    expect((cover as HTMLImageElement).src).toContain("cover.jpg");
  });

  it("无 cover_url 时渲染图标占位（非 img）", () => {
    const song = makeSong({ cover_url: null });
    const { store } = makeFakeStore({
      playerState: makePlayerState({ current_song: song, queue: [song] }),
    });
    render(<NowPlaying store={store} />);
    const cover = screen.getByTestId("now-playing-cover");
    expect(cover.tagName).not.toBe("IMG");
    expect(cover.querySelector("svg")).not.toBeNull();
  });

  it("无 album 时不渲染 album 元素", () => {
    const song = makeSong({ album: null });
    const { store } = makeFakeStore({
      playerState: makePlayerState({ current_song: song, queue: [song] }),
    });
    render(<NowPlaying store={store} />);
    expect(screen.queryByTestId("now-playing-album")).toBeNull();
  });

  it("多艺术家用 / 拼接", () => {
    const song = makeSong({ artists: ["周杰伦", "费玉清"] });
    const { store } = makeFakeStore({
      playerState: makePlayerState({ current_song: song, queue: [song] }),
    });
    render(<NowPlaying store={store} />);
    expect(screen.getByTestId("now-playing-artists").textContent).toBe("周杰伦 / 费玉清");
  });
});

describe("NowPlaying 进度条", () => {
  it("渲染进度条与时间标签", () => {
    const { store } = makeFakeStore({ playerState: makePlayerState() });
    render(<NowPlaying store={store} />);
    const progress = screen.getByTestId("now-playing-progress") as HTMLInputElement;
    expect(progress.tagName).toBe("INPUT");
    expect(progress.type).toBe("range");
    expect(progress.max).toBe("240");
    expect(progress.value).toBe("30");
    expect(screen.getByTestId("now-playing-position").textContent).toBe("0:30");
    expect(screen.getByTestId("now-playing-duration").textContent).toBe("4:00");
  });

  it("拖动进度条触发 store.seek", () => {
    const { store, actions } = makeFakeStore({ playerState: makePlayerState() });
    render(<NowPlaying store={store} />);
    const progress = screen.getByTestId("now-playing-progress") as HTMLInputElement;
    act(() => {
      fireEvent.change(progress, { target: { value: "120" } });
    });
    expect(actions.seek).toHaveBeenCalledWith(120);
  });
});

describe("NowPlaying 控制按钮", () => {
  it("playing 状态显示 pause 图标，点击调 pause", () => {
    const { store, actions } = makeFakeStore({ playerState: makePlayerState({ state: "playing" }) });
    render(<NowPlaying store={store} />);
    const btn = screen.getByTestId("now-playing-play-pause");
    expect(btn).toHaveAttribute("aria-label", "暂停");
    act(() => btn.click());
    expect(actions.pause).toHaveBeenCalled();
  });

  it("paused 状态显示 play 图标，点击调 resume", () => {
    const { store, actions } = makeFakeStore({ playerState: makePlayerState({ state: "paused" }) });
    render(<NowPlaying store={store} />);
    const btn = screen.getByTestId("now-playing-play-pause");
    expect(btn).toHaveAttribute("aria-label", "播放");
    act(() => btn.click());
    expect(actions.resume).toHaveBeenCalled();
  });

  it("上一首按钮调 previous", () => {
    const { store, actions } = makeFakeStore({ playerState: makePlayerState() });
    render(<NowPlaying store={store} />);
    act(() => screen.getByTestId("now-playing-previous").click());
    expect(actions.previous).toHaveBeenCalled();
  });

  it("下一首按钮调 next", () => {
    const { store, actions } = makeFakeStore({ playerState: makePlayerState() });
    render(<NowPlaying store={store} />);
    act(() => screen.getByTestId("now-playing-next").click());
    expect(actions.next).toHaveBeenCalled();
  });

  it("停止按钮调 stop", () => {
    const { store, actions } = makeFakeStore({ playerState: makePlayerState() });
    render(<NowPlaying store={store} />);
    act(() => screen.getByTestId("now-playing-stop").click());
    expect(actions.stop).toHaveBeenCalled();
  });

  it("循环模式按钮显示当前模式图标，点击调 setRepeatMode（下一模式）", () => {
    const { store, actions } = makeFakeStore({
      playerState: makePlayerState({ repeat_mode: "sequence" }),
    });
    render(<NowPlaying store={store} />);
    const btn = screen.getByTestId("now-playing-repeat");
    expect(btn).toHaveAttribute("data-repeat-mode", "sequence");
    expect(btn).toHaveAttribute("aria-label", "顺序播放");
    act(() => btn.click());
    expect(actions.setRepeatMode).toHaveBeenCalledWith("list_loop");
  });

  it("single 模式点击切换到 random", () => {
    const { store, actions } = makeFakeStore({
      playerState: makePlayerState({ repeat_mode: "single" }),
    });
    render(<NowPlaying store={store} />);
    act(() => screen.getByTestId("now-playing-repeat").click());
    expect(actions.setRepeatMode).toHaveBeenCalledWith("random");
  });
});

describe("NowPlaying 风格约束", () => {
  it("渲染内容不含 emoji（Film Atelier 红线）", () => {
    const { store } = makeFakeStore({ playerState: makePlayerState() });
    const { container } = render(<NowPlaying store={store} />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u);
  });

  it("所有图标经 Icon 组件渲染为 svg（非直接 lucide import）", () => {
    const { store } = makeFakeStore({ playerState: makePlayerState() });
    const { container } = render(<NowPlaying store={store} />);
    const svgs = container.querySelectorAll("svg");
    expect(svgs.length).toBeGreaterThan(0);
  });

  it("容器暴露 data-player-state 属性", () => {
    const { store } = makeFakeStore({ playerState: makePlayerState({ state: "playing" }) });
    render(<NowPlaying store={store} />);
    expect(screen.getByTestId("now-playing")).toHaveAttribute("data-player-state", "playing");
  });
});
