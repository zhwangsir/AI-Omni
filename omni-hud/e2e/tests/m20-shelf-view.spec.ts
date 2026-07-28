/**
 * M20 ShelfView 3D 歌单架 E2E 测试（7 用例）。
 *
 * 覆盖维度：
 * 1. 右键 toggle：space → shelf，ShelfStage 创建（cardCount 从 0 变为 N）
 * 2. card count：shelf-card-count 显示正确数量
 * 3. 再右键切回：shelf → space，ShelfStage dispose（cardCount 归 0）
 * 4. playlists 同步：libraryStore.playlists 变化时 shelf 卡片同步刷新
 * 5. 空歌单：playlists=[] 时 cardCount=0 不 crash
 * 6. space.setMood(null)：shelf 模式下 setMood(null) 不抛错
 * 7. 场景未就绪不抛错：spaceRef.current=null 时 toggle 静默丢弃不 crash
 *
 * 验证策略：
 * - ShelfView 的 div 在 Full 模式下恒挂载（App.tsx:353），fieldMode 由 hudStore 内部控制
 * - cardCount 是验证 fieldMode 的可靠指标：
 *   space=0（ShelfStage 未创建）/ shelf+N=playlists.length（ShelfStage.setCards 后）
 * - 需先进入 Full 模式（emit VOICE_THINKING → windowMode=full）+ 等 ImmersiveSpace 就绪
 *   （__debug_space__ != null → spaceRef.current != null → getShelfHost 可用）
 * - libraryStore 经 dynamic import /src/store/libraryRuntime.ts 访问 App.tsx 同一单例
 * - MUSIC_TOOL handler 返回 JSON 字符串（与真实 Tauri invoke<string> 返回 String 对齐，
 *   libraryStore.defaultInvoker 经 JSON.parse 解析为 { ok, data } 信封）
 *
 * 注意：ShelfView 内部 useEffect 订阅 hudStore.fieldMode，但 hudStore 单例未导出
 * （App.tsx:50 getHudStore 是模块私有），无法经 evaluate 直接读取 fieldMode。
 * 故用 cardCount 行为间接验证 fieldMode 切换（预填充 playlists 后 shelf 模式 cardCount>0）。
 */
import { test, expect, type Page } from "../support/fixture";
import { CMD, VOICE_STATUS_EVENT } from "../support/env";
import { VOICE_THINKING } from "../fixtures/voice";
import { ShelfViewPage } from "../pages/ShelfView";
import type { IpcRouter } from "../support/ipcRouter";

// ---------------------------------------------------------------------------
// Playlist fixtures（与 src/store/libraryStore.ts Playlist 接口对齐）
// ---------------------------------------------------------------------------

interface PlaylistFixture {
  readonly id: number;
  readonly name: string;
  readonly created_at: number;
  readonly updated_at: number;
  readonly song_count: number;
}

/** 2 首歌单 fixture：用于 toggle / 切回 / 同步测试。 */
const PLAYLISTS_TWO: readonly PlaylistFixture[] = [
  { id: 1, name: "夜曲集", created_at: 1700000000, updated_at: 1700000000, song_count: 5 },
  { id: 2, name: "稻香集", created_at: 1700000001, updated_at: 1700000001, song_count: 7 },
];

