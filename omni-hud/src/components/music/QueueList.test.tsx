/**
 * QueueList 组件测试（M17.10 TDD）。
 *
 * 覆盖：空队列占位 / 队列渲染 / 当前曲目高亮 / 点击跳转 play(index) /
 * maxRows 限制 / 无 emoji / Icon svg。
 */
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MusicState, MusicStore, PlayerStateContract, Song } from "../../store/musicStore";
import { QueueList } from "./QueueList";

function makeSong(id: string, name: string, overrides: Partial<Song> = {}): Song {
  return {
    id,
    name,
    source: "netease",
    artists: ["周杰伦"],
    album: null,
    duration_s: 200,
    url: `http://example.com/${id}.mp3`,
    lyrics: null,
    cover_url: null,
    ...overrides,
  };
}

function makePlayerState(queue: Song[], currentIndex: number): PlayerStateContract {
  return {
    queue,
    current_index: currentIndex,
    state: "playing",
    repeat_mode: "sequence",
    position_s: 10,
    current_song: queue[currentIndex] ?? null,
  };
}

function makeFakeStore(playerState: PlayerStateContract | null): {
  store: MusicStore;
  actions: Record<string, ReturnType<typeof vi.fn>>;
} {
  const state: MusicState = {
    playerState,
    isLoading: false,
    error: null,
    loginQr: null,
    loginStatus: "idle",
    onlineResults: null,
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

describe("QueueList 空队列", () => {
  it("queue 为空时显示「队列为空」", () => {
    const { store } = makeFakeStore(makePlayerState([], -1));
    render(<QueueList store={store} />);
    expect(screen.getByTestId("queue-list")).toHaveAttribute("data-empty", "true");
    expect(screen.getByTestId("queue-list").textContent).toContain("队列为空");
  });

  it("playerState 为 null 时显示空占位", () => {
    const { store } = makeFakeStore(null);
    render(<QueueList store={store} />);
    expect(screen.getByTestId("queue-list")).toHaveAttribute("data-empty", "true");
  });

  it("空状态渲染 ListMusic 图标 svg", () => {
    const { store } = makeFakeStore(null);
    const { container } = render(<QueueList store={store} />);
    expect(container.querySelector("svg")).not.toBeNull();
  });
});

describe("QueueList 渲染", () => {
  const songs = [makeSong("s1", "晴天"), makeSong("s2", "七里香"), makeSong("s3", "稻香")];

  it("渲染全部队列项", () => {
    const { store } = makeFakeStore(makePlayerState(songs, 0));
    render(<QueueList store={store} />);
    expect(screen.getByTestId("queue-list")).toHaveAttribute("data-empty", "false");
    expect(screen.getByTestId("queue-list").getAttribute("data-queue-length")).toBe("3");
    const rows = screen.getAllByTestId("queue-list-row");
    expect(rows).toHaveLength(3);
  });

  it("当前曲目高亮（data-current=true）", () => {
    const { store } = makeFakeStore(makePlayerState(songs, 1));
    render(<QueueList store={store} />);
    const rows = screen.getAllByTestId("queue-list-row");
    expect(rows[0]).toHaveAttribute("data-current", "false");
    expect(rows[1]).toHaveAttribute("data-current", "true");
    expect(rows[2]).toHaveAttribute("data-current", "false");
  });

  it("当前曲目显示 play 图标而非序号", () => {
    const { store } = makeFakeStore(makePlayerState(songs, 0));
    render(<QueueList store={store} />);
    // 当前行内含 svg（play 图标）
    const currentRow = screen.getAllByTestId("queue-list-row")[0];
    expect(currentRow.querySelector("svg")).not.toBeNull();
    // 非当前行无 svg（纯序号）
    const otherRow = screen.getAllByTestId("queue-list-row")[1];
    expect(otherRow.querySelector("svg")).toBeNull();
  });

  it("渲染歌名", () => {
    const { store } = makeFakeStore(makePlayerState(songs, 0));
    render(<QueueList store={store} />);
    const rows = screen.getAllByTestId("queue-list-row");
    expect(rows[0].textContent).toContain("晴天");
    expect(rows[1].textContent).toContain("七里香");
  });
});

describe("QueueList 点击跳转", () => {
  const songs = [makeSong("s1", "晴天"), makeSong("s2", "七里香")];

  it("点击某行调 store.play({index})", () => {
    const { store, actions } = makeFakeStore(makePlayerState(songs, 0));
    render(<QueueList store={store} />);
    const rows = screen.getAllByTestId("queue-list-row");
    act(() => rows[1].click());
    expect(actions.play).toHaveBeenCalledWith({ index: 1 });
  });

  it("点击当前行也调 play", () => {
    const { store, actions } = makeFakeStore(makePlayerState(songs, 0));
    render(<QueueList store={store} />);
    act(() => screen.getAllByTestId("queue-list-row")[0].click());
    expect(actions.play).toHaveBeenCalledWith({ index: 0 });
  });
});

describe("QueueList maxRows 限制", () => {
  it("maxRows=2 只渲染前 2 行（不裁剪数据源）", () => {
    const songs = [makeSong("s1", "a"), makeSong("s2", "b"), makeSong("s3", "c")];
    const { store } = makeFakeStore(makePlayerState(songs, 0));
    render(<QueueList store={store} maxRows={2} />);
    const rows = screen.getAllByTestId("queue-list-row");
    expect(rows).toHaveLength(2);
  });
});

describe("QueueList 风格约束", () => {
  it("不含 emoji", () => {
    const songs = [makeSong("s1", "晴天")];
    const { store } = makeFakeStore(makePlayerState(songs, 0));
    const { container } = render(<QueueList store={store} />);
    expect(container.textContent ?? "").not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u);
  });
});
