/**
 * 歌词同步 store（M18 前端）。
 *
 * 框架无关订阅模式（与 musicStore / agentStore 同款），React 侧经
 * ``useSyncExternalStore`` 绑定。维护：
 *
 * 1. ``currentLyrics``：来自后端 ``LyricsResult.to_dict()``（lyrics_chain.py），
 *    含 ``lyrics`` 原始文本 / ``source`` 来源标识 / ``parsed`` 解析后的行列表。
 *    前端只读消费，不本地修改——后端是唯一权威源。
 * 2. ``currentIndex`` / ``currentWordIndex``：**本地二分查找**定位当前行 + 逐字
 *    高亮，**不每次 position 变化都打 IPC**（性能红线，timeupdate 每秒多次触发）。
 *    二分逻辑镜像 ``lyrics_sync.py`` 的 ``find_current_line`` / ``find_current_word``，
 *    含用户偏移叠加（``eff = position + offset``）。
 * 3. ``offsetS``：用户全局偏移（正数提前、负数延后），经 ``lyrics_set_offset`` 持久化
 *    到后端 ``LyricsSync`` 进程内单例。
 *
 * IPC 通道（D17.1 同款）：经通用 ``lyrics_tool`` command 调 Rust → Python
 * omni_lyrics 工具（M18.5 后端）。工具返回 JSON 字符串
 * ``{"ok": true, "data": ...}``，store 侧解析 + 防御性归一化（IPC 边界不可信）。
 *
 * 非 Tauri 环境（vitest / 纯 web 预览）默认 invoker 返回 ``E_NOT_TAURI``，
 * store 呈现离线态而非报错刷屏；测试经 ``deps.invoker`` 注入 fake 即可。
 */
import { invoke } from "@tauri-apps/api/core";

import { isTauri } from "../lib/window";

// ---------------------------------------------------------------------------
// 状态契约（与 omni_lyrics/lrc_parser.py + lyrics_chain.py 对齐）
// ---------------------------------------------------------------------------

/** 后端 LyricsResult.source 枚举（lyrics_chain.py）。 */
export type LyricsSource = "local_file" | "embedded" | "online" | "none";

/** 逐字歌词的单字片段（对应后端 lrc_parser.Word.to_dict：``{time_s, text}``）。 */
export interface Word {
  /** 该字起始时间（秒）。 */
  readonly time_s: number;
  /** 字文本（后端字段为 text，前端语义化为 char）。 */
  readonly char: string;
}

/** 单行歌词（对应后端 lrc_parser.LyricsLine.to_dict）。 */
export interface LyricsLine {
  /** 行起始时间（秒）。 */
  readonly time_s: number;
  /** 行文本（逐字行时为各 word 文本拼接）。 */
  readonly text: string;
  /** 翻译文本；无翻译为 null。 */
  readonly translation: string | null;
  /** 逐字歌词的字片段列表；非逐字行为 null。 */
  readonly words: readonly Word[] | null;
}

/** 后端 LyricsResult.to_dict 归一化后的前端结构。 */
export interface LyricsResult {
  /** 原始歌词文本（LRC 或纯文本）；全部失败为 null。 */
  readonly lyrics: string | null;
  /** 命中的来源：local_file / embedded / online / none。 */
  readonly source: LyricsSource;
  /** 解析后的行列表（按 time_s 升序）；无歌词为空列表。 */
  readonly parsed: readonly LyricsLine[];
}

// ---------------------------------------------------------------------------
// IPC 边界（不可信数据归一化）
// ---------------------------------------------------------------------------

/** 工具返回的 JSON 字符串解析后结构。 */
export interface LyricsToolResult<T> {
  readonly ok: boolean;
  readonly data?: T;
  readonly error?: { readonly code: string; readonly message: string };
}

/**
 * 通用歌词工具调用器：经 ``invoke('lyrics_tool', {tool, args})`` 调 Rust → Python。
 * 返回解析后的 ``LyricsToolResult``；实现侧负责 JSON 解析与防御性归一化。
 */
export type LyricsInvoker = (
  tool: string,
  args?: Record<string, unknown>,
) => Promise<LyricsToolResult<unknown>>;

