/**
 * libraryStore 测试（M19 TDD）。
 *
 * 经 ``deps.invoker`` 依赖注入 fake 调用器，不 mock Tauri 模块。
 * 覆盖：
 * - 初始状态（EMPTY_LIBRARY_STATE）
 * - scanLibrary 成功/失败归一化
 * - searchLibrary 成功/失败 + searchQuery 同步
 * - fetchStatus / fetchPlaylists / fetchPlaylistSongs 归一化
 * - selectPlaylist 联动 fetchPlaylistSongs
 * - createPlaylist 成功后刷新歌单列表 / 空名拦截
 * - addToPlaylist / removeFromPlaylist 成功后联动刷新
 * - decryptFile confirm 安全门（D19.1 合规）
 * - subscribe 通知 / isLoading 切换 / error 透传
 *
 * 后端契约来自 omni_music/library/db.py + tools.py M19 工具。
 */
import { describe, expect, it, vi } from "vitest";

import {
  EMPTY_LIBRARY_STATE,
  createLibraryStore,
  type LibraryInvoker,
  type LibraryToolResult,
} from "./libraryStore";

// ---------------------------------------------------------------------------
// fake invoker 构造工具
// ---------------------------------------------------------------------------

/** 工具返回结果的简写别名（与 LibraryToolResult<unknown> 同构）。 */
type MusicToolResult = LibraryToolResult<unknown>;

interface FakeInvokerOptions {
  /** tool → 返回结果（ok + data 或 error）。 */
  results?: Record<string, MusicToolResult>;
  /** tool → 结果序列（按调用顺序消费）。 */
  sequences?: Record<string, MusicToolResult[]>;
  /** 默认结果（未匹配 tool 时）。 */
  defaultResult?: MusicToolResult;
}

function makeFakeInvoker(opts: FakeInvokerOptions = {}): {
  invoker: LibraryInvoker;
  calls: { tool: string; args?: Record<string, unknown> }[];
} {
  const calls: { tool: string; args?: Record<string, unknown> }[] = [];
  const seqCounters: Record<string, number> = {};
  const invoker: LibraryInvoker = async (tool, args) => {
    calls.push({ tool, args });
    const seq = opts.sequences?.[tool];
    if (seq !== undefined) {
      const idx = seqCounters[tool] ?? 0;
      seqCounters[tool] = idx + 1;
      const result = seq[Math.min(idx, seq.length - 1)];
      if (result !== undefined) return result;
    }
    const result = opts.results?.[tool];
    if (result !== undefined) return result;
    return opts.defaultResult ?? { ok: false, error: { code: "E_NO_MOCK", message: `未 mock tool: ${tool}` } };
  };
  return { invoker, calls };
}

/** 构造一个合法的 LibrarySong dict（db.py songs 行）。 */
function makeSongDict(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "song_1",
    path: "/music/a.mp3",
    title: "晴天",
    artist: "周杰伦",
    album: "叶惠美",
    duration_s: 269,
    cover_path: null,
    lyrics_path: null,
    source: "local",
    file_mtime: 1000.0,
    file_size: 1024,
    added_at: 2000.0,
    ...overrides,
  };
}

/** 构造一个合法的 Playlist dict（db.py get_playlists 行）。 */
function makePlaylistDict(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 1,
    name: "我的歌单",
    created_at: 1000.0,
    updated_at: 2000.0,
    song_count: 3,
    ...overrides,
  };
}

const okScanResult = (overrides: Record<string, unknown> = {}): MusicToolResult => ({
  ok: true,
  data: { scanned: 10, added: 5, updated: 3, skipped: 2, errors: 0, ...overrides },
});

const okSearchResult = (songs: unknown[]): MusicToolResult => ({
  ok: true,
  data: { songs, count: songs.length },
});

const okStatusResult = (overrides: Record<string, unknown> = {}): MusicToolResult => ({
  ok: true,
  data: { song_count: 100, playlist_count: 5, last_scan_at: 1700000000.0, watching: false, ...overrides },
});

