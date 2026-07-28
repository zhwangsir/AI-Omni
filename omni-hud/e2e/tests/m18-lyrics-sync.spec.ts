/**
 * M18 歌词同步 E2E 测试（9 用例）。
 *
 * 覆盖维度：
 * 1. 无曲目时不渲染歌词面板（current_song=null → LyricsDisplay 不挂载）
 * 2. 有曲目 → lyrics_tool IPC 调用获取歌词（bindLyricsSync 触发 fetchLyrics）
 * 3. LRC 解析正确显示歌词行（parsed 渲染为 lyrics-row 列表）
 * 4. position_s 变化 → 当前行高亮切换（refreshCurrentLine 本地二分）
 * 5. 逐字歌词显示（lyrics-word + lyrics-word-current 高亮）
 * 6. 翻译歌词显示（lyrics-row-translation span）
 * 7. 无歌词时显示纯文本（source=none + data-empty="true"）
 * 8. lyrics_tool IPC 失败 → 降级显示空态（不 crash）
 * 9. 切歌时歌词重新获取（current_song.id 变化 → fetchLyrics 重跑）
 *
 * 路由策略：
 * - music_tool handler 返回带 current_song 的 player state（触发 LyricsDisplay 挂载）
 * - lyrics_tool handler 按 args.tool 分发（lyrics_get / lyrics_set_offset 等）
 * - 经 ``__omniDebug.music.fetchPlayerState()`` 触发 musicStore 拉取
 * - 经 ``__omniDebug.lyrics.refreshCurrentLine(pos)`` 驱动当前行切换
 *
 * 重要：handler 必须返回 JSON 字符串（与 lyricsStore.defaultInvoker 的
 * ``invoke<string>`` + ``JSON.parse`` 模式对齐），否则会因
 * ``JSON.parse("[object Object]")`` 抛 "is not valid JSON" 错误。
 */
import { test, expect } from "../support/fixture";
import { CMD } from "../support/env";
import { HudApp } from "../pages/HudApp";
import { LyricsDisplay } from "../pages/LyricsDisplay";
import {
  okEnvelope,
  EMPTY_LYRICS_RESULT,
  LRC_STANDARD_RESULT,
  LRC_WORD_BY_WORD_RESULT,
  LRC_WITH_TRANSLATION_RESULT,
  MULTI_LINE_RESULT,
  PLAIN_TEXT_RESULT,
} from "../fixtures/lyrics";
import { PLAYER_STATE_PLAYING, SONG_QINGTIAN } from "../fixtures/music";
import type { LyricsResult } from "../../src/store/lyricsStore";

/**
 * 构造 music_tool handler：返回带 current_song 的 player state，
 * 触发 App.tsx 渲染 LyricsDisplay。
 */
function makeMusicHandlerWithSong(): (args: Record<string, unknown>) => unknown {
  return (args) => {
    const tool = String(args.tool ?? "");
    if (tool === "music_get_player_state") {
      return JSON.stringify(okEnvelope(PLAYER_STATE_PLAYING));
    }
    return JSON.stringify(okEnvelope({}));
  };
}

/**
 * 构造 music_tool handler：返回空 player state（无 current_song），
 * 触发 App.tsx 不渲染 LyricsDisplay。
 */
function makeMusicHandlerEmpty(): (args: Record<string, unknown>) => unknown {
  return (args) => {
    const tool = String(args.tool ?? "");
    if (tool === "music_get_player_state") {
      // current_song=null → App.tsx 不渲染 LyricsDisplay
      return JSON.stringify(
        okEnvelope({
          ...PLAYER_STATE_PLAYING,
          current_song: null,
          queue: [],
          current_index: -1,
          state: "stopped",
          position_s: 0,
        }),
      );
    }
    return JSON.stringify(okEnvelope({}));
  };
}

/**
 * 构造 lyrics_tool handler：lyrics_get 返回指定 LyricsResult。
 *
 * @param getLyrics 返回 lyrics_get 的 fixture data（LyricsResult 结构）
 */