/** 默认 Tauri invoker：非 Tauri 环境降级为 E_NOT_TAURI（不抛错）。 */
async function defaultInvoker(
  tool: string,
  args?: Record<string, unknown>,
): Promise<LyricsToolResult<unknown>> {
  if (!isTauri()) {
    return {
      ok: false,
      error: { code: "E_NOT_TAURI", message: "非 Tauri 环境，歌词工具不可用" },
    };
  }
  try {
    // 后端返回 JSON 字符串 {"ok": true, "data": ...} / {"ok": false, "error": {...}}
    const raw = await invoke<string>("lyrics_tool", { tool, args: args ?? {} });
    const parsed = JSON.parse(raw) as LyricsToolResult<unknown>;
    return parsed;
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return { ok: false, error: { code: "E_IPC_FAILED", message } };
  }
}

function asRecord(raw: unknown): Record<string, unknown> | null {
  return raw !== null && typeof raw === "object" ? (raw as Record<string, unknown>) : null;
}

function asString(raw: unknown): string | null {
  return typeof raw === "string" ? raw : null;
}

function asFiniteNumber(raw: unknown): number | null {
  return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
}

const LYRICS_SOURCES: ReadonlySet<string> = new Set<LyricsSource>([
  "local_file",
  "embedded",
  "online",
  "none",
]);

/** 把不可信输入归一为 Word；任一必填字段缺失返回 null。 */
function normalizeWord(raw: unknown): Word | null {
  const obj = asRecord(raw);
  if (obj === null) return null;
  const time = asFiniteNumber(obj.time_s);
  // 后端字段为 text，前端语义化为 char；同时兼容前端 char 字段
  const char = asString(obj.text) ?? asString(obj.char);
  if (time === null || char === null) return null;
  return { time_s: time, char };
}

/** 把不可信输入归一为 LyricsLine；缺 text / time_s 返回 null。 */
function normalizeLyricsLine(raw: unknown): LyricsLine | null {
  const obj = asRecord(raw);
  if (obj === null) return null;
  const time = asFiniteNumber(obj.time_s);
  const text = asString(obj.text);
  if (time === null || text === null) return null;
  const translation = asString(obj.translation);
  // words 为 null / 缺省 → null；为数组时逐项归一过滤；其他类型 → null
  let words: readonly Word[] | null = null;
  if (Array.isArray(obj.words)) {
    const normalized = obj.words
      .map(normalizeWord)
      .filter((w): w is Word => w !== null);
    words = normalized.length > 0 ? normalized : null;
  }
  return { time_s: time, text, translation, words };
}

/** 把不可信输入归一为 LyricsResult；结构非法时降级为空结果（source=none）。 */
function normalizeLyricsResult(raw: unknown): LyricsResult {
  const obj = asRecord(raw);
  if (obj === null) {
    return { lyrics: null, source: "none", parsed: [] };
  }
  const sourceStr = asString(obj.source);
  const source: LyricsSource =
    sourceStr !== null && LYRICS_SOURCES.has(sourceStr)
      ? (sourceStr as LyricsSource)
      : "none";
  const lyrics = asString(obj.lyrics);
  const parsed = Array.isArray(obj.parsed)
    ? obj.parsed
        .map(normalizeLyricsLine)
        .filter((l): l is LyricsLine => l !== null)
    : [];
  return { lyrics, source, parsed };
}

// ---------------------------------------------------------------------------
// 本地二分查找（镜像 lyrics_sync.py find_current_line / find_current_word）
// ---------------------------------------------------------------------------

/**
 * 在已按 time_s 升序排序的行列表中二分查找当前行索引。
 *
 * 镜像 ``lyrics_sync.py::LyricsSync.find_current_line`` 语义：
 * - 空列表 → -1
 * - 找最大的 ``time_s <= eff_time``；若有多个相同 time_s，取**首个**
 *   （与后端 ``line.time_s > best_time`` 严格大于语义一致）
 * - 所有行 time_s 都 > eff_time → 返回 0（第一行）
 *
 * ``eff_time = position_s + offset_s``（用户偏移叠加）。
 */
function findCurrentLine(
  parsed: readonly LyricsLine[],
  positionS: number,
  offsetS: number,
): number {
  if (parsed.length === 0) return -1;
  const effTime = positionS + offsetS;
  // 二分：找到最后一个 time_s <= effTime 的位置（rightmost）
  // 若有重复 time_s，再向左走到首个出现的位置，匹配后端「首个最大」语义。
  let lo = 0;
  let hi = parsed.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (parsed[mid]!.time_s <= effTime) {
      lo = mid + 1;
    } else {
      hi = mid;
    }
  }
  // lo - 1 是 rightmost（time_s <= effTime 的最后一个）
  if (lo === 0) {
    // 所有行 time_s > effTime → 返回 0（第一行，与后端一致）
    return 0;
  }
  let idx = lo - 1;
  // 向左走到首个相同 time_s 的位置（匹配后端「首个最大」语义）
  const targetTime = parsed[idx]!.time_s;
  while (idx > 0 && parsed[idx - 1]!.time_s === targetTime) {
    idx -= 1;
  }
  return idx;
}

