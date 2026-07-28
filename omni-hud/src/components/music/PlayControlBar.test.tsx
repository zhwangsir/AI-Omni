/**
 * PlayControlBar 组件测试（M17.10 TDD）。
 *
 * 覆盖：空状态占位 / 精简信息渲染 / 播放暂停按钮 / 上一首下一首 /
 * 进度条 seek / 循环模式切换 / 无 emoji / Icon svg。
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MusicState, MusicStore, PlayerStateContract, Song } from "../../store/musicStore";
import { PlayControlBar } from "./PlayControlBar";

function makeSong(overrides: Partial<Song> = {}): Song {
  return {
    id: "s1",
    name: "晴天",
    source: "netease",
    artists: ["周杰伦"],
    album: "叶惠美",
    duration_s: 240,
    url: "http://example.com/q.mp3",
    lyrics: null,
    cover_url: null,
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
} {
  let state: MusicState = {
    playerState: null,
    isLoading: false,
    error: null,
    loginQr: null,
    loginStatus: "idle",
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
  return { store, actions };
}

describe("PlayControlBar 空状态", () => {
  it("无 playerState 时显示「未在播放」", () => {
    const { store } = makeFakeStore({ playerState: null });
    render(<PlayControlBar store={store} />);
    expect(screen.getByTestId("play-control-bar")).toHaveAttribute("data-empty", "true");
    expect(screen.getByTestId("play-control-bar").textContent).toContain("未在播放");
  });

  it("空状态渲染 Music 图标 svg", () => {
    const { store } = makeFakeStore({ playerState: null });
    const { container } = render(<PlayControlBar store={store} />);
    expect(container.querySelector("svg")).not.toBeNull();
  });
});

describe("PlayControlBar 精简信息", () => {
  it("渲染歌名与艺术家", () => {
    const { store } = makeFakeStore({ playerState: makePlayerState() });
    render(<PlayControlBar store={store} />);
    expect(screen.getByTestId("play-control-bar-title").textContent).toBe("晴天");
    expect(screen.getByTestId("play-control-bar-artists").textContent).toBe("周杰伦");
  });

  it("渲染进度条与时间", () => {
    const { store } = makeFakeStore({ playerState: makePlayerState() });
    render(<PlayControlBar store={store} />);
    const progress = screen.getByTestId("play-control-bar-progress") as HTMLInputElement;
    expect(progress.max).toBe("240");
    expect(progress.value).toBe("30");
  });
});

describe("PlayControlBar 控制按钮", () => {
  it("playing 时点击播放按钮调 pause", () => {
    const { store, actions } = makeFakeStore({ playerState: makePlayerState({ state: "playing" }) });
    render(<PlayControlBar store={store} />);
    const btn = screen.getByTestId("play-control-bar-play-pause");
    expect(btn).toHaveAttribute("aria-label", "暂停");
    act(() => btn.click());
    expect(actions.pause).toHaveBeenCalled();
  });

  it("paused 时点击播放按钮调 resume", () => {
    const { store, actions } = makeFakeStore({ playerState: makePlayerState({ state: "paused" }) });
    render(<PlayControlBar store={store} />);
    const btn = screen.getByTestId("play-control-bar-play-pause");
    expect(btn).toHaveAttribute("aria-label", "播放");
    act(() => btn.click());
    expect(actions.resume).toHaveBeenCalled();
  });

  it("上一首按钮调 previous", () => {
    const { store, actions } = makeFakeStore({ playerState: makePlayerState() });
    render(<PlayControlBar store={store} />);
    act(() => screen.getByTestId("play-control-bar-previous").click());
    expect(actions.previous).toHaveBeenCalled();
  });

  it("下一首按钮调 next", () => {
    const { store, actions } = makeFakeStore({ playerState: makePlayerState() });
    render(<PlayControlBar store={store} />);
    act(() => screen.getByTestId("play-control-bar-next").click());
    expect(actions.next).toHaveBeenCalled();
  });

  it("进度条 change 触发 seek", () => {
    const { store, actions } = makeFakeStore({ playerState: makePlayerState() });
    render(<PlayControlBar store={store} />);
    const progress = screen.getByTestId("play-control-bar-progress") as HTMLInputElement;
    act(() => {
      fireEvent.change(progress, { target: { value: "60" } });
    });
    expect(actions.seek).toHaveBeenCalledWith(60);
  });

  it("循环模式按钮点击调 setRepeatMode", () => {
    const { store, actions } = makeFakeStore({
      playerState: makePlayerState({ repeat_mode: "sequence" }),
    });
    render(<PlayControlBar store={store} />);
    const btn = screen.getByTestId("play-control-bar-repeat");
    expect(btn).toHaveAttribute("data-repeat-mode", "sequence");
    act(() => btn.click());
    expect(actions.setRepeatMode).toHaveBeenCalledWith("list_loop");
  });
});

describe("PlayControlBar 风格约束", () => {
  it("不含 emoji", () => {
    const { store } = makeFakeStore({ playerState: makePlayerState() });
    const { container } = render(<PlayControlBar store={store} />);
    expect(container.textContent ?? "").not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u);
  });

  it("图标渲染为 svg", () => {
    const { store } = makeFakeStore({ playerState: makePlayerState() });
    const { container } = render(<PlayControlBar store={store} />);
    expect(container.querySelectorAll("svg").length).toBeGreaterThan(0);
  });
});
