/**
 * M19 本地音乐库 E2E 测试（8 用例）。
 *
 * 覆盖维度：
 * 1. 默认空库 → LibraryView 显示空态（library-song-empty 可见）
 * 2. music_tool music_library_scan → 扫描完成 + 扫描摘要显示
 * 3. music_tool music_library_search → 搜索结果列表渲染
 * 4. music_tool music_playlist_list → 歌单列表渲染
 * 5. music_tool music_playlist_add → 添加歌曲到歌单
 * 6. music_tool music_playlist_remove → 从歌单移除歌曲
 * 7. music_tool music_library_status → 库状态计数显示
 * 8. library IPC 失败 → 错误显示 + 不 crash
 *
 * 路由策略：
 * - 经 fakeTauri.override(CMD.MUSIC_TOOL, ...) 注入各工具响应
 * - 经 __omniDebug.mountLibraryView() 挂载 LibraryView 组件
 * - 经 data-testid 属性断言 UI 状态
 *
 * 注意：LibraryView 默认不在 App.tsx 中渲染（仅 ShelfView 订阅 playlists）。
 * E2E 经 __omniDebug.mountLibraryView() 动态挂载，验证库浏览 UI。
 * 挂载后 LibraryView 的 useEffect 自动调 fetchStatus + fetchPlaylists。
 */
import { test, expect } from "../support/fixture";
import { CMD, GLOBAL_KEYS } from "../support/env";
import { LibraryViewPage } from "../pages/LibraryView";

/** __omniDebug 全局对象 key（inline 供 page.evaluate 使用）。 */
const OMNI_DEBUG_KEY = GLOBAL_KEYS.OMNI_DEBUG;

// ---------------------------------------------------------------------------
// music_tool 响应构造器（与 libraryStore 各 action 的归一化路径对齐）
// ---------------------------------------------------------------------------

/**
 * 所有响应构造器返回 JSON 字符串（与真实 Tauri invoke<string> 返回 String 对齐）。
 *
 * libraryStore.defaultInvoker（libraryStore.ts:112）调用
 * ``invoke<string>('music_tool', {tool, args})`` 后做 ``JSON.parse(raw)`` 解析为
 * ``{ ok, data }`` 信封。若 handler 返回对象，``JSON.parse("[object Object]")``
 * 会抛 SyntaxError → store 降级为 E_IPC_FAILED 错误，UI 不更新。
 *
 * 与 m17-music-control.spec.ts / m20-shelf-view.spec.ts 同款约定。
 */

/** music_library_status 成功响应。 */
function statusOkResponse(
  songCount: number,
  playlistCount: number,
  watching = false,
): string {
  return JSON.stringify({
    ok: true,
    data: {
      song_count: songCount,
      playlist_count: playlistCount,
      last_scan_at: Date.now() / 1000 - 300,
      watching,
    },
  });
}

/** music_library_scan 成功响应。 */
function scanOkResponse(
  scanned: number,
  added: number,
  updated: number,
  skipped: number,
  errors: number,
): string {
  return JSON.stringify({
    ok: true,
    data: { scanned, added, updated, skipped, errors },
  });
}

/** music_library_search 成功响应。 */
function searchOkResponse(songs: Array<{
  id: string;
  title: string;
  artist: string;
  album?: string;
  duration_s?: number;
}>): string {
  return JSON.stringify({
    ok: true,
    data: {
      songs: songs.map((s) => ({
        id: s.id,
        path: `/music/${s.id}.mp3`,
        title: s.title,
        artist: s.artist,
        album: s.album ?? null,
        duration_s: s.duration_s ?? 240,
        cover_path: null,
        lyrics_path: null,
        source: "local",
        file_mtime: 1000,
        file_size: 1024,
        added_at: 2000,
      })),
      count: songs.length,
    },
  });
}

/** music_playlist_list 成功响应（不传 playlist_id → 返回 playlists 数组）。 */
function playlistsOkResponse(playlists: Array<{
  id: number;
  name: string;
  song_count: number;
}>): string {
  return JSON.stringify({
    ok: true,
    data: {
      playlists: playlists.map((p) => ({
        id: p.id,
        name: p.name,
        created_at: 1700000000,
        updated_at: 1700000000,
        song_count: p.song_count,
      })),
    },
  });
}