const okPlaylistsResult = (playlists: unknown[]): MusicToolResult => ({
  ok: true,
  data: { playlists, count: playlists.length },
});

const okPlaylistSongsResult = (songs: unknown[], playlistId = 1): MusicToolResult => ({
  ok: true,
  data: { songs, count: songs.length, playlist_id: playlistId },
});

const okDecryptResult = (overrides: Record<string, unknown> = {}): MusicToolResult => ({
  ok: true,
  data: {
    output_path: "/music/a.decrypted.mp3",
    source_path: "/music/a.qmc0",
    compliance: "D19.1: 仅用于已合法购买内容的格式转换",
    notice: "请确保你已合法购买该音频内容",
    ...overrides,
  },
});

// ---------------------------------------------------------------------------
// 初始状态
// ---------------------------------------------------------------------------

describe("libraryStore 初始状态", () => {
  it("createLibraryStore 返回 EMPTY_LIBRARY_STATE 副本", () => {
    const { invoker } = makeFakeInvoker();
    const store = createLibraryStore({ invoker });
    const state = store.getState();
    expect(state.songs).toBeNull();
    expect(state.playlists).toEqual([]);
    expect(state.currentPlaylistId).toBeNull();
    expect(state.playlistSongs).toBeNull();
    expect(state.status).toBeNull();
    expect(state.lastScanResult).toBeNull();
    expect(state.lastDecryptResult).toBeNull();
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
    expect(state.searchQuery).toBe("");
  });

  it("EMPTY_LIBRARY_STATE 是冻结的初始快照", () => {
    expect(EMPTY_LIBRARY_STATE.songs).toBeNull();
    expect(EMPTY_LIBRARY_STATE.playlists).toEqual([]);
    expect(EMPTY_LIBRARY_STATE.isLoading).toBe(false);
  });

  it("subscribe 收到 listener 并在 patch 时通知", () => {
    const { invoker } = makeFakeInvoker();
    const store = createLibraryStore({ invoker });
    const listener = vi.fn();
    const unsub = store.subscribe(listener);
    store.setSearchQuery("test");
    expect(listener).toHaveBeenCalled();
    unsub();
    listener.mockClear();
    store.setSearchQuery("again");
    expect(listener).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// scanLibrary
// ---------------------------------------------------------------------------

describe("libraryStore scanLibrary", () => {
  it("调用 music_library_scan 工具并归一化结果", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: { music_library_scan: okScanResult() },
    });
    const store = createLibraryStore({ invoker });
    const result = await store.scanLibrary();
    expect(result).not.toBeNull();
    expect(result?.scanned).toBe(10);
    expect(result?.added).toBe(5);
    expect(result?.updated).toBe(3);
    expect(result?.skipped).toBe(2);
    expect(result?.errors).toBe(0);
    expect(calls[0]?.tool).toBe("music_library_scan");
    expect(store.getState().lastScanResult).not.toBeNull();
  });

  it("传 rootDir 时 args 包含 root_dir", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: { music_library_scan: okScanResult() },
    });
    const store = createLibraryStore({ invoker });
    await store.scanLibrary("/custom/music");
    expect(calls[0]?.args?.root_dir).toBe("/custom/music");
  });

  it("工具失败时写 error 并返回 null", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        music_library_scan: { ok: false, error: { code: "E_SCAN_FAILED", message: "扫描失败" } },
      },
    });
    const store = createLibraryStore({ invoker });
    const result = await store.scanLibrary();
    expect(result).toBeNull();
    expect(store.getState().error).toBe("扫描失败");
    expect(store.getState().lastScanResult).toBeNull();
  });

  it("数据非法时写 error 并返回 null", async () => {
    const { invoker } = makeFakeInvoker({
      results: { music_library_scan: { ok: true, data: "not an object" } },
    });
    const store = createLibraryStore({ invoker });
    const result = await store.scanLibrary();
    expect(result).toBeNull();
    expect(store.getState().error).toBe("扫描结果数据非法");
  });

  it("isLoading 在调用期间为 true，结束后为 false", async () => {
    const { invoker } = makeFakeInvoker({
      results: { music_library_scan: okScanResult() },
    });
    const store = createLibraryStore({ invoker });
    const states: boolean[] = [];
    store.subscribe(() => states.push(store.getState().isLoading));
    await store.scanLibrary();
    expect(states).toContain(true);
    expect(store.getState().isLoading).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// searchLibrary
// ---------------------------------------------------------------------------

describe("libraryStore searchLibrary", () => {
  it("调用 music_library_search 并归一化歌曲列表", async () => {
    const songs = [makeSongDict({ id: "s1", title: "晴天" }), makeSongDict({ id: "s2", title: "稻香" })];
    const { invoker, calls } = makeFakeInvoker({
      results: { music_library_search: okSearchResult(songs) },
    });
    const store = createLibraryStore({ invoker });
    const result = await store.searchLibrary("周杰伦");
    expect(result).not.toBeNull();
    expect(result).toHaveLength(2);
    expect(result?.[0]?.id).toBe("s1");
    expect(result?.[0]?.title).toBe("晴天");
    expect(calls[0]?.args?.query).toBe("周杰伦");
    expect(calls[0]?.args?.limit).toBe(20);
    expect(store.getState().songs).toHaveLength(2);
    expect(store.getState().searchQuery).toBe("周杰伦");
  });

  it("自定义 limit 透传到 args", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: { music_library_search: okSearchResult([]) },
    });
    const store = createLibraryStore({ invoker });
    await store.searchLibrary("test", 50);
    expect(calls[0]?.args?.limit).toBe(50);
  });

  it("过滤掉缺 id 的非法歌曲", async () => {
    const songs = [makeSongDict({ id: "s1" }), { path: "/x.mp3" }, makeSongDict({ id: "s2" })];
    const { invoker } = makeFakeInvoker({
      results: { music_library_search: okSearchResult(songs) },
    });
    const store = createLibraryStore({ invoker });
    const result = await store.searchLibrary("test");
    expect(result).toHaveLength(2);
  });

  it("工具失败时写 error 并返回 null", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        music_library_search: { ok: false, error: { code: "E_SEARCH_FAILED", message: "搜索失败" } },
      },
    });
    const store = createLibraryStore({ invoker });
    const result = await store.searchLibrary("test");
    expect(result).toBeNull();
    expect(store.getState().error).toBe("搜索失败");
  });
});

