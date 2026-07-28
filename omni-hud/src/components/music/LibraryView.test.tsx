/**
 * LibraryView 组件测试（M19 TDD）。
 *
 * 覆盖：
 * - 初始渲染 / 空状态占位
 * - 状态栏显示库状态（歌曲数 / 歌单数 / 监听指示 / 扫描摘要）
 * - 扫描按钮调 store.scanLibrary
 * - 搜索输入 + Enter / 按钮调 store.searchLibrary
 * - 歌单列表渲染 / 点击选中 / 创建歌单
 * - 歌曲列表渲染（搜索结果 / 歌单内歌曲）
 * - error 显示
 * - autoFetch=false 不自动拉取
 * - 无 emoji / Icon svg
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  LibraryStore,
  LibraryStoreState,
  LibrarySong,
  Playlist,
  LibraryStatus,
  ScanResult,
} from "../../store/libraryStore";
import { EMPTY_LIBRARY_STATE } from "../../store/libraryStore";
import { LibraryView } from "./LibraryView";

// ---------------------------------------------------------------------------
// fake 数据构造
// ---------------------------------------------------------------------------

function makeSong(overrides: Partial<LibrarySong> = {}): LibrarySong {
  return {
    id: "s1",
    path: "/music/a.mp3",
    title: "晴天",
    artist: "周杰伦",
    album: "叶惠美",
    duration_s: 269,
    cover_path: null,
    lyrics_path: null,
    source: "local",
    file_mtime: 1000,
    file_size: 1024,
    added_at: 2000,
    ...overrides,
  };
}

function makePlaylist(overrides: Partial<Playlist> = {}): Playlist {
  return {
    id: 1,
    name: "我的歌单",
    created_at: 1000,
    updated_at: 2000,
    song_count: 3,
    ...overrides,
  };
}

function makeStatus(overrides: Partial<LibraryStatus> = {}): LibraryStatus {
  return {
    song_count: 100,
    playlist_count: 5,
    last_scan_at: Date.now() / 1000 - 300, // 5 分钟前
    watching: false,
    ...overrides,
  };
}

function makeScanResult(overrides: Partial<ScanResult> = {}): ScanResult {
  return { scanned: 10, added: 5, updated: 3, skipped: 2, errors: 0, ...overrides };
}

// ---------------------------------------------------------------------------
// fake store 构造
// ---------------------------------------------------------------------------

function makeFakeStore(initialState: Partial<LibraryStoreState> = {}): {
  store: LibraryStore;
  actions: Record<string, ReturnType<typeof vi.fn>>;
  setState: (patch: Partial<LibraryStoreState>) => void;
} {
  let state: LibraryStoreState = { ...EMPTY_LIBRARY_STATE, ...initialState };
  const listeners = new Set<() => void>();
  const actions = {
    scanLibrary: vi.fn(async () => makeScanResult() as ScanResult | null),
    searchLibrary: vi.fn(async () => [] as readonly LibrarySong[] | null),
    fetchStatus: vi.fn(async () => {}),
    fetchPlaylists: vi.fn(async () => {}),
    fetchPlaylistSongs: vi.fn(async () => {}),
    selectPlaylist: vi.fn(async () => {}),
    createPlaylist: vi.fn(async () => 1 as number | null),
    addToPlaylist: vi.fn(async () => true),
    removeFromPlaylist: vi.fn(async () => true),
    decryptFile: vi.fn(async () => null),
    setSearchQuery: vi.fn(),
    clearError: vi.fn(),
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
  } as unknown as LibraryStore;
  const setState = (patch: Partial<LibraryStoreState>): void => {
    state = { ...state, ...patch };
    for (const l of listeners) l();
  };
  return { store, actions, setState };
}

// ---------------------------------------------------------------------------
// 初始渲染 / 空状态
// ---------------------------------------------------------------------------

describe("LibraryView 初始渲染", () => {
  it("渲染根容器 library-view", () => {
    const { store } = makeFakeStore();
    render(<LibraryView store={store} autoFetch={false} />);
    expect(screen.getByTestId("library-view")).toBeTruthy();
  });

  it("空状态显示占位文案", () => {
    const { store } = makeFakeStore();
    render(<LibraryView store={store} autoFetch={false} />);
    expect(screen.getByTestId("library-song-empty")).toBeTruthy();
    expect(screen.getByTestId("library-song-panel").getAttribute("data-mode")).toBe("empty");
  });

  it("空状态渲染 music 图标 svg", () => {
    const { store } = makeFakeStore();
    const { container } = render(<LibraryView store={store} autoFetch={false} />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("autoFetch=true 时挂载后调 fetchStatus + fetchPlaylists", () => {
    const { store, actions } = makeFakeStore();
    render(<LibraryView store={store} />);
    expect(actions.fetchStatus).toHaveBeenCalledTimes(1);
    expect(actions.fetchPlaylists).toHaveBeenCalledTimes(1);
  });

  it("autoFetch=false 时不自动拉取", () => {
    const { store, actions } = makeFakeStore();
    render(<LibraryView store={store} autoFetch={false} />);
    expect(actions.fetchStatus).not.toHaveBeenCalled();
    expect(actions.fetchPlaylists).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// 状态栏
// ---------------------------------------------------------------------------

describe("LibraryView 状态栏", () => {
  it("显示歌曲数与歌单数", () => {
    const { store } = makeFakeStore({ status: makeStatus({ song_count: 42, playlist_count: 3 }) });
    render(<LibraryView store={store} autoFetch={false} />);
    const counts = screen.getByTestId("library-status-counts");
    expect(counts.textContent).toContain("42");
    expect(counts.textContent).toContain("3");
  });

  it("status 为 null 时显示 —", () => {
    const { store } = makeFakeStore({ status: null });
    render(<LibraryView store={store} autoFetch={false} />);
    expect(screen.getByTestId("library-status-counts").textContent).toContain("—");
  });

  it("watching=true 时显示监听指示", () => {
    const { store } = makeFakeStore({ status: makeStatus({ watching: true }) });
    render(<LibraryView store={store} autoFetch={false} />);
    expect(screen.getByTestId("library-watching")).toBeTruthy();
  });

  it("watching=false 时不显示监听指示", () => {
    const { store } = makeFakeStore({ status: makeStatus({ watching: false }) });
    render(<LibraryView store={store} autoFetch={false} />);
    expect(screen.queryByTestId("library-watching")).toBeNull();
  });

  it("lastScanResult 存在时显示扫描摘要", () => {
    const { store } = makeFakeStore({
      status: makeStatus(),
      lastScanResult: makeScanResult({ scanned: 50, added: 10, errors: 2 }),
    });
    render(<LibraryView store={store} autoFetch={false} />);
    const summary = screen.getByTestId("library-scan-summary");
    expect(summary.textContent).toContain("50");
    expect(summary.textContent).toContain("10");
    expect(summary.textContent).toContain("错误 2");
  });

  it("点击扫描按钮调 store.scanLibrary", () => {
    const { store, actions } = makeFakeStore();
    render(<LibraryView store={store} autoFetch={false} />);
    act(() => screen.getByTestId("library-scan-btn").click());
    expect(actions.scanLibrary).toHaveBeenCalledTimes(1);
  });

  it("isLoading=true 时扫描按钮禁用", () => {
    const { store } = makeFakeStore({ isLoading: true });
    render(<LibraryView store={store} autoFetch={false} />);
    const btn = screen.getByTestId("library-scan-btn") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 歌单列表
// ---------------------------------------------------------------------------

describe("LibraryView 歌单列表", () => {
  it("渲染歌单行（含名称与歌曲数）", () => {
    const playlists = [
      makePlaylist({ id: 1, name: "歌单A", song_count: 5 }),
      makePlaylist({ id: 2, name: "歌单B", song_count: 0 }),
    ];
    const { store } = makeFakeStore({ playlists });
    render(<LibraryView store={store} autoFetch={false} />);
    const rows = screen.getAllByTestId("library-playlist-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]?.textContent).toContain("歌单A");
    expect(rows[0]?.textContent).toContain("5");
    expect(rows[1]?.textContent).toContain("歌单B");
    expect(rows[1]?.textContent).toContain("0");
  });

  it("歌单为空时显示「暂无歌单」", () => {
    const { store } = makeFakeStore({ playlists: [] });
    render(<LibraryView store={store} autoFetch={false} />);
    expect(screen.getByTestId("library-playlist-sidebar").textContent).toContain("暂无歌单");
  });

  it("点击歌单行调 store.selectPlaylist(id)", () => {
    const playlists = [makePlaylist({ id: 3, name: "x" })];
    const { store, actions } = makeFakeStore({ playlists });
    render(<LibraryView store={store} autoFetch={false} />);
    act(() => screen.getAllByTestId("library-playlist-row")[0].click());
    expect(actions.selectPlaylist).toHaveBeenCalledWith(3);
  });

  it("当前选中歌单高亮（data-current=true）", () => {
    const playlists = [
      makePlaylist({ id: 1, name: "A" }),
      makePlaylist({ id: 2, name: "B" }),
    ];
    const { store } = makeFakeStore({ playlists, currentPlaylistId: 2 });
    render(<LibraryView store={store} autoFetch={false} />);
    const rows = screen.getAllByTestId("library-playlist-row");
    expect(rows[0]?.getAttribute("data-current")).toBe("false");
    expect(rows[1]?.getAttribute("data-current")).toBe("true");
  });

  it("输入名称 + 点击创建按钮调 store.createPlaylist", async () => {
    const { store, actions } = makeFakeStore();
    render(<LibraryView store={store} autoFetch={false} />);
    const input = screen.getByTestId("library-new-playlist-input") as HTMLInputElement;
    act(() => {
      fireEvent.change(input, { target: { value: "新歌单" } });
    });
    await act(async () => {
      screen.getByTestId("library-create-playlist-btn").click();
      // 等待 createPlaylist promise 解析后 setNewName("") 触发的状态更新
      await vi.waitFor(() => expect(actions.createPlaylist).toHaveBeenCalled());
    });
    expect(actions.createPlaylist).toHaveBeenCalledWith("新歌单");
  });

  it("空名称时创建按钮禁用", () => {
    const { store } = makeFakeStore();
    render(<LibraryView store={store} autoFetch={false} />);
    const btn = screen.getByTestId("library-create-playlist-btn") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("输入名称 + Enter 调 store.createPlaylist", async () => {
    const { store, actions } = makeFakeStore();
    render(<LibraryView store={store} autoFetch={false} />);
    const input = screen.getByTestId("library-new-playlist-input") as HTMLInputElement;
    act(() => {
      fireEvent.change(input, { target: { value: "回车歌单" } });
    });
    await act(async () => {
      fireEvent.keyDown(input, { key: "Enter" });
      await vi.waitFor(() => expect(actions.createPlaylist).toHaveBeenCalled());
    });
    expect(actions.createPlaylist).toHaveBeenCalledWith("回车歌单");
  });
});

// ---------------------------------------------------------------------------
// 搜索
// ---------------------------------------------------------------------------

describe("LibraryView 搜索", () => {
  it("输入关键词 + 点击搜索按钮调 store.searchLibrary", () => {
    const { store, actions } = makeFakeStore();
    render(<LibraryView store={store} autoFetch={false} />);
    const input = screen.getByTestId("library-search-input") as HTMLInputElement;
    act(() => {
      fireEvent.change(input, { target: { value: "周杰伦" } });
    });
    act(() => screen.getByTestId("library-search-btn").click());
    expect(actions.searchLibrary).toHaveBeenCalledWith("周杰伦");
  });

  it("输入关键词 + Enter 调 store.searchLibrary", () => {
    const { store, actions } = makeFakeStore();
    render(<LibraryView store={store} autoFetch={false} />);
    const input = screen.getByTestId("library-search-input") as HTMLInputElement;
    act(() => {
      fireEvent.change(input, { target: { value: "晴天" } });
    });
    act(() => {
      fireEvent.keyDown(input, { key: "Enter" });
    });
    expect(actions.searchLibrary).toHaveBeenCalledWith("晴天");
  });

  it("有搜索结果时渲染歌曲列表（mode=search）", () => {
    const songs = [
      makeSong({ id: "s1", title: "晴天", artist: "周杰伦" }),
      makeSong({ id: "s2", title: "稻香", artist: "周杰伦" }),
    ];
    const { store } = makeFakeStore({ songs });
    render(<LibraryView store={store} autoFetch={false} />);
    expect(screen.getByTestId("library-song-panel").getAttribute("data-mode")).toBe("search");
    const list = screen.getByTestId("library-song-list");
    expect(list.getAttribute("data-song-count")).toBe("2");
    const rows = screen.getAllByTestId("library-song-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]?.textContent).toContain("晴天");
    expect(rows[1]?.textContent).toContain("稻香");
  });

  it("搜索结果为空时显示「无匹配歌曲」", () => {
    const { store } = makeFakeStore({ songs: [] });
    render(<LibraryView store={store} autoFetch={false} />);
    expect(screen.getByTestId("library-song-empty").textContent).toContain("无匹配歌曲");
  });
});

// ---------------------------------------------------------------------------
// 歌单内歌曲
// ---------------------------------------------------------------------------

describe("LibraryView 歌单内歌曲", () => {
  it("选中歌单时显示歌单内歌曲（mode=playlist）", () => {
    const songs = [makeSong({ id: "s1", title: "歌单曲目" })];
    const { store } = makeFakeStore({
      songs: null,
      currentPlaylistId: 1,
      playlistSongs: songs,
    });
    render(<LibraryView store={store} autoFetch={false} />);
    expect(screen.getByTestId("library-song-panel").getAttribute("data-mode")).toBe("playlist");
    expect(screen.getByTestId("library-song-list").getAttribute("data-song-count")).toBe("1");
    expect(screen.getAllByTestId("library-song-row")[0]?.textContent).toContain("歌单曲目");
  });

  it("歌单为空时显示「歌单为空」", () => {
    const { store } = makeFakeStore({
      songs: null,
      currentPlaylistId: 1,
      playlistSongs: [],
    });
    render(<LibraryView store={store} autoFetch={false} />);
    expect(screen.getByTestId("library-song-empty").textContent).toContain("歌单为空");
  });

  it("搜索结果优先于歌单内歌曲展示", () => {
    const { store } = makeFakeStore({
      songs: [makeSong({ id: "s1", title: "搜索结果" })],
      currentPlaylistId: 1,
      playlistSongs: [makeSong({ id: "s2", title: "歌单曲目" })],
    });
    render(<LibraryView store={store} autoFetch={false} />);
    expect(screen.getByTestId("library-song-panel").getAttribute("data-mode")).toBe("search");
    expect(screen.getAllByTestId("library-song-row")).toHaveLength(1);
    expect(screen.getAllByTestId("library-song-row")[0]?.textContent).toContain("搜索结果");
  });
});

// ---------------------------------------------------------------------------
// 错误显示
// ---------------------------------------------------------------------------

describe("LibraryView 错误显示", () => {
  it("error 非 null 时显示错误条", () => {
    const { store } = makeFakeStore({ error: "扫描失败" });
    render(<LibraryView store={store} autoFetch={false} />);
    expect(screen.getByTestId("library-error").textContent).toContain("扫描失败");
  });

  it("error 为 null 时不显示错误条", () => {
    const { store } = makeFakeStore({ error: null });
    render(<LibraryView store={store} autoFetch={false} />);
    expect(screen.queryByTestId("library-error")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 风格约束
// ---------------------------------------------------------------------------

describe("LibraryView 风格约束", () => {
  it("不含 emoji", () => {
    const { store } = makeFakeStore({
      songs: [makeSong()],
      playlists: [makePlaylist()],
      status: makeStatus(),
    });
    const { container } = render(<LibraryView store={store} autoFetch={false} />);
    expect(container.textContent ?? "").not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u);
  });

  it("歌曲行渲染 music2 图标 svg", () => {
    const { store } = makeFakeStore({ songs: [makeSong()] });
    render(<LibraryView store={store} autoFetch={false} />);
    const row = screen.getAllByTestId("library-song-row")[0];
    expect(row.querySelector("svg")).not.toBeNull();
  });
});
