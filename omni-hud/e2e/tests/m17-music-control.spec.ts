/**
 * M17 音乐控制 E2E 测试（9 用例）。
 *
 * 覆盖维度：
 * 1. 默认无曲目时显示空态（PlayControlBar / NowPlaying / QueueList 三处占位）
 * 2. music_tool IPC 返回曲目 → NowPlaying 显示标题 / 艺术家
 * 3. 点击播放按钮 → music_tool 调用 music_resume
 * 4. 点击暂停 → music_tool 调用 music_pause
 * 5. 点击下一首 → music_tool 调用 music_next
 * 6. 点击上一首 → music_tool 调用 music_previous
 * 7. 队列显示多首歌曲（data-queue-length=3）
 * 8. 循环模式切换（sequence → list_loop → single → random）
 * 9. music_tool IPC 失败 → UI 降级不 crash（error 写入 store 但组件仍渲染）
 *
 * 路由策略：
 * - 经 ``__omniDebug.music.fetchPlayerState()`` 触发 musicStore 拉取状态
 * - ``fakeTauri.override(CMD.MUSIC_TOOL, handler)`` 注入 fixture 响应：
 *   handler 按 args.tool 分发到对应 fixture（music_get_player_state / music_play 等）
 * - ``fakeTauri.callsFor(CMD.MUSIC_TOOL)`` 断言 invoke 调用与 args
 *
 * 重要：musicStore 的 invoker 走 src/lib/window.ts isTauri() → 经
 * ``__TAURI_INTERNALS__.invoke('music_tool', {tool, args})`` 调 Node router。
 * fakeTauri 的 router 收到 invoke 后按 args.tool 字段分发——所以 handler
 * 需读取 ``args.tool`` 来区分不同 music_* 工具，返回对应的 fixture data。
 */
import { test, expect } from "../support/fixture";
import { CMD } from "../support/env";
import { HudApp } from "../pages/HudApp";
import { NowPlaying } from "../pages/music/NowPlaying";
import { PlayControlBar } from "../pages/music/PlayControlBar";
import { QueueList } from "../pages/music/QueueList";
import {
  okEnvelope,
  PLAYER_STATE_EMPTY,
  PLAYER_STATE_PAUSED,
  PLAYER_STATE_PLAYING,
  PLAYER_STATE_PLAYING_QUEUE,
  PLAYER_STATE_PLAYING_QUEUE_INDEX1,
  playerStateWithRepeatMode,
  SONG_QINGTIAN,
} from "../fixtures/music";

/**
 * 触发 musicStore.fetchPlayerState() 拉取后端状态。
 *
 * 经 ``__omniDebug.music.fetchPlayerState()`` 调用 store action（DEV 模式下
 * App.tsx useEffect 暴露的入口）。先等待 __omniDebug 就绪，避免 effect 未跑
 * 时 evaluate 返回 undefined 导致 fetchPlayerState 不执行。
 */
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

/**
 * 构造 music_tool handler：按 args.tool 分发到 fixture 响应。
 *
 * musicStore.defaultInvoker 调用 ``invoke<string>('music_tool', {tool, args})``，
 * 然后 ``JSON.parse(raw)`` 解析。故 handler 必须返回 JSON 字符串（与 Rust 侧
 * ``music_tool`` command 返回 ``serde_json::Value`` 经 Tauri IPC 序列化为
 * JSON 字符串的行为对齐）——若返回对象，``JSON.parse("[object Object]")`` 会抛
 * "is not valid JSON" 错误，store 降级为 error 态。
 *
 * router 收到的 invokeArgs 为 ``{tool, args}`` 字典（camelCase key 与 Rust 对齐）。
 * handler 读取 ``invokeArgs.tool`` 决定返回哪个 fixture data。
 *
 * @param getPlayerState 返回 music_get_player_state 的 fixture data
 */
