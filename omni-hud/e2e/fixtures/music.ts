/**
 * Music 测试夹具（M17 音乐控制 E2E）。
 *
 * 与 src/store/musicStore.ts 的 Song / PlayerStateContract 类型对齐，
 * 覆盖空态 / 播放 / 暂停 / 队列 / 循环模式等关键状态。所有 fixture 为
 * music_tool IPC 返回的 ``{ok: true, data: ...}`` 信封的 data 部分，
 * spec 经 ``fakeTauri.override(CMD.MUSIC_TOOL, ...)`` 注入。
 *
 * 字段命名严格遵循 src/store/musicStore.ts 的 normalizePlayerState / normalizeSong
 * 归一化结果（snake_case），与 Rust 侧 serde 序列化 + Python to_dict 对齐——
 * 保证 E2E 注入的负载与真实 Python omni_music 工具返回的字段结构完全一致。
 */
import type {
  PlayerStateContract,
  RepeatMode,
  Song,
} from "../../src/store/musicStore";

/** 工具返回信封结构（与 src-tauri/src/music.rs parse_music_result 对齐）。 */
export interface MusicToolEnvelope<T> {
  readonly ok: boolean;
  readonly data?: T;
  readonly error?: { readonly code: string; readonly message: string };
}

/**
 * 构造成功信封：包一层 ``{ok: true, data}``。
 *
 * musicStore.defaultInvoker 解析 invoke<string> 为 JSON 后取 .ok / .data，
 * 故 fixture 必须以信封形式注入 router。
 */
export function okEnvelope<T>(data: T): MusicToolEnvelope<T> {
  return { ok: true, data };
}

/** 构造失败信封：包一层 ``{ok: false, error: {code, message}}``。 */
export function errEnvelope(code: string, message: string): MusicToolEnvelope<never> {
  return { ok: false, error: { code, message } };
}

// ---------------------------------------------------------------------------
// Song fixtures
// ---------------------------------------------------------------------------

/**
 * 构造 Song fixture。
 *
 * @param overrides 覆盖字段（id / name / artists / album / duration_s / url / cover_url / source）
 */
function makeSong(overrides: Partial<Song> = {}): Song {
  return {
    id: "song_1",
    name: "晴天",
    artists: ["周杰伦"],
    album: "叶惠美",
    duration_s: 269,
    url: "https://example.com/song_1.mp3",
    lyrics: null,
    cover_url: "https://example.com/cover_1.jpg",
    source: "netease",
    ...overrides,
  };
}

/** 单曲 fixture 1：晴天 / 周杰伦 / 269s / 网易云。 */
export const SONG_QINGTIAN: Song = makeSong();

/** 单曲 fixture 2：稻香 / 周杰伦 / 223s / 网易云。 */
export const SONG_DAOXIANG: Song = makeSong({
  id: "song_2",
  name: "稻香",
  album: "魔杰座",
  duration_s: 223,
  url: "https://example.com/song_2.mp3",
  cover_url: "https://example.com/cover_2.jpg",
});

/** 单曲 fixture 3：七里香 / 周杰伦 / 296s / QQ 音乐。 */
export const SONG_QILIXIANG: Song = makeSong({
  id: "song_3",
  name: "七里香",
  artists: ["周杰伦"],
  album: "七里香",
  duration_s: 296,
  url: "https://example.com/song_3.mp3",
  cover_url: "https://example.com/cover_3.jpg",
  source: "qqmusic",
});

/** 单曲 fixture 4：无封面 / 无专辑 / 无 URL（VIP 曲目场景）。 */
export const SONG_NO_COVER_NO_URL: Song = makeSong({
  id: "song_4",
  name: "VIP 限定曲目",
  artists: ["某歌手"],
  album: null,
  url: null,
  cover_url: null,
});

/**
 * 多曲队列 fixture：3 首歌曲（晴天 / 稻香 / 七里香），用于队列列表测试。
 */
export const QUEUE_THREE_SONGS: readonly Song[] = [
  SONG_QINGTIAN,
  SONG_DAOXIANG,
  SONG_QILIXIANG,
];

// ---------------------------------------------------------------------------
// PlayerStateContract fixtures
// ---------------------------------------------------------------------------

/**
 * 构造 PlayerStateContract fixture。
 *
 * @param overrides 覆盖字段
 */
function makePlayerState(
  overrides: Partial<PlayerStateContract> = {},
): PlayerStateContract {
  return {
    queue: [SONG_QINGTIAN],
    current_index: 0,
    state: "playing",
    repeat_mode: "sequence",
    position_s: 30,
    current_song: SONG_QINGTIAN,
    ...overrides,
  };
}

/**
 * 空播放器状态：无队列、无当前曲目、stopped。
 *
 * 用于测试「默认无曲目时显示空态」。
 */
export const PLAYER_STATE_EMPTY: PlayerStateContract = makePlayerState({
  queue: [],
  current_index: -1,
  state: "stopped",
  repeat_mode: "sequence",
  position_s: 0,
  current_song: null,
});

/** 播放中状态：晴天 / position=30s / repeat=sequence。 */
export const PLAYER_STATE_PLAYING: PlayerStateContract = makePlayerState({
  state: "playing",
  position_s: 30,
});

/** 暂停状态：晴天 / position=45s / repeat=sequence。 */
export const PLAYER_STATE_PAUSED: PlayerStateContract = makePlayerState({
  state: "paused",
  position_s: 45,
});

/** 播放中 + 3 首队列：current_index=0（晴天）。 */
export const PLAYER_STATE_PLAYING_QUEUE: PlayerStateContract = makePlayerState({
  queue: [...QUEUE_THREE_SONGS],
  current_index: 0,
  state: "playing",
});

/** 播放中 + 3 首队列 + current_index=1（稻香，第二首）。 */
export const PLAYER_STATE_PLAYING_QUEUE_INDEX1: PlayerStateContract = makePlayerState({
  queue: [...QUEUE_THREE_SONGS],
  current_index: 1,
  current_song: SONG_DAOXIANG,
  state: "playing",
});

/** 4 种循环模式 fixture 列表，用于参数化测试。 */
export const ALL_REPEAT_MODES: readonly RepeatMode[] = [
  "sequence",
  "list_loop",
  "single",
  "random",
];

/**
 * 不同循环模式对应的播放器状态 fixture。
 *
 * 每种模式保持 current_song 一致（晴天），仅 repeat_mode 字段变化，
 * 用于测试「循环模式切换 → data-repeat-mode 属性变化」。
 */
export function playerStateWithRepeatMode(mode: RepeatMode): PlayerStateContract {
  return makePlayerState({ repeat_mode: mode, state: "playing" });
}