/** music_playlist_list 成功响应（传 playlist_id → 返回 songs 数组）。 */
function playlistSongsOkResponse(songs: Array<{
  id: string;
  title: string;
  artist: string;
}>): string {
  return JSON.stringify({
    ok: true,
    data: {
      songs: songs.map((s) => ({
        id: s.id,
        path: `/music/${s.id}.mp3`,
        title: s.title,
        artist: s.artist,
        album: null,
        duration_s: 240,
        cover_path: null,
        lyrics_path: null,
        source: "local",
        file_mtime: 1000,
        file_size: 1024,
        added_at: 2000,
      })),
      count: songs.length,
    },
  });
}

/** music_playlist_create 成功响应。 */
function createPlaylistOkResponse(playlistId: number): string {
  return JSON.stringify({ ok: true, data: { playlist_id: playlistId } });
}

/** music_playlist_add 成功响应。 */
function addPlaylistOkResponse(added: boolean): string {
  return JSON.stringify({ ok: true, data: { added } });
}

/** music_playlist_remove 成功响应。 */
function removePlaylistOkResponse(removed: boolean): string {
  return JSON.stringify({ ok: true, data: { removed } });
}

/** music_tool 失败响应。 */
function musicErrorResponse(
  code = "E_BACKEND_UNAVAILABLE",
  message = "音乐库后端不可用",
): string {
  return JSON.stringify({ ok: false, error: { code, message } });
}

/**
 * 默认 music_tool handler：music_library_status / music_playlist_list 返回空数据，
 * 其他工具返回 E_NOT_TAURI（避免 LibraryView 挂载时 fetchStatus/fetchPlaylists 报错）。
 */
function defaultMusicToolHandler(args: Record<string, unknown>): string {
  const tool = args.tool as string | undefined;
  if (tool === "music_library_status") {
    return statusOkResponse(0, 0, false);
  }
  if (tool === "music_playlist_list") {
    // 不传 playlist_id → 返回空 playlists
    if (args.args === undefined || (args.args as Record<string, unknown>).playlist_id === undefined) {
      return playlistsOkResponse([]);
    }
    return playlistSongsOkResponse([]);
  }
  return musicErrorResponse();
}

// ---------------------------------------------------------------------------
// 测试用例
// ---------------------------------------------------------------------------