function makeLyricsHandler(
  getLyrics: () => LyricsResult = () => LRC_STANDARD_RESULT,
): (args: Record<string, unknown>) => unknown {
  return (args) => {
    const tool = String(args.tool ?? "");
    switch (tool) {
      case "lyrics_get":
        return JSON.stringify(okEnvelope(getLyrics()));
      case "lyrics_set_offset":
        return JSON.stringify(okEnvelope({ offset_s: 0 }));
      case "lyrics_search":
        return JSON.stringify(okEnvelope({ songs: [], count: 0 }));
      case "lyrics_upload":
        return JSON.stringify(okEnvelope({ path: "/tmp/test.lrc" }));
      case "lyrics_get_current":
        return JSON.stringify(okEnvelope({ line: null, word: null }));
      default:
        return JSON.stringify(okEnvelope({}));
    }
  };
}

/** 触发 musicStore.fetchPlayerState()（等待 __omniDebug 就绪）。 */
async function fetchPlayerStateViaDebug(page: import("@playwright/test").Page): Promise<void> {
  const hud = new HudApp(page);
  await hud.waitForDebugApi();
  await page.evaluate(() => {
    const debug = (window as unknown as {
      __omniDebug?: { music: { fetchPlayerState: () => Promise<void> } };
    }).__omniDebug;
    return debug!.music.fetchPlayerState();
  });
}