// ---------------------------------------------------------------------------
// fetchStatus
// ---------------------------------------------------------------------------

describe("libraryStore fetchStatus", () => {
  it("调用 music_library_status 并归一化", async () => {
    const { invoker } = makeFakeInvoker({
      results: { music_library_status: okStatusResult({ watching: true }) },
    });
    const store = createLibraryStore({ invoker });
    await store.fetchStatus();
    const status = store.getState().status;
    expect(status).not.toBeNull();
    expect(status?.song_count).toBe(100);
    expect(status?.playlist_count).toBe(5);
    expect(status?.last_scan_at).toBe(1700000000.0);
    expect(status?.watching).toBe(true);
  });

  it("last_scan_at 为 null 时归一化为 null", async () => {
    const { invoker } = makeFakeInvoker({
      results: { music_library_status: okStatusResult({ last_scan_at: null }) },
    });
    const store = createLibraryStore({ invoker });
    await store.fetchStatus();
    expect(store.getState().status?.last_scan_at).toBeNull();
  });

  it("数据非法时写 error", async () => {
    const { invoker } = makeFakeInvoker({
      results: { music_library_status: { ok: true, data: "bad" } },
    });
    const store = createLibraryStore({ invoker });
    await store.fetchStatus();
    expect(store.getState().error).toBe("库状态数据非法");
    expect(store.getState().status).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// fetchPlaylists / fetchPlaylistSongs / selectPlaylist
// ---------------------------------------------------------------------------

describe("libraryStore fetchPlaylists", () => {
  it("调用 music_playlist_list 并归一化歌单列表", async () => {
    const playlists = [
      makePlaylistDict({ id: 1, name: "歌单A", song_count: 3 }),
      makePlaylistDict({ id: 2, name: "歌单B", song_count: 0 }),
    ];
    const { invoker } = makeFakeInvoker({
      results: { music_playlist_list: okPlaylistsResult(playlists) },
    });
    const store = createLibraryStore({ invoker });
    await store.fetchPlaylists();
    const list = store.getState().playlists;
    expect(list).toHaveLength(2);
    expect(list[0]?.id).toBe(1);
    expect(list[0]?.name).toBe("歌单A");
    expect(list[0]?.song_count).toBe(3);
    expect(list[1]?.song_count).toBe(0);
  });

  it("过滤掉缺 id/name 的非法歌单", async () => {
    const playlists = [makePlaylistDict({ id: 1 }), { name: "无 ID" }, makePlaylistDict({ id: 2 })];
    const { invoker } = makeFakeInvoker({
      results: { music_playlist_list: okPlaylistsResult(playlists) },
    });
    const store = createLibraryStore({ invoker });
    await store.fetchPlaylists();
    expect(store.getState().playlists).toHaveLength(2);
  });
});

describe("libraryStore fetchPlaylistSongs", () => {
  it("调用 music_playlist_list 传 playlist_id 并归一化歌曲", async () => {
    const songs = [makeSongDict({ id: "s1" }), makeSongDict({ id: "s2" })];
    const { invoker, calls } = makeFakeInvoker({
      results: { music_playlist_list: okPlaylistSongsResult(songs, 5) },
    });
    const store = createLibraryStore({ invoker });
    await store.fetchPlaylistSongs(5);
    expect(calls[0]?.args?.playlist_id).toBe(5);
    expect(store.getState().playlistSongs).toHaveLength(2);
    expect(store.getState().playlistSongs?.[0]?.id).toBe("s1");
  });
});

describe("libraryStore selectPlaylist", () => {
  it("设置 currentPlaylistId 并拉取歌曲", async () => {
    const songs = [makeSongDict({ id: "s1" })];
    const { invoker, calls } = makeFakeInvoker({
      results: { music_playlist_list: okPlaylistSongsResult(songs, 3) },
    });
    const store = createLibraryStore({ invoker });
    await store.selectPlaylist(3);
    expect(store.getState().currentPlaylistId).toBe(3);
    expect(store.getState().playlistSongs).toHaveLength(1);
    expect(calls[0]?.args?.playlist_id).toBe(3);
  });

  it("传 null 时清空 currentPlaylistId 不拉取", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: { music_playlist_list: okPlaylistsResult([]) },
    });
    const store = createLibraryStore({ invoker });
    await store.selectPlaylist(null);
    expect(store.getState().currentPlaylistId).toBeNull();
    expect(store.getState().playlistSongs).toBeNull();
    expect(calls).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// createPlaylist
// ---------------------------------------------------------------------------

describe("libraryStore createPlaylist", () => {
  it("调用 music_playlist_create 并返回 playlist_id", async () => {
    const { invoker, calls } = makeFakeInvoker({
      sequences: {
        music_playlist_create: [{ ok: true, data: { playlist_id: 7, name: "新歌单" } }],
        music_playlist_list: [okPlaylistsResult([makePlaylistDict({ id: 7, name: "新歌单" })])],
      },
    });
    const store = createLibraryStore({ invoker });
    const pid = await store.createPlaylist("新歌单");
    expect(pid).toBe(7);
    expect(calls[0]?.args?.name).toBe("新歌单");
    // 创建后应自动刷新歌单列表
    expect(calls.some((c) => c.tool === "music_playlist_list")).toBe(true);
    expect(store.getState().playlists).toHaveLength(1);
  });

  it("空名拦截返回 null 写 error", async () => {
    const { invoker, calls } = makeFakeInvoker();
    const store = createLibraryStore({ invoker });
    const pid = await store.createPlaylist("   ");
    expect(pid).toBeNull();
    expect(store.getState().error).toBe("歌单名不能为空");
    expect(calls).toHaveLength(0);
  });

  it("工具失败时返回 null 写 error", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        music_playlist_create: { ok: false, error: { code: "E_INVALID_ARGS", message: "重名" } },
      },
    });
    const store = createLibraryStore({ invoker });
    const pid = await store.createPlaylist("重名");
    expect(pid).toBeNull();
    expect(store.getState().error).toBe("重名");
  });

  it("响应缺 playlist_id 时写 error", async () => {
    const { invoker } = makeFakeInvoker({
      results: { music_playlist_create: { ok: true, data: { name: "x" } } },
    });
    const store = createLibraryStore({ invoker });
    const pid = await store.createPlaylist("x");
    expect(pid).toBeNull();
    expect(store.getState().error).toBe("歌单 ID 缺失");
  });
});

// ---------------------------------------------------------------------------
// addToPlaylist / removeFromPlaylist
// ---------------------------------------------------------------------------

describe("libraryStore addToPlaylist", () => {
  it("调用 music_playlist_add 并返回 true", async () => {
    const { invoker, calls } = makeFakeInvoker({
      sequences: {
        music_playlist_add: [{ ok: true, data: { playlist_id: 1, song_id: "s1", added: true } }],
        music_playlist_list: [okPlaylistsResult([])],
      },
    });
    const store = createLibraryStore({ invoker });
    const ok = await store.addToPlaylist(1, "s1");
    expect(ok).toBe(true);
    expect(calls[0]?.args?.playlist_id).toBe(1);
    expect(calls[0]?.args?.song_id).toBe("s1");
  });

  it("传 position 时透传到 args", async () => {
    const { invoker, calls } = makeFakeInvoker({
      sequences: {
        music_playlist_add: [{ ok: true, data: { added: true } }],
        music_playlist_list: [okPlaylistsResult([])],
      },
    });
    const store = createLibraryStore({ invoker });
    await store.addToPlaylist(1, "s1", 3);
    expect(calls[0]?.args?.position).toBe(3);
  });

  it("当前歌单是被添加歌单时联动刷新歌曲列表", async () => {
    const { invoker, calls } = makeFakeInvoker({
      sequences: {
        music_playlist_add: [{ ok: true, data: { added: true } }],
        music_playlist_list: [
          okPlaylistSongsResult([makeSongDict({ id: "s1" }), makeSongDict({ id: "s2" })], 1),
          okPlaylistsResult([]),
          okPlaylistsResult([]),
        ],
      },
    });
    const store = createLibraryStore({ invoker });
    // 先选中歌单 1
    await store.selectPlaylist(1);
    calls.length = 0;
    // 再添加歌曲
    await store.addToPlaylist(1, "s2");
    // 应触发 fetchPlaylistSongs（playlist_id=1）+ fetchPlaylists
    const playlistListCalls = calls.filter((c) => c.tool === "music_playlist_list");
    expect(playlistListCalls.length).toBeGreaterThanOrEqual(2);
    expect(playlistListCalls.some((c) => c.args?.playlist_id === 1)).toBe(true);
  });

  it("工具失败时返回 false 写 error", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        music_playlist_add: { ok: false, error: { code: "E_INVALID_ARGS", message: "歌曲不存在" } },
      },
    });
    const store = createLibraryStore({ invoker });
    const ok = await store.addToPlaylist(1, "bad");
    expect(ok).toBe(false);
    expect(store.getState().error).toBe("歌曲不存在");
  });
});

