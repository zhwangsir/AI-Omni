/**
 * 音乐播放状态 store（M17.10）。
 *
 * 框架无关订阅模式（与 agentStore / statusStore 同款），React 侧经
 * ``useSyncExternalStore`` 绑定。维护两类状态：
 *
 * 1. 播放器状态 ``playerState``：来自后端 ``MusicPlayer.to_state_dict()``
 *    （player.py），含 queue / current_index / state / repeat_mode /
 *    position_s / current_song。前端只读消费，不本地修改——后端是唯一权威源。
 * 2. 扫码登录 ``loginQr`` / ``loginStatus``：经 ``music_get_login_qr`` 发起，
 *    轮询 ``music_check_login_status`` 推进状态机。
 *
 * IPC 通道（D17.1）：经通用 ``music_tool`` command 调 Rust → Python omni_music
 * 工具（M17.9 后端对接）。工具返回 JSON 字符串 ``{"ok": true, "data": ...}``，
 * store 侧解析 + 防御性归一化（IPC 边界不可信）。
 *
 * 非 Tauri 环境（vitest / 纯 web 预览）默认 invoker 返回 ``E_NOT_TAURI``，
 * store 呈现离线态而非报错刷屏；测试经 ``deps.invoker`` 注入 fake 即可。
 *
 * 实际音频播放由 ``AudioPlayer.tsx`` 的 ``<audio>`` 元素负责（D17.1 前端 WebAudio 优先），
 * store 只管元数据与状态机；``position_s`` 由 ``<audio>`` 的 timeupdate 推送回后端。
 */
import { invoke } from "@tauri-apps/api/core";

import { isTauri } from "../lib/window";

// ---------------------------------------------------------------------------
// 状态契约（与 omni_music/player.py to_state_dict + models.py Song.to_dict 对齐）
// ---------------------------------------------------------------------------

/** 音乐源（models.py MusicSourceEnum）。 */
export type MusicSourceName = "netease" | "qqmusic" | "local" | "spotify";

/** 单曲元数据（models.py Song.to_dict）。 */
export interface Song {
  readonly id: string;
  readonly name: string;
  readonly artists: readonly string[];
  readonly album: string | null;
  readonly duration_s: number;
  readonly url: string | null;
  readonly lyrics: string | null;
  readonly cover_url: string | null;
  readonly source: MusicSourceName;
}

/** 播放状态名（player.py PlayerState.value）。 */
export type PlayerStateName = "stopped" | "playing" | "paused";

/** 播放模式（player.py RepeatMode.value）。 */
export type RepeatMode = "single" | "list_loop" | "random" | "sequence";

/** 后端 to_state_dict 推送的完整播放器状态。 */
export interface PlayerStateContract {
  readonly queue: readonly Song[];
  readonly current_index: number;
  readonly state: PlayerStateName;
  readonly repeat_mode: RepeatMode;
  readonly position_s: number;
  readonly current_song: Song | null;
}

/** 扫码登录状态机。 */
export type LoginStatus = "idle" | "waiting" | "scanned" | "confirmed" | "expired";

/** 扫码登录返回的二维码信息。 */
export interface LoginQr {
  readonly key: string;
  readonly qr_url: string;
  readonly source: string;
}

// ---------------------------------------------------------------------------
// IPC 边界（不可信数据归一化）
// ---------------------------------------------------------------------------

/** 工具返回的 JSON 字符串解析后结构。 */
export interface MusicToolResult<T> {
  readonly ok: boolean;
  readonly data?: T;
  readonly error?: { readonly code: string; readonly message: string };
}

/**
 * 通用音乐工具调用器：经 ``invoke('music_tool', {tool, args})`` 调 Rust → Python。
 * 返回解析后的 ``MusicToolResult``；实现侧负责 JSON 解析与防御性归一化。
 */
export type MusicInvoker = (
  tool: string,
  args?: Record<string, unknown>,
) => Promise<MusicToolResult<unknown>>;

