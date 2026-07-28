/**
 * Lyrics 测试夹具（M18 歌词同步 E2E）。
 *
 * 与 src/store/lyricsStore.ts 的 LyricsResult / LyricsLine / Word 类型对齐，
 * 覆盖标准 LRC / 逐字歌词 / 翻译歌词 / 纯文本歌词 / 空歌词等关键场景。
 *
 * 所有 fixture 为 lyrics_tool IPC 返回的 ``{ok: true, data: ...}`` 信封的
 * data 部分（LyricsResult 结构：lyrics 原始文本 + source 来源 + parsed 解析行）。
 * spec 经 ``fakeTauri.override(CMD.LYRICS_TOOL, handler)`` 注入，
 * handler 返回 JSON 字符串（与 music_tool 同款：lyricsStore.defaultInvoker
 * 调 ``invoke<string>`` + ``JSON.parse`` 解析）。
 */
import type {
  LyricsLine,
  LyricsResult,
  LyricsSource,
  Word,
} from "../../src/store/lyricsStore";

/** 工具返回信封结构（与 src-tauri/src/lyrics.rs parse_lyrics_result 对齐）。 */
export interface LyricsToolEnvelope<T> {
  readonly ok: boolean;
  readonly data?: T;
  readonly error?: { readonly code: string; readonly message: string };
}

/** 构造成功信封：``{ok: true, data}``。 */
export function okEnvelope<T>(data: T): LyricsToolEnvelope<T> {
  return { ok: true, data };
}

/** 构造失败信封：``{ok: false, error: {code, message}}``。 */
export function errEnvelope(code: string, message: string): LyricsToolEnvelope<never> {
  return { ok: false, error: { code, message } };
}

// ---------------------------------------------------------------------------
// Word / Line fixtures
// ---------------------------------------------------------------------------

/** 构造 Word fixture（逐字歌词单字片段）。 */
function makeWord(time_s: number, char: string): Word {
  return { time_s, char };
}