describe("libraryStore removeFromPlaylist", () => {
  it("调用 music_playlist_remove 并返回 true", async () => {
    const { invoker, calls } = makeFakeInvoker({
      sequences: {
        music_playlist_remove: [{ ok: true, data: { removed: true } }],
        music_playlist_list: [okPlaylistsResult([])],
      },
    });
    const store = createLibraryStore({ invoker });
    const ok = await store.removeFromPlaylist(1, "s1");
    expect(ok).toBe(true);
    expect(calls[0]?.args?.playlist_id).toBe(1);
    expect(calls[0]?.args?.song_id).toBe("s1");
  });

  it("工具失败时返回 false", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        music_playlist_remove: { ok: false, error: { code: "E_INVALID_ARGS", message: "x" } },
      },
    });
    const store = createLibraryStore({ invoker });
    const ok = await store.removeFromPlaylist(1, "s1");
    expect(ok).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// decryptFile（D19.1 合规）
// ---------------------------------------------------------------------------

describe("libraryStore decryptFile", () => {
  it("confirm=true 时调用 music_decrypt_file 并归一化结果", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: { music_decrypt_file: okDecryptResult() },
    });
    const store = createLibraryStore({ invoker });
    const result = await store.decryptFile("/music/a.qmc0", undefined, true);
    expect(result).not.toBeNull();
    expect(result?.output_path).toBe("/music/a.decrypted.mp3");
    expect(result?.source_path).toBe("/music/a.qmc0");
    expect(result?.compliance).toContain("D19.1");
    expect(calls[0]?.args?.path).toBe("/music/a.qmc0");
    expect(calls[0]?.args?.confirm).toBe(true);
    expect(store.getState().lastDecryptResult).not.toBeNull();
  });

  it("传 outputPath 时透传 output_path", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: { music_decrypt_file: okDecryptResult() },
    });
    const store = createLibraryStore({ invoker });
    await store.decryptFile("/music/a.qmc0", "/custom/out.mp3", true);
    expect(calls[0]?.args?.output_path).toBe("/custom/out.mp3");
  });

  it("confirm=false 时拦截不调用工具（D19.1 安全门）", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: { music_decrypt_file: okDecryptResult() },
    });
    const store = createLibraryStore({ invoker });
    const result = await store.decryptFile("/music/a.qmc0");
    expect(result).toBeNull();
    expect(calls).toHaveLength(0);
    expect(store.getState().error).toContain("D19.1");
    expect(store.getState().lastDecryptResult).toBeNull();
  });

  it("工具失败时返回 null 写 error", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        music_decrypt_file: { ok: false, error: { code: "E_DECRYPT_KEY_MISSING", message: "缺密钥" } },
      },
    });
    const store = createLibraryStore({ invoker });
    const result = await store.decryptFile("/music/a.mflac", undefined, true);
    expect(result).toBeNull();
    expect(store.getState().error).toBe("缺密钥");
  });

  it("数据非法时写 error", async () => {
    const { invoker } = makeFakeInvoker({
      results: { music_decrypt_file: { ok: true, data: "bad" } },
    });
    const store = createLibraryStore({ invoker });
    const result = await store.decryptFile("/music/a.qmc0", undefined, true);
    expect(result).toBeNull();
    expect(store.getState().error).toBe("解密结果数据非法");
  });
});

// ---------------------------------------------------------------------------
// setSearchQuery / clearError
// ---------------------------------------------------------------------------

describe("libraryStore setSearchQuery / clearError", () => {
  it("setSearchQuery 更新 searchQuery 并通知", () => {
    const { invoker } = makeFakeInvoker();
    const store = createLibraryStore({ invoker });
    store.setSearchQuery("周杰伦");
    expect(store.getState().searchQuery).toBe("周杰伦");
  });

  it("clearError 清除 error", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        music_library_status: { ok: false, error: { code: "E_X", message: "err" } },
      },
    });
    const store = createLibraryStore({ invoker });
    await store.fetchStatus();
    expect(store.getState().error).toBe("err");
    store.clearError();
    expect(store.getState().error).toBeNull();
  });
});