function makeMusicHandler(
  getPlayerState: () => unknown = () => PLAYER_STATE_PLAYING,
): (args: Record<string, unknown>) => unknown {
  return (args) => {
    const tool = String(args.tool ?? "");
    switch (tool) {
      case "music_get_player_state":
        return JSON.stringify(okEnvelope(getPlayerState()));
      case "music_play":
      case "music_pause":
      case "music_resume":
      case "music_stop":
      case "music_next":
      case "music_previous":
      case "music_seek":
      case "music_set_repeat_mode":
        // 控制 action 默认返回 ok 空信封；调用后 store 会再调
        // music_get_player_state 刷新状态——这里也返回同一份 fixture
        return JSON.stringify(okEnvelope({}));
      default:
        return JSON.stringify(okEnvelope({}));
    }
  };
}

test.describe("M17 音乐控制", () => {
  test("默认无曲目时显示空态（PlayControlBar / NowPlaying / QueueList 三处占位）", async ({
    appPage,
  }) => {
    // Full 模式下 App.tsx 必挂载三个音乐组件；初始 playerState=null →
    // 各组件 song=null / queue=[] → 渲染 data-empty="true" 占位
    const playControlBar = new PlayControlBar(appPage);
    const nowPlaying = new NowPlaying(appPage);
    const queueList = new QueueList(appPage);

    await playControlBar.waitForMounted();
    await nowPlaying.waitForMounted();
    await queueList.waitForMounted();

    await playControlBar.waitForEmpty(true);
    await nowPlaying.waitForEmpty(true);
    await queueList.waitForEmpty(true);
  });

  test("music_tool IPC 返回曲目 → NowPlaying 显示标题 / 艺术家", async ({
    appPage,
    fakeTauri,
  }) => {
    // 注入 music_tool handler：music_get_player_state 返回 PLAYER_STATE_PLAYING
    // （晴天 / 周杰伦 / playing / position=30s）
    fakeTauri.override(CMD.MUSIC_TOOL, makeMusicHandler(() => PLAYER_STATE_PLAYING));

    const nowPlaying = new NowPlaying(appPage);
    await nowPlaying.waitForMounted();

    // 经 __omniDebug.music.fetchPlayerState() 触发 store 拉取 →
    // musicStore.defaultInvoker 调 invoke('music_tool', {tool:'music_get_player_state'})
    // → router 返回 fixture data → normalizePlayerState 写入 playerState
    // → NowPlaying 重新渲染显示曲目信息
    await fetchPlayerStateViaDebug(appPage);

    await nowPlaying.waitForEmpty(false);
    await nowPlaying.waitForTitle(SONG_QINGTIAN.name);
    await nowPlaying.waitForArtistsContaining(SONG_QINGTIAN.artists[0]!);

    // 断言 music_tool IPC 被调用（fetchPlayerState 调用 music_get_player_state）
    const calls = fakeTauri.callsFor(CMD.MUSIC_TOOL);
    expect(calls.length).toBeGreaterThanOrEqual(1);
    expect(calls[0]?.args).toMatchObject({
      tool: "music_get_player_state",
    });
  });

  test("点击播放按钮 → music_tool 调用 music_resume", async ({
    appPage,
    fakeTauri,
  }) => {
    // 先注入 paused 状态（playing=false → 点击触发 resume 而非 pause）
    fakeTauri.override(
      CMD.MUSIC_TOOL,
      makeMusicHandler(() => PLAYER_STATE_PAUSED),
    );

    const playControlBar = new PlayControlBar(appPage);
    const nowPlaying = new NowPlaying(appPage);
    await playControlBar.waitForMounted();

    await fetchPlayerStateViaDebug(appPage);

    await playControlBar.waitForEmpty(false);
    await playControlBar.waitForPlayerState("paused");

    // 清空 calls 日志，确保后续断言只针对点击触发的调用
    fakeTauri.callsFor; // 触发 getter，无副作用
    const callsBefore = fakeTauri.callsFor(CMD.MUSIC_TOOL).length;

    // 点击播放按钮（paused → resume）
    await playControlBar.clickPlayPause();

    // 等待 music_resume 调用到达
    await expect
      .poll(() => fakeTauri.callsFor(CMD.MUSIC_TOOL).length)
      .toBeGreaterThan(callsBefore);

    // 找到 music_resume 调用记录
    const calls = fakeTauri.callsFor(CMD.MUSIC_TOOL);
    const resumeCall = calls.find((c) => (c.args as { tool?: string }).tool === "music_resume");
    expect(resumeCall).toBeDefined();
  });

  test("点击暂停 → music_tool 调用 music_pause", async ({
    appPage,
    fakeTauri,
  }) => {
    // 注入 playing 状态（playing=true → 点击触发 pause）
    fakeTauri.override(
      CMD.MUSIC_TOOL,
      makeMusicHandler(() => PLAYER_STATE_PLAYING),
    );

    const playControlBar = new PlayControlBar(appPage);
    await playControlBar.waitForMounted();

    await fetchPlayerStateViaDebug(appPage);

    await playControlBar.waitForEmpty(false);
    await playControlBar.waitForPlayerState("playing");

    const callsBefore = fakeTauri.callsFor(CMD.MUSIC_TOOL).length;

    await playControlBar.clickPlayPause();

    await expect
      .poll(() => fakeTauri.callsFor(CMD.MUSIC_TOOL).length)
      .toBeGreaterThan(callsBefore);

    const calls = fakeTauri.callsFor(CMD.MUSIC_TOOL);
    const pauseCall = calls.find((c) => (c.args as { tool?: string }).tool === "music_pause");
    expect(pauseCall).toBeDefined();
  });

  test("点击下一首 → music_tool 调用 music_next", async ({
    appPage,
    fakeTauri,
  }) => {
    fakeTauri.override(
      CMD.MUSIC_TOOL,
      makeMusicHandler(() => PLAYER_STATE_PLAYING),
    );

    const playControlBar = new PlayControlBar(appPage);
    await playControlBar.waitForMounted();

    await fetchPlayerStateViaDebug(appPage);

    await playControlBar.waitForEmpty(false);

    const callsBefore = fakeTauri.callsFor(CMD.MUSIC_TOOL).length;

    await playControlBar.clickNext();

    await expect
      .poll(() => fakeTauri.callsFor(CMD.MUSIC_TOOL).length)
      .toBeGreaterThan(callsBefore);

    const calls = fakeTauri.callsFor(CMD.MUSIC_TOOL);
    const nextCall = calls.find((c) => (c.args as { tool?: string }).tool === "music_next");
    expect(nextCall).toBeDefined();
  });

  test("点击上一首 → music_tool 调用 music_previous", async ({
    appPage,
    fakeTauri,
  }) => {
    fakeTauri.override(
      CMD.MUSIC_TOOL,
      makeMusicHandler(() => PLAYER_STATE_PLAYING),
    );

    const playControlBar = new PlayControlBar(appPage);
    await playControlBar.waitForMounted();

    await fetchPlayerStateViaDebug(appPage);

    await playControlBar.waitForEmpty(false);

    const callsBefore = fakeTauri.callsFor(CMD.MUSIC_TOOL).length;

    await playControlBar.clickPrevious();

    await expect
      .poll(() => fakeTauri.callsFor(CMD.MUSIC_TOOL).length)
      .toBeGreaterThan(callsBefore);

    const calls = fakeTauri.callsFor(CMD.MUSIC_TOOL);
    const prevCall = calls.find((c) => (c.args as { tool?: string }).tool === "music_previous");
    expect(prevCall).toBeDefined();
  });

  test("队列显示多首歌曲（data-queue-length=3）", async ({
    appPage,
    fakeTauri,
  }) => {
    // 注入 3 首队列的播放器状态
    fakeTauri.override(
      CMD.MUSIC_TOOL,
      makeMusicHandler(() => PLAYER_STATE_PLAYING_QUEUE),
    );

    const queueList = new QueueList(appPage);
    await queueList.waitForMounted();

    await fetchPlayerStateViaDebug(appPage);

    // 等待队列加载：data-empty=false + data-queue-length=3
    await queueList.waitForEmpty(false);
    await queueList.waitForQueueLength(3);

    // 验证行数与 song-id 正确
    expect(await queueList.getRows().count()).toBe(3);
    expect(await queueList.getRowSongId(0)).toBe(PLAYER_STATE_PLAYING_QUEUE.queue[0]!.id);
    expect(await queueList.getRowSongId(1)).toBe(PLAYER_STATE_PLAYING_QUEUE.queue[1]!.id);
    expect(await queueList.getRowSongId(2)).toBe(PLAYER_STATE_PLAYING_QUEUE.queue[2]!.id);

    // current_index=0 → 第 0 行标记为当前
    expect(await queueList.isRowCurrent(0)).toBe(true);
    expect(await queueList.isRowCurrent(1)).toBe(false);
  });

  test("循环模式切换（sequence → list_loop → single → random）", async ({
    appPage,
    fakeTauri,
  }) => {
    // 4 种循环模式的播放器状态，按切换顺序返回
    const modes = ["sequence", "list_loop", "single", "random"] as const;
    let modeIdx = 0;
    fakeTauri.override(CMD.MUSIC_TOOL, (args) => {
      const tool = String(args.tool ?? "");
      if (tool === "music_get_player_state") {
        // 每次刷新返回当前 idx 对应的模式（首次返回 sequence）
        const mode = modes[modeIdx]!;
        return JSON.stringify(okEnvelope(playerStateWithRepeatMode(mode)));
      }
      if (tool === "music_set_repeat_mode") {
        // 切换模式：idx 前进一位（mod 4）
        modeIdx = (modeIdx + 1) % modes.length;
        return JSON.stringify(okEnvelope({}));
      }
      return JSON.stringify(okEnvelope({}));
    });

    const playControlBar = new PlayControlBar(appPage);
    await playControlBar.waitForMounted();

    // 首次 fetch 拉取初始 sequence 模式
    await fetchPlayerStateViaDebug(appPage);

    await playControlBar.waitForEmpty(false);
    await playControlBar.waitForRepeatMode("sequence");

    // 点击 1：sequence → list_loop
    await playControlBar.clickRepeat();
    await playControlBar.waitForRepeatMode("list_loop");

    // 点击 2：list_loop → single
    await playControlBar.clickRepeat();
    await playControlBar.waitForRepeatMode("single");

    // 点击 3：single → random
    await playControlBar.clickRepeat();
    await playControlBar.waitForRepeatMode("random");

    // 断言 music_set_repeat_mode 被调用 3 次，每次 args.mode 对应目标模式
    const setModeCalls = fakeTauri
      .callsFor(CMD.MUSIC_TOOL)
      .filter((c) => (c.args as { tool?: string }).tool === "music_set_repeat_mode");
    expect(setModeCalls.length).toBe(3);
    expect(setModeCalls[0]?.args).toMatchObject({ tool: "music_set_repeat_mode", args: { mode: "list_loop" } });
    expect(setModeCalls[1]?.args).toMatchObject({ tool: "music_set_repeat_mode", args: { mode: "single" } });
    expect(setModeCalls[2]?.args).toMatchObject({ tool: "music_set_repeat_mode", args: { mode: "random" } });
  });

  test("music_tool IPC 失败 → UI 降级不 crash（store 写 error，组件仍渲染空态）", async ({
    appPage,
    fakeTauri,
  }) => {
    // 监听未捕获的 pageerror（store 应吞错，不抛 unhandled rejection）
    const errors: string[] = [];
    appPage.on("pageerror", (err) => {
      errors.push(err.message);
    });

    // 注入失败 handler：所有 music_tool 调用返回错误信封（JSON 字符串）
    fakeTauri.override(CMD.MUSIC_TOOL, () =>
      JSON.stringify({
        ok: false,
        error: { code: "E_CLI_FAILED", message: "omni_music CLI 不可用" },
      }),
    );

    const playControlBar = new PlayControlBar(appPage);
    const nowPlaying = new NowPlaying(appPage);
    const queueList = new QueueList(appPage);
    await playControlBar.waitForMounted();

    // 触发 fetchPlayerState → 调用 music_get_player_state → 返回错误信封
    // → store.callTool 写 error 状态、playerState 保持 null
    await fetchPlayerStateViaDebug(appPage);

    // 等待 music_tool 调用到达（即使失败也记录 calls）
    await expect
      .poll(() => fakeTauri.callsFor(CMD.MUSIC_TOOL).length)
      .toBeGreaterThanOrEqual(1);

    // 组件应仍渲染（不 crash），且因 playerState=null 显示空态
    await playControlBar.waitForEmpty(true);
    await nowPlaying.waitForEmpty(true);
    await queueList.waitForEmpty(true);

    // 不应有未捕获的 pageerror（store callTool 吞错）
    expect(errors).toEqual([]);
  });
});