/** 构造 LyricsLine fixture。 */
function makeLine(overrides: Partial<LyricsLine> = {}): LyricsLine {
  return {
    time_s: 1.0,
    text: "故事的小黄花",
    translation: null,
    words: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// 标准 LRC（带时间轴，非逐字）
// ---------------------------------------------------------------------------

/**
 * 标准 LRC 原始文本：3 行带时间轴的歌词。
 *
 * 用于测试 LRC 解析正确显示歌词行 + position_s 变化时当前行高亮切换。
 */
export const LRC_STANDARD_TEXT = `[00:01.00]故事的小黄花
[00:05.00]从出生那年就飘着
[00:09.00]少年的快乐一直这么简单`;

/** 标准 LRC 解析后的 3 行（与 LRC_STANDARD_TEXT 对应）。 */
export const LRC_STANDARD_PARSED: readonly LyricsLine[] = [
  makeLine({ time_s: 1.0, text: "故事的小黄花" }),
  makeLine({ time_s: 5.0, text: "从出生那年就飘着" }),
  makeLine({ time_s: 9.0, text: "少年的快乐一直这么简单" }),
];

/** 标准 LRC 完整 LyricsResult（local_file 来源）。 */
export const LRC_STANDARD_RESULT: LyricsResult = {
  lyrics: LRC_STANDARD_TEXT,
  source: "local_file",
  parsed: [...LRC_STANDARD_PARSED],
};

// ---------------------------------------------------------------------------
// 逐字歌词（带 words 数组）
// ---------------------------------------------------------------------------

/**
 * 逐字歌词行：text="晴天" + words=["晴","天"] 各带时间轴。
 *
 * 用于测试逐字高亮：position_s 变化时 currentWordIndex 切换。
 */
export const WORD_LINE: LyricsLine = makeLine({
  time_s: 1.0,
  text: "晴天",
  words: [
    makeWord(1.0, "晴"),
    makeWord(1.5, "天"),
  ],
});

/** 逐字歌词 LyricsResult：1 行逐字歌词。 */
export const LRC_WORD_BY_WORD_RESULT: LyricsResult = {
  lyrics: "[00:01.00]晴[00:01.50]天",
  source: "online",
  parsed: [WORD_LINE],
};

// ---------------------------------------------------------------------------
// 翻译歌词（带 translation 字段）
// ---------------------------------------------------------------------------

/**
 * 翻译歌词行：text="Hello" + translation="你好"。
 *
 * 用于测试翻译渲染：LyricsRow 在原文下方渲染翻译 span。
 */
export const TRANSLATION_LINE: LyricsLine = makeLine({
  time_s: 1.0,
  text: "Hello",
  translation: "你好",
  words: null,
});

/** 翻译歌词 LyricsResult：1 行带翻译的歌词。 */
export const LRC_WITH_TRANSLATION_RESULT: LyricsResult = {
  lyrics: "[00:01.00]Hello",
  source: "online",
  parsed: [TRANSLATION_LINE],
};

// ---------------------------------------------------------------------------
// 纯文本歌词（无时间轴）
// ---------------------------------------------------------------------------

/**
 * 纯文本歌词（无时间轴）：parsed 中每行 time_s=0.0。
 *
 * 用于测试无 LRC 时间轴时的降级显示——所有行 time_s=0 → position_s=0
 * 时第一行高亮。
 */
export const PLAIN_TEXT_LINES: readonly LyricsLine[] = [
  makeLine({ time_s: 0.0, text: "这是一首纯文本歌词" }),
  makeLine({ time_s: 0.0, text: "没有时间轴" }),
  makeLine({ time_s: 0.0, text: "全部 time_s=0" }),
];

/** 纯文本歌词 LyricsResult。 */
export const PLAIN_TEXT_RESULT: LyricsResult = {
  lyrics: "这是一首纯文本歌词\n没有时间轴\n全部 time_s=0",
  source: "embedded",
  parsed: [...PLAIN_TEXT_LINES],
};

// ---------------------------------------------------------------------------
// 空歌词（source=none）
// ---------------------------------------------------------------------------

/** 空歌词 LyricsResult：无歌词 / source=none / parsed=[]。 */
export const EMPTY_LYRICS_RESULT: LyricsResult = {
  lyrics: null,
  source: "none",
  parsed: [],
};

// ---------------------------------------------------------------------------
// 多行带时间轴歌词（用于切歌 / 自动滚动测试）
// ---------------------------------------------------------------------------

/**
 * 5 行带时间轴的歌词，时间间隔 2s。
 *
 * 用于测试 position_s 变化驱动 currentIndex 切换（每 2s 切一行）。
 */
export const MULTI_LINE_PARSED: readonly LyricsLine[] = [
  makeLine({ time_s: 0.0, text: "第 1 行" }),
  makeLine({ time_s: 2.0, text: "第 2 行" }),
  makeLine({ time_s: 4.0, text: "第 3 行" }),
  makeLine({ time_s: 6.0, text: "第 4 行" }),
  makeLine({ time_s: 8.0, text: "第 5 行" }),
];

/** 多行歌词 LyricsResult。 */
export const MULTI_LINE_RESULT: LyricsResult = {
  lyrics: "[00:00.00]第 1 行\n[00:02.00]第 2 行\n[00:04.00]第 3 行\n[00:06.00]第 4 行\n[00:08.00]第 5 行",
  source: "local_file",
  parsed: [...MULTI_LINE_PARSED],
};

// ---------------------------------------------------------------------------
// lyrics_set_offset 返回数据
// ---------------------------------------------------------------------------

/** lyrics_set_offset 工具返回的归一化偏移数据。 */
export const OFFSET_RESULT = { offset_s: 0.5 };

/** 构造 lyrics_get handler 返回的 LyricsResult data。 */
export function makeLyricsGetHandlerData(
  result: LyricsResult = LRC_STANDARD_RESULT,
): unknown {
  return result;
}