test.describe("M19 本地音乐库", () => {
  test("默认空库 → LibraryView 显示空态（library-song-empty 可见）", async ({
    appPage,
    fakeTauri,
  }) => {
    // 注入空库响应（status: 0 首 / 0 歌单；playlists: []）
    fakeTauri.override(CMD.MUSIC_TOOL, defaultMusicToolHandler);

    const library = new LibraryViewPage(appPage);
    await library.mount();

    // 等待 LibraryView 挂载 + autoFetch 触发 fetchStatus + fetchPlaylists
    await library.waitForSongPanelMode("empty");
    await library.waitForEmpty();
    // 库状态计数显示 "0 首 / 0 歌单"
    await library.waitForStatusCountsContains("0 首");
    // 歌单列表为空（暂无歌单占位）
    await library.waitForPlaylistRowCount(0);
  });

  test("music_tool music_library_scan → 扫描完成 + 扫描摘要显示", async ({
    appPage,
    fakeTauri,
  }) => {
    fakeTauri.override(CMD.MUSIC_TOOL, (args) => {
      const tool = args.tool as string | undefined;
      if (tool === "music_library_status") return statusOkResponse(120, 5, true);
      if (tool === "music_playlist_list") {
        if ((args.args as Record<string, unknown>)?.playlist_id === undefined) {
          return playlistsOkResponse([]);
        }
        return playlistSongsOkResponse([]);
      }
      if (tool === "music_library_scan") {
        return scanOkResponse(150, 30, 10, 100, 5);
      }
      return musicErrorResponse();
    });

    const library = new LibraryViewPage(appPage);
    await library.mount();

    // 点击扫描按钮触发 scanLibrary
    await library.clickScan();

    // 等待扫描摘要可见且包含 "扫描 150"
    await library.waitForScanSummaryContains("扫描 150");
    // 库状态计数更新为 "120 首 / 5 歌单"
    await library.waitForStatusCountsContains("120 首");
    await library.waitForStatusCountsContains("5 歌单");
  });

  test("music_tool music_library_search → 搜索结果列表渲染", async ({
    appPage,
    fakeTauri,
  }) => {
    fakeTauri.override(CMD.MUSIC_TOOL, (args) => {
      const tool = args.tool as string | undefined;
      if (tool === "music_library_status") return statusOkResponse(100, 3, false);
      if (tool === "music_playlist_list") {
        if ((args.args as Record<string, unknown>)?.playlist_id === undefined) {
          return playlistsOkResponse([]);
        }
        return playlistSongsOkResponse([]);
      }
      if (tool === "music_library_search") {
        return searchOkResponse([
          { id: "s1", title: "晴天", artist: "周杰伦", album: "叶惠美" },
          { id: "s2", title: "稻香", artist: "周杰伦", album: "魔杰座" },
          { id: "s3", title: "夜曲", artist: "周杰伦", album: "十一月的萧邦" },
        ]);
      }
      return musicErrorResponse();
    });

    const library = new LibraryViewPage(appPage);
    await library.mount();

    // 输入搜索关键词 + 回车
    await library.searchByEnter("周杰伦");

    // 等待歌曲面板切到 search 模式 + 3 首歌
    await library.waitForSongPanelMode("search");
    await library.waitForSongCount(3);
  });

  test("music_tool music_playlist_list → 歌单列表渲染", async ({
    appPage,
    fakeTauri,
  }) => {
    fakeTauri.override(CMD.MUSIC_TOOL, (args) => {
      const tool = args.tool as string | undefined;
      if (tool === "music_library_status") return statusOkResponse(100, 3, false);
      if (tool === "music_playlist_list") {
        if ((args.args as Record<string, unknown>)?.playlist_id === undefined) {
          return playlistsOkResponse([
            { id: 1, name: "夜曲", song_count: 5 },
            { id: 2, name: "清晨", song_count: 3 },
            { id: 3, name: "雨夜", song_count: 7 },
          ]);
        }
        return playlistSongsOkResponse([]);
      }
      return musicErrorResponse();
    });

    const library = new LibraryViewPage(appPage);
    await library.mount();

    // 等待歌单列表渲染（3 个歌单）
    await library.waitForPlaylistRowCount(3);
    // 第一个歌单的 data-playlist-id 应为 "1"
    const firstId = await library.getPlaylistId(0);
    expect(firstId).toBe("1");
    // 第一个歌单的文本应包含 "夜曲"
    const firstText = await library.getPlaylistRowText(0);
    expect(firstText).toContain("夜曲");
  });

  test("music_tool music_playlist_add → 添加歌曲到歌单", async ({
    appPage,
    fakeTauri,
  }) => {
    // 跟踪 add 调用，返回 added=true 后续 fetchPlaylists 刷新 song_count
    let addCallCount = 0;
    fakeTauri.override(CMD.MUSIC_TOOL, (args) => {
      const tool = args.tool as string | undefined;
      if (tool === "music_library_status") return statusOkResponse(100, 1, false);
      if (tool === "music_playlist_list") {
        if ((args.args as Record<string, unknown>)?.playlist_id === undefined) {
          // add 后 song_count 从 5 → 6
          return playlistsOkResponse([
            { id: 1, name: "我的歌单", song_count: addCallCount > 0 ? 6 : 5 },
          ]);
        }
        return playlistSongsOkResponse([]);
      }
      if (tool === "music_playlist_add") {
        addCallCount++;
        return addPlaylistOkResponse(true);
      }
      return musicErrorResponse();
    });

    const library = new LibraryViewPage(appPage);
    await library.mount();
    await library.waitForPlaylistRowCount(1);

    // 经 __omniDebug.library.addToPlaylist 触发（绕过 UI 无直接添加入口的限制）
    await appPage.evaluate((key) => {
      const api = (window as unknown as Record<string, unknown>)[
        key
      ] as { library: { addToPlaylist(pid: number, sid: string): Promise<boolean> } } | undefined;
      return api?.library.addToPlaylist(1, "s_new");
    }, OMNI_DEBUG_KEY);

    // 等待 add 调用被记录
    await expect
      .poll(async () => fakeTauri.callsFor(CMD.MUSIC_TOOL).filter(
        (c) => (c.args as { tool?: string })?.tool === "music_playlist_add",
      ).length)
      .toBeGreaterThanOrEqual(1);

    // 等待歌单列表刷新（fetchPlaylists 被 addToPlaylist 内部调用）
    // song_count 从 5 → 6
    await expect
      .poll(async () => {
        const text = await library.getPlaylistRowText(0);
        return text.includes("6");
      })
      .toBe(true);
  });

  test("music_tool music_playlist_remove → 从歌单移除歌曲", async ({
    appPage,
    fakeTauri,
  }) => {
    let removeCallCount = 0;
    fakeTauri.override(CMD.MUSIC_TOOL, (args) => {
      const tool = args.tool as string | undefined;
      if (tool === "music_library_status") return statusOkResponse(100, 1, false);
      if (tool === "music_playlist_list") {
        if ((args.args as Record<string, unknown>)?.playlist_id === undefined) {
          // remove 后 song_count 从 5 → 4
          return playlistsOkResponse([
            { id: 1, name: "我的歌单", song_count: removeCallCount > 0 ? 4 : 5 },
          ]);
        }
        return playlistSongsOkResponse([]);
      }
      if (tool === "music_playlist_remove") {
        removeCallCount++;
        return removePlaylistOkResponse(true);
      }
      return musicErrorResponse();
    });

    const library = new LibraryViewPage(appPage);
    await library.mount();
    await library.waitForPlaylistRowCount(1);

    // 经 __omniDebug.library.removeFromPlaylist 触发
    await appPage.evaluate((key) => {
      const api = (window as unknown as Record<string, unknown>)[
        key
      ] as { library: { removeFromPlaylist(pid: number, sid: string): Promise<boolean> } } | undefined;
      return api?.library.removeFromPlaylist(1, "s1");
    }, OMNI_DEBUG_KEY);

    // 等待 remove 调用被记录
    await expect
      .poll(async () => fakeTauri.callsFor(CMD.MUSIC_TOOL).filter(
        (c) => (c.args as { tool?: string })?.tool === "music_playlist_remove",
      ).length)
      .toBeGreaterThanOrEqual(1);

    // 等待歌单列表刷新（fetchPlaylists 被 removeFromPlaylist 内部调用）
    // song_count 从 5 → 4
    await expect
      .poll(async () => {
        const text = await library.getPlaylistRowText(0);
        return text.includes("4");
      })
      .toBe(true);
  });

  test("music_tool music_library_status → 库状态计数显示", async ({
    appPage,
    fakeTauri,
  }) => {
    fakeTauri.override(CMD.MUSIC_TOOL, (args) => {
      const tool = args.tool as string | undefined;
      if (tool === "music_library_status") {
        return statusOkResponse(256, 12, true);
      }
      if (tool === "music_playlist_list") {
        if ((args.args as Record<string, unknown>)?.playlist_id === undefined) {
          return playlistsOkResponse([]);
        }
        return playlistSongsOkResponse([]);
      }
      return musicErrorResponse();
    });

    const library = new LibraryViewPage(appPage);
    await library.mount();

    // 库状态计数显示 "256 首 / 12 歌单"
    await library.waitForStatusCountsContains("256 首");
    await library.waitForStatusCountsContains("12 歌单");
    // watching=true → library-watching 元素可见
    await expect(appPage.locator('[data-testid="library-watching"]')).toBeVisible();
  });

  test("library IPC 失败 → 错误显示 + 不 crash", async ({
    appPage,
    fakeTauri,
  }) => {
    // 监听未捕获错误
    const errors: string[] = [];
    appPage.on("pageerror", (err) => {
      errors.push(err.message);
    });

    // 让 music_library_status 失败，music_playlist_list 返回空数据
    fakeTauri.override(CMD.MUSIC_TOOL, (args) => {
      const tool = args.tool as string | undefined;
      if (tool === "music_library_status") {
        return musicErrorResponse("E_BACKEND_UNAVAILABLE", "音乐库后端不可用");
      }
      if (tool === "music_playlist_list") {
        if ((args.args as Record<string, unknown>)?.playlist_id === undefined) {
          return playlistsOkResponse([]);
        }
        return playlistSongsOkResponse([]);
      }
      return musicErrorResponse();
    });

    const library = new LibraryViewPage(appPage);
    await library.mount();

    // 等待错误显示包含 "音乐库后端不可用"
    await library.waitForErrorContains("音乐库后端不可用");
    // 不应有未捕获错误
    expect(errors).toEqual([]);
    // LibraryView 仍可用（空态占位可见）
    await library.waitForEmpty();
  });
});