/**
 * 在当前行的逐字列表中查找当前字索引。
 *
 * 镜像 ``lyrics_sync.py::LyricsSync.find_current_word``：
 * - 无 words / 空 words → null
 * - 找最大的 ``time_s <= eff_time``；重复时间取首个
 * - 所有 word.time_s > eff_time → 返回 0（第一个字）
 */
function findCurrentWord(
  line: LyricsLine,
  positionS: number,
  offsetS: number,
): number | null {
  if (line.words === null || line.words.length === 0) return null;
  const effTime = positionS + offsetS;
  let lo = 0;
  let hi = line.words.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (line.words[mid]!.time_s <= effTime) {
      lo = mid + 1;
    } else {
      hi = mid;
    }
  }
  if (lo === 0) return 0;
  let idx = lo - 1;
  const targetTime = line.words[idx]!.time_s;
  while (idx > 0 && line.words[idx - 1]!.time_s === targetTime) {
    idx -= 1;
  }
  return idx;
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export interface LyricsState {
  /** 当前歌词结果；null = 尚未拉取 / 拉取失败。 */
  readonly currentLyrics: LyricsResult | null;
  /** 当前行索引（0-based）；-1 = 无歌词 / 未定位。 */
  readonly currentIndex: number;
  /** 当前逐字高亮索引；null = 非逐字行 / 无歌词。 */
  readonly currentWordIndex: number | null;
  /** 用户全局偏移（秒）；正数提前、负数延后。 */
  readonly offsetS: number;
  /** 正在拉取 / 调用工具中。 */
  readonly isLoading: boolean;
  /** 最近一次错误信息（用户可读）；null = 无错误。 */
  readonly error: string | null;
}

export interface LyricsStore {
  getState: () => LyricsState;
  subscribe: (listener: () => void) => () => void;
  /** 拉取歌词（lyrics_get）：按 song_id 经优先级链获取并解析。 */
  fetchLyrics: (songId: string, source?: LyricsSource) => Promise<void>;
  /** 本地二分查找更新 currentIndex / currentWordIndex（不打 IPC）。 */
  refreshCurrentLine: (positionS: number) => void;
  /** 设置用户偏移并持久化到后端（lyrics_set_offset）。 */
  setOffset: (offsetS: number) => Promise<void>;
  /** 按关键词搜索歌曲（lyrics_search），返回归一化后的 songs 列表。 */
  searchLyrics: (keyword: string) => Promise<readonly SearchedSong[] | null>;
  /** 上传 / 保存歌词到本地 .lrc 文件（lyrics_upload），返回文件路径。 */
  uploadLyrics: (songId: string, lrcText: string) => Promise<string | null>;
  /** 清空当前歌词与行索引（切歌时调用）；保留 offsetS（用户偏好）。 */
  clear: () => void;
  /**
   * E2E / 演示专用：直接注入歌词结果，绕过 IPC。
   * 生产路径不应调用——仅供 __omniDebug 与非 Tauri 预览注入快照。
   */
  debugSetLyrics: (lyrics: LyricsResult | null) => void;
}

/** lyrics_search 返回的精简歌曲元数据（仅含定位所需字段）。 */
export interface SearchedSong {
  readonly id: string;
  readonly name: string;
  readonly artists: readonly string[];
  readonly source: string | null;
}

export interface LyricsStoreDeps {
  /** 注入自定义 invoker（测试用）；缺省走 Tauri invoke。 */
  readonly invoker?: LyricsInvoker;
}

/** 空状态：无歌词、无当前行、偏移 0。 */
export const EMPTY_LYRICS_STATE: LyricsState = {
  currentLyrics: null,
  currentIndex: -1,
  currentWordIndex: null,
  offsetS: 0,
  isLoading: false,
  error: null,
};