/** 3 首歌单 fixture：用于 card count / playlists 同步测试。 */
const PLAYLISTS_THREE: readonly PlaylistFixture[] = [
  ...PLAYLISTS_TWO,
  { id: 3, name: "七里香集", created_at: 1700000002, updated_at: 1700000002, song_count: 9 },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * 进入 Full 模式并等待 ImmersiveSpace 场景就绪。
 *
 * emit VOICE_THINKING → statusStore.voice.windowMode=full → App.tsx 推导
 * windowMode=full → ShelfView 挂载（App.tsx:353）。等待 __debug_space__
 * 就绪确保 spaceRef.current != null，ShelfView 的 shelf 分支才能创建 ShelfStage。
 *
 * 不等场景就绪时 toggle 仍安全（ShelfView 用 space?. 可选链 + host===null
 * 防御），但 ShelfStage 不会创建 → cardCount 保持 0，无法验证 shelf 模式生效。
 */
async function enterFullModeAndWait(
  appPage: Page,
  fakeTauri: IpcRouter,
): Promise<void> {
  fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_THINKING);
  // 等 voice state 更新为 thinking（statusStore 处理 emit 后的异步通知）
  await appPage.waitForFunction(
    () =>
      document
        .querySelector('[data-testid="hud-root"]')
        ?.getAttribute("data-voice-state") === "thinking",
    undefined,
    { timeout: 10_000 },
  );
  // 等 ImmersiveSpace 场景就绪（DEV 模式暴露 __debug_space__）
  await appPage.waitForFunction(
    () =>
      (window as unknown as Record<string, unknown>).__debug_space__ != null,
    undefined,
    { timeout: 15_000 },
  );
}

/**
 * 注入 MUSIC_TOOL handler 并经 libraryStore 单例触发 fetchPlaylists。
 *
 * handler 返回 JSON 字符串（与真实 Tauri invoke<string> 返回 String 对齐），
 * libraryStore.defaultInvoker（libraryStore.ts:112）经 JSON.parse 解析为
 * { ok, data } 信封。若 handler 返回对象则 JSON.parse(object) 会抛 SyntaxError
 * → store 写 E_IPC_FAILED 错误，playlists 不更新。
 *
 * 经 dynamic import /src/store/libraryRuntime.ts 访问 App.tsx 同一单例
 * （App.tsx:77 useMemo(getLibraryStore, [])），调 fetchPlaylists() →
 * music_playlist_list IPC → handler 返回 fixture data → store 更新 playlists
 * → ShelfView 订阅触发 setCards（若 shelf 模式下）。
 *
 * @param playlists 歌单列表 fixture（normalizePlaylist 校验 id/name 必填）
 */
async function populatePlaylists(
  appPage: Page,
  fakeTauri: IpcRouter,
  playlists: readonly PlaylistFixture[],
): Promise<void> {
  fakeTauri.override(CMD.MUSIC_TOOL, (args) => {
    const tool = String(args.tool ?? "");
    if (tool === "music_playlist_list") {
      // 不传 playlist_id 时返回歌单列表；传 playlist_id 时返回空歌曲列表
      if (args.playlist_id !== undefined) {
        return JSON.stringify({ ok: true, data: { songs: [], count: 0 } });
      }
      return JSON.stringify({ ok: true, data: { playlists } });
    }
    return JSON.stringify({ ok: true, data: {} });
  });
  await appPage.evaluate(async () => {
    const mod = await import("/src/store/libraryRuntime.ts");
    const store = mod.getLibraryStore();
    await store.fetchPlaylists();
  });
}

/**
 * 收集 console.error 与 pageerror，用于「不抛错」断言。
 *
 * 返回一个数组与清理函数。测试结束前应断言数组为空（无 error）。
 * ShelfView 内部用 space?.setMood(null) 等可选链防御 null，若防御失效
 * 会经 React 错误边界或 window.onerror 暴露为 pageerror。
 */