/** 默认 Tauri invoker：非 Tauri 环境降级为 E_NOT_TAURI（不抛错）。 */
async function defaultInvoker(
  tool: string,
  args?: Record<string, unknown>,
): Promise<MusicToolResult<unknown>> {
  if (!isTauri()) {
    return { ok: false, error: { code: "E_NOT_TAURI", message: "非 Tauri 环境，音乐工具不可用" } };
  }
  try {
    // 后端返回 JSON 字符串 {"ok": true, "data": ...} / {"ok": false, "error": {...}}
    const raw = await invoke<string>("music_tool", { tool, args: args ?? {} });
    const parsed = JSON.parse(raw) as MusicToolResult<unknown>;
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

function asStringArray(raw: unknown): readonly string[] {
  return Array.isArray(raw)
    ? raw.filter((v): v is string => typeof v === "string")
    : [];
}

const MUSIC_SOURCES: ReadonlySet<string> = new Set<MusicSourceName>([
  "netease",
  "qqmusic",
  "local",
  "spotify",
]);

const PLAYER_STATES: ReadonlySet<string> = new Set<PlayerStateName>([
  "stopped",
  "playing",
  "paused",
]);

const REPEAT_MODES: ReadonlySet<string> = new Set<RepeatMode>([
  "single",
  "list_loop",
  "random",
  "sequence",
]);

/** 把不可信输入归一为 Song；任一必填字段缺失返回 null。 */
function normalizeSong(raw: unknown): Song | null {
  const obj = asRecord(raw);
  if (obj === null) return null;
  const id = asString(obj.id);
  const name = asString(obj.name);
  if (id === null || name === null) return null;
  const source = asString(obj.source);
  if (source === null || !MUSIC_SOURCES.has(source)) return null;
  const duration = asFiniteNumber(obj.duration_s);
  return {
    id,
    name,
    source: source as MusicSourceName,
    artists: asStringArray(obj.artists),
    album: asString(obj.album),
    duration_s: duration ?? 0,
    url: asString(obj.url),
    lyrics: asString(obj.lyrics),
    cover_url: asString(obj.cover_url),
  };
}

/** 把不可信输入归一为 PlayerStateContract；结构非法返回 null。 */
function normalizePlayerState(raw: unknown): PlayerStateContract | null {
  const obj = asRecord(raw);
  if (obj === null) return null;
  const stateStr = asString(obj.state);
  const repeatStr = asString(obj.repeat_mode);
  if (stateStr === null || !PLAYER_STATES.has(stateStr)) return null;
  if (repeatStr === null || !REPEAT_MODES.has(repeatStr)) return null;
  const currentIndex = asFiniteNumber(obj.current_index);
  const position = asFiniteNumber(obj.position_s);
  if (currentIndex === null || position === null) return null;
  const queue = Array.isArray(obj.queue)
    ? obj.queue.map(normalizeSong).filter((s): s is Song => s !== null)
    : [];
  const currentSong =
    obj.current_song === null ? null : normalizeSong(obj.current_song);
  return {
    queue,
    current_index: currentIndex,
    state: stateStr as PlayerStateName,
    repeat_mode: repeatStr as RepeatMode,
    position_s: position,
    current_song: currentSong,
  };
}

/** 把不可信输入归一为 LoginQr；缺关键字段返回 null。 */
function normalizeLoginQr(raw: unknown): LoginQr | null {
  const obj = asRecord(raw);
  if (obj === null) return null;
  const key = asString(obj.key);
  const qrUrl = asString(obj.qr_url);
  const source = asString(obj.source);
  if (key === null || qrUrl === null || source === null) return null;
  return { key, qr_url: qrUrl, source };
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export interface MusicState {
  /** 后端推送的播放器状态；null = 尚未拉取 / 拉取失败。 */
  readonly playerState: PlayerStateContract | null;
  /** 正在拉取 / 调用工具中。 */
  readonly isLoading: boolean;
  /** 最近一次错误信息（用户可读）；null = 无错误。 */
  readonly error: string | null;
  /** 扫码登录二维码信息；null = 未发起 / 已关闭。 */
  readonly loginQr: LoginQr | null;
  /** 扫码登录状态机。 */
  readonly loginStatus: LoginStatus;
  /** 在线搜索结果（music_search，M32.29b）；null = 未搜索 / 已清空。 */
  readonly onlineResults: readonly Song[] | null;
}

export interface MusicStore {
  getState: () => MusicState;
  subscribe: (listener: () => void) => () => void;
  /** 拉取后端播放器状态（music_get_player_state）。 */
  fetchPlayerState: () => Promise<void>;
  /** 开始播放：可指定 songId / index / keyword（music_play）。 */
  play: (opts?: { songId?: string; index?: number; keyword?: string }) => Promise<void>;
  /** 暂停（music_pause）。 */
  pause: () => Promise<void>;
  /** 恢复（music_resume）。 */
  resume: () => Promise<void>;
  /** 停止（music_stop）。 */
  stop: () => Promise<void>;
  /** 下一首（music_next）。 */
  next: () => Promise<void>;
  /** 上一首（music_previous）。 */
  previous: () => Promise<void>;
  /** 跳转到指定位置秒（music_seek）。 */
  seek: (position_s: number) => Promise<void>;
  /** 切换播放模式（music_set_repeat_mode）。 */
  setRepeatMode: (mode: RepeatMode) => Promise<void>;
  /** 发起扫码登录（music_get_login_qr）并启动状态轮询。 */
  startLogin: () => Promise<void>;
  /** 停止登录状态轮询（关闭弹窗 / 组件卸载时调用）。 */
  stopLoginPolling: () => void;
  /** 在线搜索歌曲（music_search，M32.29b）；空关键词清空结果不发请求。 */
  searchOnline: (keyword: string) => Promise<void>;
  /** 清空在线搜索结果（切回本地库 / 关闭视图时调用）。 */
  clearOnlineResults: () => void;
  /**
   * E2E / 演示专用：直接注入播放器状态，绕过 IPC。
   * 生产路径不应调用——后端是唯一权威源；仅供 __omniDebug 与非 Tauri 预览注入快照。
   */
  debugSetPlayerState: (playerState: PlayerStateContract | null) => void;
}

export interface MusicStoreDeps {
  /** 注入自定义 invoker（测试用）；缺省走 Tauri invoke。 */
  readonly invoker?: MusicInvoker;
  /** 登录状态轮询间隔 ms，缺省 2000。 */
  readonly loginPollMs?: number;
}

/** 空状态：无播放器状态、无登录、idle。 */
export const EMPTY_MUSIC_STATE: MusicState = {
  playerState: null,
  isLoading: false,
  error: null,
  loginQr: null,
  loginStatus: "idle",
  onlineResults: null,
};

/** 默认登录轮询间隔：2s（网易云 / QQ 音乐扫码通常 30-60s 内完成）。 */
export const DEFAULT_LOGIN_POLL_MS = 2000;

type TimerHandle = ReturnType<typeof setInterval>;

export function createMusicStore(deps: MusicStoreDeps = {}): MusicStore {
  const invoker: MusicInvoker = deps.invoker ?? defaultInvoker;
  const loginPollMs = deps.loginPollMs ?? DEFAULT_LOGIN_POLL_MS;
  let state: MusicState = { ...EMPTY_MUSIC_STATE };
  const listeners = new Set<() => void>();
  let loginTimer: TimerHandle | null = null;

  const emit = (): void => {
    for (const listener of listeners) listener();
  };

  const patch = (next: Partial<MusicState>): void => {
    state = { ...state, ...next };
    emit();
  };

  /**
   * 调用 music 工具，返回 data 或 null（失败时写 error 状态）。
   * 调用期间置 isLoading=true。
   */
  async function callTool<T>(tool: string, args?: Record<string, unknown>): Promise<T | null> {
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

  /** 拉取并归一化播放器状态。 */
  const refreshPlayerState = async (): Promise<void> => {
    const data = await callTool<unknown>("music_get_player_state");
    if (data === null) return; // 错误已写入 state.error
    const normalized = normalizePlayerState(data);
    if (normalized === null) {
      patch({ error: "播放器状态数据非法" });
      return;
    }
    patch({ playerState: normalized, error: null });
  };

  const clearLoginTimer = (): void => {
    if (loginTimer !== null) {
      clearInterval(loginTimer);
      loginTimer = null;
    }
  };

  /** 轮询 music_check_login_status 推进状态机。 */
  const pollLoginStatus = async (): Promise<void> => {
    if (state.loginStatus !== "waiting" && state.loginStatus !== "scanned") {
      return;
    }
    const data = await callTool<unknown>("music_check_login_status");
    if (data === null) return;
    const obj = asRecord(data);
    if (obj === null) return;
    const statusStr = asString(obj.status);
    if (statusStr === null) return;
    if (statusStr === "waiting" || statusStr === "scanned" || statusStr === "confirmed" || statusStr === "expired") {
      patch({ loginStatus: statusStr as LoginStatus });
      if (statusStr === "confirmed" || statusStr === "expired") {
        clearLoginTimer();
      }
    }
  };

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    async fetchPlayerState() {
      await refreshPlayerState();
    },
    async play(opts = {}) {
      const args: Record<string, unknown> = {};
      if (opts.songId !== undefined) args.song_id = opts.songId;
      if (opts.index !== undefined) args.index = opts.index;
      if (opts.keyword !== undefined) args.keyword = opts.keyword;
      await callTool("music_play", args);
      await refreshPlayerState();
    },
    async pause() {
      await callTool("music_pause");
      await refreshPlayerState();
    },
    async resume() {
      await callTool("music_resume");
      await refreshPlayerState();
    },
    async stop() {
      await callTool("music_stop");
      await refreshPlayerState();
    },
    async next() {
      await callTool("music_next");
      await refreshPlayerState();
    },
    async previous() {
      await callTool("music_previous");
      await refreshPlayerState();
    },
    async seek(position_s: number) {
      if (!Number.isFinite(position_s) || position_s < 0) return;
      await callTool("music_seek", { position_s });
      // seek 不强制 refresh（前端 audio.currentTime 已是权威，避免抖动）
    },
    async setRepeatMode(mode) {
      await callTool("music_set_repeat_mode", { mode });
      await refreshPlayerState();
    },
    async startLogin() {
      clearLoginTimer();
      patch({ loginStatus: "waiting", error: null });
      const data = await callTool<unknown>("music_get_login_qr");
      if (data === null) {
        patch({ loginStatus: "idle" });
        return;
      }
      const qr = normalizeLoginQr(data);
      if (qr === null) {
        patch({ loginStatus: "idle", error: "二维码数据非法" });
        return;
      }
      patch({ loginQr: qr, loginStatus: "waiting" });
      // 启动轮询（clearInterval 句柄存闭包，stopLoginPolling 清理）
      loginTimer = setInterval(() => {
        void pollLoginStatus();
      }, loginPollMs);
    },
    stopLoginPolling() {
      clearLoginTimer();
      if (state.loginStatus === "waiting" || state.loginStatus === "scanned") {
        patch({ loginStatus: "idle" });
      }
    },
    async searchOnline(keyword: string) {
      const trimmed = keyword.trim();
      if (trimmed === "") {
        // 空关键词：不发请求，仅清空结果（M32.29b 契约）
        patch({ onlineResults: null });
        return;
      }
      const data = await callTool<unknown>("music_search", { keyword: trimmed, limit: 20 });
      if (data === null) {
        // 错误已由 callTool 写入 state.error；结果置 null 避免展示过期列表
        patch({ onlineResults: null });
        return;
      }
      const obj = asRecord(data);
      const rawSongs = obj?.songs;
      if (!Array.isArray(rawSongs)) {
        patch({ onlineResults: null, error: "搜索结果数据非法" });
        return;
      }
      const songs = rawSongs
        .map(normalizeSong)
        .filter((s): s is Song => s !== null);
      patch({ onlineResults: songs, error: null });
    },
    clearOnlineResults() {
      patch({ onlineResults: null });
    },
    debugSetPlayerState(playerState) {
      patch({ playerState, error: null });
    },
  };
}