test.describe("M18 歌词同步", () => {
  test("无曲目时不渲染歌词面板（current_song=null → LyricsDisplay 不挂载）", async ({
    appPage,
    fakeTauri,
  }) => {
    // 注入空 player state（无 current_song）→ App.tsx 不渲染 LyricsDisplay
    fakeTauri.override(CMD.MUSIC_TOOL, makeMusicHandlerEmpty());
    fakeTauri.override(CMD.LYRICS_TOOL, makeLyricsHandler());

    const lyrics = new LyricsDisplay(appPage);

    // fetchPlayerState 拉取空 player state → current_song=null
    await fetchPlayerStateViaDebug(appPage);

    // LyricsDisplay 应未挂载（App.tsx:348 currentSong !== null 条件不满足）
    // 等待 detached：初始就不挂载，立即满足
    await lyrics.waitForDetached(2_000);
  });

  test("有曲目 → lyrics_tool IPC 调用获取歌词（bindLyricsSync 触发 fetchLyrics）", async ({
    appPage,
    fakeTauri,
  }) => {
    // music_tool 返回带 current_song 的状态 → App.tsx 渲染 LyricsDisplay
    // lyrics_tool 返回标准 LRC
    fakeTauri.override(CMD.MUSIC_TOOL, makeMusicHandlerWithSong());
    fakeTauri.override(CMD.LYRICS_TOOL, makeLyricsHandler(() => LRC_STANDARD_RESULT));

    const lyrics = new LyricsDisplay(appPage);

    // fetchPlayerState → current_song=SONG_QINGTIAN → bindLyricsSync 的 onChange
    // 检测到 songId 变化（null → "song_1"）→ 调 lyricsStore.fetchLyrics("song_1")
    // → lyrics_get IPC 调用 → 返回 LRC_STANDARD_RESULT → lyricsStore 写入 currentLyrics
    // → LyricsDisplay 渲染 parsed 行
    await fetchPlayerStateViaDebug(appPage);

    // 等待 LyricsDisplay 挂载并显示非空歌词
    await lyrics.waitForMounted();
    await lyrics.waitForEmpty(false);

    // 断言 lyrics_tool IPC 被调用（lyrics_get with song_id="song_1"）
    const calls = fakeTauri.callsFor(CMD.LYRICS_TOOL);
    expect(calls.length).toBeGreaterThanOrEqual(1);
    const getCall = calls.find((c) => (c.args as { tool?: string }).tool === "lyrics_get");
    expect(getCall).toBeDefined();
    expect(getCall?.args).toMatchObject({
      tool: "lyrics_get",
      args: { song_id: SONG_QINGTIAN.id },
    });
  });

  test("LRC 解析正确显示歌词行（parsed 渲染为 lyrics-row 列表）", async ({
    appPage,
    fakeTauri,
  }) => {
    fakeTauri.override(CMD.MUSIC_TOOL, makeMusicHandlerWithSong());
    fakeTauri.override(CMD.LYRICS_TOOL, makeLyricsHandler(() => LRC_STANDARD_RESULT));

    const lyrics = new LyricsDisplay(appPage);
    await fetchPlayerStateViaDebug(appPage);

    await lyrics.waitForMounted();
    await lyrics.waitForEmpty(false);

    // LRC_STANDARD_RESULT.parsed 有 3 行 → 渲染 3 个 lyrics-row
    const rowCount = await lyrics.getRows().count();
    expect(rowCount).toBe(LRC_STANDARD_RESULT.parsed.length);

    // 验证每行的 text 与 time_s
    for (let i = 0; i < LRC_STANDARD_RESULT.parsed.length; i++) {
      const expected = LRC_STANDARD_RESULT.parsed[i]!;
      expect(await lyrics.getRowText(i)).toContain(expected.text);
      expect(await lyrics.getRowTime(i)).toBe(expected.time_s);
    }
  });

  test("position_s 变化 → 当前行高亮切换（refreshCurrentLine 本地二分）", async ({
    appPage,
    fakeTauri,
  }) => {
    // 使用 MULTI_LINE_RESULT：5 行，时间 0/2/4/6/8s，每 2s 切一行
    fakeTauri.override(CMD.MUSIC_TOOL, makeMusicHandlerWithSong());
    fakeTauri.override(CMD.LYRICS_TOOL, makeLyricsHandler(() => MULTI_LINE_RESULT));

    const lyrics = new LyricsDisplay(appPage);
    await fetchPlayerStateViaDebug(appPage);

    await lyrics.waitForMounted();
    await lyrics.waitForEmpty(false);

    // 等待渲染完成（5 行）+ lyricsStore.currentLyrics 已写入。
    // fetchPlayerState → bindLyricsSync → fetchLyrics → lyrics_get IPC →
    // lyricsStore.currentLyrics 写入 → LyricsDisplay 渲染 parsed 行。
    // 等待行数 = 5 确保歌词已就绪，refreshCurrentLine 才不会因 currentLyrics=null 早退。
    //
    // 注意：LyricsDisplay 的 useEffect 在挂载时即触发 refreshCurrentLine(positionS)，
    // 但此时 currentLyrics=null（fetchLyrics 尚未完成）→ no-op。fetchLyrics 完成后
    // 写入 currentLyrics + currentIndex=-1，但 useEffect 不会因 currentLyrics 变化重跑
    // （依赖仅 positionS / store）。故测试需手动调 refreshCurrentLine 驱动当前行切换。
    await expect
      .poll(async () => await lyrics.getRows().count())
      .toBe(MULTI_LINE_RESULT.parsed.length);

    // position_s=1.0 → 第 0 行（time_s=0 是最大的 <= 1.0 的）
    await appPage.evaluate(() => {
      const debug = (window as unknown as {
        __omniDebug?: { lyrics: { refreshCurrentLine: (pos: number) => void } };
      }).__omniDebug;
      debug!.lyrics.refreshCurrentLine(1.0);
    });
    await lyrics.waitForCurrentIndex(0);
    expect(await lyrics.isRowCurrent(0)).toBe(true);
    expect(await lyrics.isRowCurrent(1)).toBe(false);

    // position_s=3.0 → 第 1 行（time_s=2 是最大的 <= 3.0 的）
    await appPage.evaluate(() => {
      const debug = (window as unknown as {
        __omniDebug?: { lyrics: { refreshCurrentLine: (pos: number) => void } };
      }).__omniDebug;
      debug!.lyrics.refreshCurrentLine(3.0);
    });
    await lyrics.waitForCurrentIndex(1);
    expect(await lyrics.isRowCurrent(1)).toBe(true);

    // position_s=7.0 → 第 3 行（time_s=6 是最大的 <= 7.0 的）
    await appPage.evaluate(() => {
      const debug = (window as unknown as {
        __omniDebug?: { lyrics: { refreshCurrentLine: (pos: number) => void } };
      }).__omniDebug;
      debug!.lyrics.refreshCurrentLine(7.0);
    });
    await lyrics.waitForCurrentIndex(3);
    expect(await lyrics.isRowCurrent(3)).toBe(true);
  });

  test("逐字歌词显示（lyrics-word + lyrics-word-current 高亮）", async ({
    appPage,
    fakeTauri,
  }) => {
    // LRC_WORD_BY_WORD_RESULT：1 行 "晴天" + words=["晴"@1.0, "天"@1.5]
    fakeTauri.override(CMD.MUSIC_TOOL, makeMusicHandlerWithSong());
    fakeTauri.override(CMD.LYRICS_TOOL, makeLyricsHandler(() => LRC_WORD_BY_WORD_RESULT));

    const lyrics = new LyricsDisplay(appPage);
    await fetchPlayerStateViaDebug(appPage);

    await lyrics.waitForMounted();
    await lyrics.waitForEmpty(false);

    // 等待 lyricsStore.currentLyrics 已写入（1 行 parsed）。
    // LyricsDisplay 的 useEffect 在挂载时即触发 refreshCurrentLine(positionS)，
    // 但此时 currentLyrics=null（fetchLyrics 尚未完成）→ no-op。fetchLyrics 完成后
    // 写入 currentLyrics + currentIndex=-1，但 useEffect 不会因 currentLyrics 变化重跑。
    // 故测试需手动调 refreshCurrentLine 驱动当前行 + 逐字高亮。
    await expect
      .poll(async () => await lyrics.getRows().count())
      .toBe(LRC_WORD_BY_WORD_RESULT.parsed.length);

    // position_s=1.0 → currentIndex=0（第 0 行 time_s=1.0 <= 1.0）
    //                       + currentWordIndex=0（"晴"@1.0 <= 1.0）
    await appPage.evaluate(() => {
      const debug = (window as unknown as {
        __omniDebug?: { lyrics: { refreshCurrentLine: (pos: number) => void } };
      }).__omniDebug;
      debug!.lyrics.refreshCurrentLine(1.0);
    });
    await lyrics.waitForCurrentIndex(0);

    // 当前行（第 0 行）渲染 2 个 lyrics-word span（"晴" + "天"）
    const wordCount = await lyrics.getRowWords(0).count();
    expect(wordCount).toBe(LRC_WORD_BY_WORD_RESULT.parsed[0]!.words!.length);

    // currentWordIndex=0 → "晴" 高亮（lyrics-word-current 仅 1 个）
    await expect
      .poll(async () => await lyrics.getCurrentWord().count())
      .toBe(1);

    // position_s=1.6 → currentWordIndex=1（"天"@1.5 <= 1.6）
    await appPage.evaluate(() => {
      const debug = (window as unknown as {
        __omniDebug?: { lyrics: { refreshCurrentLine: (pos: number) => void } };
      }).__omniDebug;
      debug!.lyrics.refreshCurrentLine(1.6);
    });
    await expect
      .poll(async () => await lyrics.getCurrentWord().count())
      .toBe(1);
  });

  test("翻译歌词显示（lyrics-row-translation span）", async ({
    appPage,
    fakeTauri,
  }) => {
    // LRC_WITH_TRANSLATION_RESULT：1 行 "Hello" + translation="你好"
    fakeTauri.override(CMD.MUSIC_TOOL, makeMusicHandlerWithSong());
    fakeTauri.override(CMD.LYRICS_TOOL, makeLyricsHandler(() => LRC_WITH_TRANSLATION_RESULT));

    const lyrics = new LyricsDisplay(appPage);
    await fetchPlayerStateViaDebug(appPage);

    await lyrics.waitForMounted();
    await lyrics.waitForEmpty(false);

    // 第 0 行应有翻译 span，文本为 "你好"
    const translation = await lyrics.getRowTranslation(0);
    expect(translation).not.toBeNull();
    expect(translation).toContain("你好");
  });

  test("无歌词时显示纯文本（source=none + data-empty=true 占位）", async ({
    appPage,
    fakeTauri,
  }) => {
    // EMPTY_LYRICS_RESULT：lyrics=null / source=none / parsed=[]
    fakeTauri.override(CMD.MUSIC_TOOL, makeMusicHandlerWithSong());
    fakeTauri.override(CMD.LYRICS_TOOL, makeLyricsHandler(() => EMPTY_LYRICS_RESULT));

    const lyrics = new LyricsDisplay(appPage);
    await fetchPlayerStateViaDebug(appPage);

    await lyrics.waitForMounted();
    // 空 LyricsResult（parsed=[]）→ LyricsDisplay 渲染空态占位
    await lyrics.waitForEmpty(true);

    // data-source 应为 "none"（EMPTY_LYRICS_RESULT.source）
    expect(await lyrics.getSource()).toBe("none");
  });

  test("lyrics_tool IPC 失败 → 降级显示空态（不 crash）", async ({
    appPage,
    fakeTauri,
  }) => {
    // 监听未捕获的 pageerror
    const errors: string[] = [];
    appPage.on("pageerror", (err) => {
      errors.push(err.message);
    });

    // music_tool 正常返回 current_song，但 lyrics_tool 返回错误信封
    fakeTauri.override(CMD.MUSIC_TOOL, makeMusicHandlerWithSong());
    fakeTauri.override(CMD.LYRICS_TOOL, () =>
      JSON.stringify({
        ok: false,
        error: { code: "E_CLI_FAILED", message: "omni_lyrics CLI 不可用" },
      }),
    );

    const lyrics = new LyricsDisplay(appPage);
    await fetchPlayerStateViaDebug(appPage);

    // LyricsDisplay 应挂载（current_song 非 null），但 lyrics 为空 → data-empty="true"
    await lyrics.waitForMounted();
    await lyrics.waitForEmpty(true);

    // 等待 lyrics_tool 调用到达（即使失败也记录 calls）
    await expect
      .poll(() => fakeTauri.callsFor(CMD.LYRICS_TOOL).length)
      .toBeGreaterThanOrEqual(1);

    // 不应有未捕获的 pageerror（store callTool 吞错）
    expect(errors).toEqual([]);
  });

  test("切歌时歌词重新获取（current_song.id 变化 → fetchLyrics 重跑）", async ({
    appPage,
    fakeTauri,
  }) => {
    // 第一首：晴天（song_1）→ lyrics_get 返回 LRC_STANDARD_RESULT
    // 第二首：稻香（song_2）→ lyrics_get 返回 MULTI_LINE_RESULT（5 行）
    let currentSongId = "song_1";
    fakeTauri.override(CMD.MUSIC_TOOL, (args) => {
      const tool = String(args.tool ?? "");
      if (tool === "music_get_player_state") {
        // 第一次返回晴天，后续返回稻香
        const song =
          currentSongId === "song_1"
            ? SONG_QINGTIAN
            : { ...SONG_QINGTIAN, id: "song_2", name: "稻香" };
        return JSON.stringify(
          okEnvelope({
            ...PLAYER_STATE_PLAYING,
            current_song: song,
            queue: [song],
          }),
        );
      }
      return JSON.stringify(okEnvelope({}));
    });

    let lyricsCallCount = 0;
    fakeTauri.override(CMD.LYRICS_TOOL, (args) => {
      const tool = String(args.tool ?? "");
      if (tool === "lyrics_get") {
        lyricsCallCount += 1;
        // 第一次调用返回 3 行，第二次返回 5 行
        const result = lyricsCallCount === 1 ? LRC_STANDARD_RESULT : MULTI_LINE_RESULT;
        return JSON.stringify(okEnvelope(result));
      }
      return JSON.stringify(okEnvelope({}));
    });

    const lyrics = new LyricsDisplay(appPage);

    // 第一首：拉取晴天 → LyricsDisplay 显示 3 行
    await fetchPlayerStateViaDebug(appPage);
    await lyrics.waitForMounted();
    await lyrics.waitForEmpty(false);
    await expect
      .poll(async () => await lyrics.getRows().count())
      .toBe(LRC_STANDARD_RESULT.parsed.length);

    // 切歌到稻香：再次 fetchPlayerState → current_song.id="song_2" →
    // bindLyricsSync.onChange 检测 songId 变化 → fetchLyrics("song_2") →
    // lyrics_get 第二次调用 → 返回 MULTI_LINE_RESULT（5 行）
    currentSongId = "song_2";
    await fetchPlayerStateViaDebug(appPage);

    // 等待行数变为 5（切歌后重新 fetchLyrics + 渲染）
    await expect
      .poll(async () => await lyrics.getRows().count())
      .toBe(MULTI_LINE_RESULT.parsed.length);

    // 断言 lyrics_get 被调用 2 次（song_1 + song_2）
    const lyricsGetCalls = fakeTauri
      .callsFor(CMD.LYRICS_TOOL)
      .filter((c) => (c.args as { tool?: string }).tool === "lyrics_get");
    expect(lyricsGetCalls.length).toBe(2);
    expect(lyricsGetCalls[0]?.args).toMatchObject({
      tool: "lyrics_get",
      args: { song_id: "song_1" },
    });
    expect(lyricsGetCalls[1]?.args).toMatchObject({
      tool: "lyrics_get",
      args: { song_id: "song_2" },
    });
  });
});