export function createLyricsStore(deps: LyricsStoreDeps = {}): LyricsStore {
  const invoker: LyricsInvoker = deps.invoker ?? defaultInvoker;
  let state: LyricsState = { ...EMPTY_LYRICS_STATE };
  const listeners = new Set<() => void>();

  const emit = (): void => {
    for (const listener of listeners) listener();
  };

  const patch = (next: Partial<LyricsState>): void => {
    state = { ...state, ...next };
    emit();
  };

  /**
   * 调用 lyrics 工具，返回 data 或 null（失败时写 error 状态）。
   * 调用期间置 isLoading=true。
   */
  async function callTool<T>(
    tool: string,
    args?: Record<string, unknown>,
  ): Promise<T | null> {
    patch({ isLoading: true, error: null });
    const result = await invoker(tool, args);
    if (result.ok) {
      patch({ isLoading: false });
      return (result.data ?? null) as T | null;
    }
    const message = result.error?.message ?? "未知错误";
    patch({ isLoading: false, error: message });
    return null;
  }

  /** 归一化 lyrics_search 返回的 songs 列表。 */
  function normalizeSearchedSongs(raw: unknown): readonly SearchedSong[] {
    const obj = asRecord(raw);
    if (obj === null) return [];
    if (!Array.isArray(obj.songs)) return [];
    return obj.songs
      .map((s): SearchedSong | null => {
        const songObj = asRecord(s);
        if (songObj === null) return null;
        const id = asString(songObj.id);
        const name = asString(songObj.name);
        if (id === null || name === null) return null;
        const artists = Array.isArray(songObj.artists)
          ? songObj.artists.filter((v): v is string => typeof v === "string")
          : [];
        const source = asString(songObj.source);
        return { id, name, artists, source };
      })
      .filter((s): s is SearchedSong => s !== null);
  }

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    async fetchLyrics(songId, source) {
      const args: Record<string, unknown> = { song_id: songId };
      if (source !== undefined) args.source = source;
      const data = await callTool<unknown>("lyrics_get", args);
      if (data === null) return; // 错误已写入 state.error
      const normalized = normalizeLyricsResult(data);
      patch({
        currentLyrics: normalized,
        currentIndex: -1,
        currentWordIndex: null,
        error: null,
      });
    },
    refreshCurrentLine(positionS) {
      if (!Number.isFinite(positionS)) return;
      const lyrics = state.currentLyrics;
      if (lyrics === null) return; // 无歌词缓存，no-op
      const parsed = lyrics.parsed;
      const offset = state.offsetS;
      const lineIdx = findCurrentLine(parsed, positionS, offset);
      let wordIdx: number | null = null;
      if (lineIdx >= 0 && lineIdx < parsed.length) {
        wordIdx = findCurrentWord(parsed[lineIdx]!, positionS, offset);
      }
      // 仅在变化时 emit（避免高频 timeupdate 引发无意义重渲染）
      if (state.currentIndex === lineIdx && state.currentWordIndex === wordIdx) {
        return;
      }
      patch({ currentIndex: lineIdx, currentWordIndex: wordIdx });
    },
    async setOffset(offsetS) {
      if (!Number.isFinite(offsetS)) return;
      const data = await callTool<unknown>("lyrics_set_offset", { offset_s: offsetS });
      if (data === null) return; // 错误已写入 state.error
      const obj = asRecord(data);
      const normalized = asFiniteNumber(obj?.offset_s) ?? offsetS;
      patch({ offsetS: normalized });
    },
    async searchLyrics(keyword) {
      const data = await callTool<unknown>("lyrics_search", { keyword });
      if (data === null) return null;
      return normalizeSearchedSongs(data);
    },
    async uploadLyrics(songId, lrcText) {
      const data = await callTool<unknown>("lyrics_upload", {
        song_id: songId,
        content: lrcText,
      });
      if (data === null) return null;
      const obj = asRecord(data);
      return asString(obj?.path) ?? null;
    },
    clear() {
      if (
        state.currentLyrics === null &&
        state.currentIndex === -1 &&
        state.currentWordIndex === null
      ) {
        return; // 已是清空态，no-op
      }
      patch({
        currentLyrics: null,
        currentIndex: -1,
        currentWordIndex: null,
        error: null,
      });
    },
    debugSetLyrics(lyrics) {
      // 演示 / E2E 注入：等价于 fetchLyrics 成功路径的 patch，但绕过 IPC
      // 且不清 offsetS（用户偏好）。null 注入等价于 clear + 清错误。
      patch({
        currentLyrics: lyrics,
        currentIndex: -1,
        currentWordIndex: null,
        isLoading: false,
        error: null,
      });
    },
  };
}