function collectErrors(appPage: Page): {
  readonly errors: string[];
} {
  const errors: string[] = [];
  appPage.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`[console] ${msg.text()}`);
  });
  appPage.on("pageerror", (err) => {
    errors.push(`[pageerror] ${err.message}`);
  });
  return { errors };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("M20 ShelfView 3D 歌单架", () => {
  test("1. 右键 toggle: 默认 space 模式,右键后 fieldMode=shelf,ShelfView 挂载", async ({
    appPage,
    fakeTauri,
  }) => {
    await enterFullModeAndWait(appPage, fakeTauri);
    const shelf = new ShelfViewPage(appPage);
    await shelf.waitForMounted();

    // 预填充 playlists（2 首）：space 模式下 ShelfStage 未创建，cardCount=0
    await populatePlaylists(appPage, fakeTauri, PLAYLISTS_TWO);
    expect(await shelf.getCardCount()).toBe(0);

    // 右键 toggle: space → shelf
    await shelf.rightClick();

    // shelf 模式下 ShelfStage 创建 + setCards(playlists) → cardCount=2
    // 间接验证 fieldMode 已切换为 shelf（cardCount>0 仅在 shelf 模式下成立）
    await shelf.waitForCardCount(2);
  });

  test("2. card count: 验证 shelf-card-count 显示正确数量", async ({
    appPage,
    fakeTauri,
  }) => {
    await enterFullModeAndWait(appPage, fakeTauri);
    const shelf = new ShelfViewPage(appPage);
    await shelf.waitForMounted();

    // 预填充 3 个歌单
    await populatePlaylists(appPage, fakeTauri, PLAYLISTS_THREE);

    // 右键进入 shelf 模式
    await shelf.rightClick();

    // shelf-card-count textContent 应为 "3"
    // playlistToCards 1:1 映射 Playlist → CardData（kind=playlist）
    await shelf.waitForCardCount(3);
    expect(await shelf.getCardCount()).toBe(3);

    // 直接读 shelf-card-count 元素 textContent 验证（display:none 元素）
    const raw = await appPage.evaluate(() => {
      const el = document.querySelector('[data-testid="shelf-card-count"]');
      return el?.textContent ?? null;
    });
    expect(raw).toBe("3");
  });

  test("3. 再右键切回: shelf→space,ShelfView 卸载", async ({
    appPage,
    fakeTauri,
  }) => {
    await enterFullModeAndWait(appPage, fakeTauri);
    const shelf = new ShelfViewPage(appPage);
    await shelf.waitForMounted();

    await populatePlaylists(appPage, fakeTauri, PLAYLISTS_TWO);

    // 第一次右键: space → shelf（cardCount=2）
    await shelf.rightClick();
    await shelf.waitForCardCount(2);

    // 第二次右键: shelf → space
    await shelf.rightClick();

    // space 模式下 ShelfStage.dispose() + setCardCount(0)
    // （ShelfView.tsx:46-48 切回 space 分支）
    await shelf.waitForCardCount(0);

    // 验证 ShelfStage 已 dispose（cardCount 归 0 表示 ShelfStage 不再持有卡片）
    expect(await shelf.getCardCount()).toBe(0);
  });

  test("4. playlists 同步: libraryStore.playlists 变化时 shelf 卡片同步刷新", async ({
    appPage,
    fakeTauri,
  }) => {
    await enterFullModeAndWait(appPage, fakeTauri);
    const shelf = new ShelfViewPage(appPage);
    await shelf.waitForMounted();

    // 先进入 shelf 模式（空歌单，cardCount=0）
    await shelf.rightClick();
    await shelf.waitForCardCount(0);

    // 动态更新 playlists（空 → 3 首）
    // ShelfView.tsx:110-123 第二个 useEffect 订阅 libraryStore：
    // playlists 变化 → onChange → shelf.setCards(cards) + setCardCount(cards.length)
    await populatePlaylists(appPage, fakeTauri, PLAYLISTS_THREE);

    // cardCount 应同步刷新为 3（无需再次 toggle，libraryStore 订阅自动触发）
    await shelf.waitForCardCount(3);
  });

  test("5. 空歌单: playlists=[] 时显示空状态", async ({
    appPage,
    fakeTauri,
  }) => {
    await enterFullModeAndWait(appPage, fakeTauri);
    const shelf = new ShelfViewPage(appPage);
    await shelf.waitForMounted();

    // 显式注入空歌单（playlists=[]）
    await populatePlaylists(appPage, fakeTauri, []);

    // 右键进入 shelf 模式
    await shelf.rightClick();

    // 空歌单: playlistToCards([]) = [] → setCards([]) → cardCount=0
    // 不 crash，shelf-view 仍在 DOM
    await shelf.waitForCardCount(0);
    expect(await shelf.root.count()).toBe(1);

    // 验证 shelf-card-count textContent 为 "0"（空状态显式展示）
    const raw = await appPage.evaluate(() => {
      const el = document.querySelector('[data-testid="shelf-card-count"]');
      return el?.textContent ?? null;
    });
    expect(raw).toBe("0");
  });

  test("6. space.setMood(null): null mood 不抛错,场基线即默认氛围", async ({
    appPage,
    fakeTauri,
  }) => {
    await enterFullModeAndWait(appPage, fakeTauri);
    const shelf = new ShelfViewPage(appPage);
    await shelf.waitForMounted();

    // 收集 console.error 与 pageerror（setMood 抛错会经 React 错误边界暴露）
    const { errors } = collectErrors(appPage);

    // toggle 到 shelf: ShelfView.tsx:77 调 space?.setMood(null) 重置粒子氛围
    // （shelf 激活时重置 mood 到基线，避免语音态放大粒子干扰卡片可读性）
    await shelf.rightClick();
    await shelf.waitForCardCount(0);

    // 验证无 error（setMood(null) 不抛错，场基线即默认氛围）
    // 给一缓冲让可能的异步错误暴露
    await appPage.waitForTimeout(500);
    expect(errors).toEqual([]);

    // 验证页面仍可交互（场基线恢复后组件未崩溃，可再次 toggle）
    await shelf.rightClick();
    await shelf.waitForCardCount(0);
    expect(errors).toEqual([]);
  });

  test("7. 场景未就绪不抛错: spaceRef.current=null 时调用 setMood 等静默丢弃", async ({
    appPage,
    fakeTauri,
  }) => {
    // 进入 Full 模式但不主动等待场景就绪（模拟场景未就绪状态）
    // ImmersiveSpace.tsx:55-87 异步动态 import createSpace + runtime，
    // 在此期间 spaceRef.current=null，ShelfView 的 shelf 分支应静默跳过
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_THINKING);
    await appPage.waitForFunction(
      () =>
        document
          .querySelector('[data-testid="hud-root"]')
          ?.getAttribute("data-voice-state") === "thinking",
      undefined,
      { timeout: 10_000 },
    );

    const shelf = new ShelfViewPage(appPage);
    await shelf.waitForMounted();

    // 收集 pageerror（spaceRef.current=null 时 setMood 等调用应被 ?.
    // 可选链静默丢弃，不应抛错）
    const { errors } = collectErrors(appPage);

    // 在场景可能未就绪时 toggle（spaceRef.current 可能为 null）
    // ShelfView.tsx:62 host = space?.getShelfHost() ?? null → null 时 return
    // ShelfView.tsx:77 space?.setMood(null) → null 时跳过
    await shelf.rightClick();
    // 等待一小段时间确认无 error 抛出（React 重渲染 + 异步 effect）
    await appPage.waitForTimeout(500);
    expect(errors).toEqual([]);

    // 等场景就绪后，需再次 toggle 触发 onChange（hudStore.subscribe 不监听
    // spaceRef 变化，ShelfStage 创建只在 hudStore 状态变化时尝试）
    await shelf.waitForSpaceReady();

    // 预填充 playlists（2 首）
    await populatePlaylists(appPage, fakeTauri, PLAYLISTS_TWO);

    // 此时 fieldMode=shelf（之前 toggle 过）但 ShelfStage 可能未创建
    // （场景未就绪时 toggle 被静默跳过）。toggle 回 space 再到 shelf 触发 onChange：
    await shelf.rightClick(); // shelf → space（ShelfStage 已 null，无操作）
    await appPage.waitForTimeout(200);
    await shelf.rightClick(); // space → shelf（此时场景已就绪，ShelfStage 创建）

    // cardCount 应更新为 2（ShelfStage.setCards 注入 2 张卡片）
    await shelf.waitForCardCount(2);

    // 全程无 error（spaceRef.current=null 防御 + 场景就绪后正常工作）
    expect(errors).toEqual([]);
  });
});
