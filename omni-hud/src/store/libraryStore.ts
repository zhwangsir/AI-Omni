/**
 * 本地音乐库 store（M19）。
 *
 * 框架无关订阅模式（与 musicStore / agentStore 同款），React 侧经
 * ``useSyncExternalStore`` 绑定。管理本地音乐库的扫描、搜索、歌单、
 * 加密音频解密四类状态。
 *
 * 后端契约（omni_music/library/db.py + tools.py M19 工具）：
 * - ``music_library_scan``     → {scanned, added, updated, skipped, errors}
 * - ``music_library_search``   → {songs: LibrarySong[], count}
 * - ``music_library_status``   → {song_count, playlist_count, last_scan_at, watching}
 * - ``music_playlist_create``  → {playlist_id, name}
 * - ``music_playlist_add``     → {playlist_id, song_id, added}
 * - ``music_playlist_remove``  → {playlist_id, song_id, removed}
 * - ``music_playlist_list``    → {playlists: Playlist[]} | {songs: LibrarySong[], count, playlist_id}
 * - ``music_decrypt_file``     → {output_path, source_path, compliance, notice}
 *
 * IPC 通道（D17.1）：经通用 ``music_tool`` command 调 Rust → Python omni_music
 * 工具。与 musicStore 共享同一 invoker 契约，但独立持有 library 侧状态，
 * 避免与播放器状态互相干扰。
 *
 * 合规说明（D19.1）：解密工具需 ``confirm=true`` 安全门，store 侧不绕过；
 * ``decryptFile`` 调用前要求调用方显式传 ``confirm=true``。
 */
import { invoke } from "@tauri-apps/api/core";

import { isTauri } from "../lib/window";

// ---------------------------------------------------------------------------
// 状态契约（与 omni_music/library/db.py songs 表 + tools.py M19 工具对齐）
// ---------------------------------------------------------------------------

/** 本地音乐库单曲元数据（db.py songs 表行）。 */
export interface LibrarySong {
  readonly id: string;
  readonly path: string;
  readonly title: string | null;
  readonly artist: string | null;
  readonly album: string | null;
  readonly duration_s: number;
  readonly cover_path: string | null;
  readonly lyrics_path: string | null;
  readonly source: string;
  readonly file_mtime: number;
  readonly file_size: number;
  readonly added_at: number;
}

/** 歌单（db.py get_playlists 返回，含 song_count）。 */
export interface Playlist {
  readonly id: number;
  readonly name: string;
  readonly created_at: number;
  readonly updated_at: number;
  readonly song_count: number;
}

/** 库状态（db.py get_status + tools.py watching 字段）。 */
export interface LibraryStatus {
  readonly song_count: number;
  readonly playlist_count: number;
  readonly last_scan_at: number | null;
  readonly watching: boolean;
}

/** 扫描结果（scanner.py scan 返回）。 */
export interface ScanResult {
  readonly scanned: number;
  readonly added: number;
  readonly updated: number;
  readonly skipped: number;
  readonly errors: number;
}

/** 解密结果（tools.py music_decrypt_file 返回）。 */
export interface DecryptResult {
  readonly output_path: string;
  readonly source_path: string;
  readonly compliance: string;
  readonly notice: string;
}

// ---------------------------------------------------------------------------
// IPC 边界（不可信数据归一化）
// ---------------------------------------------------------------------------

/** 工具返回的 JSON 字符串解析后结构（与 musicStore 同构）。 */
export interface LibraryToolResult<T> {
  readonly ok: boolean;
  readonly data?: T;
  readonly error?: { readonly code: string; readonly message: string };
}

/**
 * 通用音乐工具调用器：经 ``invoke('music_tool', {tool, args})`` 调 Rust → Python。
 * 与 musicStore 的 MusicInvoker 同构，可共享也可独立注入。
 */
export type LibraryInvoker = (
  tool: string,
  args?: Record<string, unknown>,
) => Promise<LibraryToolResult<unknown>>;

/** 默认 Tauri invoker：非 Tauri 环境降级为 E_NOT_TAURI（不抛错）。 */
async function defaultInvoker(
  tool: string,
  args?: Record<string, unknown>,
): Promise<LibraryToolResult<unknown>> {
  if (!isTauri()) {
    return { ok: false, error: { code: "E_NOT_TAURI", message: "非 Tauri 环境，音乐库工具不可用" } };
  }
  try {
    const raw = await invoke<string>("music_tool", { tool, args: args ?? {} });
    const parsed = JSON.parse(raw) as LibraryToolResult<unknown>;
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

function asFiniteNumberOrZero(raw: unknown): number {
  const n = asFiniteNumber(raw);
  return n ?? 0;
}

function asBool(raw: unknown): boolean {
  return raw === true;
}

/** 把不可信输入归一为 LibrarySong；缺必填 id/path 返回 null。 */
function normalizeLibrarySong(raw: unknown): LibrarySong | null {
  const obj = asRecord(raw);
  if (obj === null) return null;
  const id = asString(obj.id);
  const path = asString(obj.path);
  if (id === null || path === null) return null;
  return {
    id,
    path,
    title: asString(obj.title),
    artist: asString(obj.artist),
    album: asString(obj.album),
    duration_s: asFiniteNumberOrZero(obj.duration_s),
    cover_path: asString(obj.cover_path),
    lyrics_path: asString(obj.lyrics_path),
    source: asString(obj.source) ?? "local",
    file_mtime: asFiniteNumberOrZero(obj.file_mtime),
    file_size: asFiniteNumberOrZero(obj.file_size),
    added_at: asFiniteNumberOrZero(obj.added_at),
  };
}

/** 把不可信输入归一为 Playlist；缺必填 id/name 返回 null。 */
function normalizePlaylist(raw: unknown): Playlist | null {
  const obj = asRecord(raw);
  if (obj === null) return null;
  const id = asFiniteNumber(obj.id);
  const name = asString(obj.name);
  if (id === null || name === null) return null;
  return {
    id,
    name,
    created_at: asFiniteNumberOrZero(obj.created_at),
    updated_at: asFiniteNumberOrZero(obj.updated_at),
    song_count: asFiniteNumberOrZero(obj.song_count),
  };
}

/** 把不可信输入归一为 LibraryStatus。 */
function normalizeLibraryStatus(raw: unknown): LibraryStatus | null {
  const obj = asRecord(raw);
  if (obj === null) return null;
  const songCount = asFiniteNumber(obj.song_count);
  const playlistCount = asFiniteNumber(obj.playlist_count);
  if (songCount === null || playlistCount === null) return null;
  const lastScanRaw = asFiniteNumber(obj.last_scan_at);
  return {
    song_count: songCount,
    playlist_count: playlistCount,
    last_scan_at: lastScanRaw,
    watching: asBool(obj.watching),
  };
}

/** 把不可信输入归一为 ScanResult。 */
function normalizeScanResult(raw: unknown): ScanResult | null {
  const obj = asRecord(raw);
  if (obj === null) return null;
  return {
    scanned: asFiniteNumberOrZero(obj.scanned),
    added: asFiniteNumberOrZero(obj.added),
    updated: asFiniteNumberOrZero(obj.updated),
    skipped: asFiniteNumberOrZero(obj.skipped),
    errors: asFiniteNumberOrZero(obj.errors),
  };
}

/** 把不可信输入归一为 DecryptResult；缺 output_path 返回 null。 */
function normalizeDecryptResult(raw: unknown): DecryptResult | null {
  const obj = asRecord(raw);
  if (obj === null) return null;
  const outputPath = asString(obj.output_path);
  const sourcePath = asString(obj.source_path);
  if (outputPath === null || sourcePath === null) return null;
  return {
    output_path: outputPath,
    source_path: sourcePath,
    compliance: asString(obj.compliance) ?? "",
    notice: asString(obj.notice) ?? "",
  };
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export interface LibraryStoreState {
  /** 搜索结果歌曲列表；null = 尚未搜索。 */
  readonly songs: readonly LibrarySong[] | null;
  /** 全部歌单列表。 */
  readonly playlists: readonly Playlist[];
  /** 当前选中的歌单 ID；null = 未选中。 */
  readonly currentPlaylistId: number | null;
  /** 当前选中歌单的歌曲列表；null = 未加载。 */
  readonly playlistSongs: readonly LibrarySong[] | null;
  /** 库状态；null = 尚未拉取。 */
  readonly status: LibraryStatus | null;
  /** 最近一次扫描结果；null = 尚未扫描。 */
  readonly lastScanResult: ScanResult | null;
  /** 最近一次解密结果；null = 尚未解密。 */
  readonly lastDecryptResult: DecryptResult | null;
  /** 正在调用工具中。 */
  readonly isLoading: boolean;
  /** 最近一次错误信息（用户可读）；null = 无错误。 */
  readonly error: string | null;
  /** 当前搜索关键词。 */
  readonly searchQuery: string;
}

export interface LibraryStore {
  getState: () => LibraryStoreState;
  subscribe: (listener: () => void) => () => void;
  /** 扫描本地音乐库（music_library_scan）。 */
  scanLibrary: (rootDir?: string) => Promise<ScanResult | null>;
  /** 全文搜索音乐库（music_library_search）。 */
  searchLibrary: (query: string, limit?: number) => Promise<readonly LibrarySong[] | null>;
  /** 拉取库状态（music_library_status）。 */
  fetchStatus: () => Promise<void>;
  /** 拉取全部歌单（music_playlist_list，不传 playlist_id）。 */
  fetchPlaylists: () => Promise<void>;
  /** 拉取指定歌单内歌曲（music_playlist_list，传 playlist_id）。 */
  fetchPlaylistSongs: (playlistId: number) => Promise<void>;
  /** 选中歌单（设置 currentPlaylistId 并拉取歌曲）。 */
  selectPlaylist: (playlistId: number | null) => Promise<void>;
  /** 创建歌单（music_playlist_create）。 */
  createPlaylist: (name: string) => Promise<number | null>;
  /** 向歌单添加歌曲（music_playlist_add）。 */
  addToPlaylist: (playlistId: number, songId: string, position?: number) => Promise<boolean>;
  /** 从歌单移除歌曲（music_playlist_remove）。 */
  removeFromPlaylist: (playlistId: number, songId: string) => Promise<boolean>;
  /** 解密加密音频文件（music_decrypt_file，D19.1 合规：需 confirm=true）。 */
  decryptFile: (path: string, outputPath?: string, confirm?: boolean) => Promise<DecryptResult | null>;
  /** 设置搜索关键词（仅本地状态，不触发搜索）。 */
  setSearchQuery: (query: string) => void;
  /** 清除错误状态。 */
  clearError: () => void;
}

export interface LibraryStoreDeps {
  /** 注入自定义 invoker（测试用）；缺省走 Tauri invoke。 */
  readonly invoker?: LibraryInvoker;
}

/** 空状态：无歌曲、无歌单、无状态。 */
export const EMPTY_LIBRARY_STATE: LibraryStoreState = {
  songs: null,
  playlists: [],
  currentPlaylistId: null,
  playlistSongs: null,
  status: null,
  lastScanResult: null,
  lastDecryptResult: null,
  isLoading: false,
  error: null,
  searchQuery: "",
};

export function createLibraryStore(deps: LibraryStoreDeps = {}): LibraryStore {
  const invoker: LibraryInvoker = deps.invoker ?? defaultInvoker;
  let state: LibraryStoreState = { ...EMPTY_LIBRARY_STATE };
  const listeners = new Set<() => void>();

  const emit = (): void => {
    for (const listener of listeners) listener();
  };

  const patch = (next: Partial<LibraryStoreState>): void => {
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

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    async scanLibrary(rootDir) {
      const args: Record<string, unknown> = { fake: false };
      if (rootDir !== undefined) args.root_dir = rootDir;
      const data = await callTool<unknown>("music_library_scan", args);
      if (data === null) return null;
      const normalized = normalizeScanResult(data);
      if (normalized === null) {
        patch({ error: "扫描结果数据非法" });
        return null;
      }
      patch({ lastScanResult: normalized, error: null });
      return normalized;
    },
    async searchLibrary(query, limit = 20) {
      patch({ searchQuery: query });
      const data = await callTool<unknown>("music_library_search", { query, limit });
      if (data === null) return null;
      const obj = asRecord(data);
      if (obj === null) {
        patch({ error: "搜索结果数据非法" });
        return null;
      }
      const songsRaw = obj.songs;
      const songs = Array.isArray(songsRaw)
        ? songsRaw.map(normalizeLibrarySong).filter((s): s is LibrarySong => s !== null)
        : [];
      patch({ songs, error: null });
      return songs;
    },
    async fetchStatus() {
      const data = await callTool<unknown>("music_library_status");
      if (data === null) return;
      const normalized = normalizeLibraryStatus(data);
      if (normalized === null) {
        patch({ error: "库状态数据非法" });
        return;
      }
      patch({ status: normalized, error: null });
    },
    async fetchPlaylists() {
      const data = await callTool<unknown>("music_playlist_list");
      if (data === null) return;
      const obj = asRecord(data);
      if (obj === null) {
        patch({ error: "歌单数据非法" });
        return;
      }
      const playlistsRaw = obj.playlists;
      const playlists = Array.isArray(playlistsRaw)
        ? playlistsRaw.map(normalizePlaylist).filter((p): p is Playlist => p !== null)
        : [];
      patch({ playlists, error: null });
    },
    async fetchPlaylistSongs(playlistId) {
      const data = await callTool<unknown>("music_playlist_list", { playlist_id: playlistId });
      if (data === null) return;
      const obj = asRecord(data);
      if (obj === null) {
        patch({ error: "歌单曲目数据非法" });
        return;
      }
      const songsRaw = obj.songs;
      const songs = Array.isArray(songsRaw)
        ? songsRaw.map(normalizeLibrarySong).filter((s): s is LibrarySong => s !== null)
        : [];
      patch({ playlistSongs: songs, error: null });
    },
    async selectPlaylist(playlistId) {
      patch({ currentPlaylistId: playlistId, playlistSongs: null });
      if (playlistId !== null) {
        await this.fetchPlaylistSongs(playlistId);
      }
    },
    async createPlaylist(name) {
      const trimmed = name.trim();
      if (!trimmed) {
        patch({ error: "歌单名不能为空" });
        return null;
      }
      const data = await callTool<unknown>("music_playlist_create", { name: trimmed });
      if (data === null) return null;
      const obj = asRecord(data);
      if (obj === null) {
        patch({ error: "创建歌单响应非法" });
        return null;
      }
      const pid = asFiniteNumber(obj.playlist_id);
      if (pid === null) {
        patch({ error: "歌单 ID 缺失" });
        return null;
      }
      // 刷新歌单列表
      await this.fetchPlaylists();
      return pid;
    },
    async addToPlaylist(playlistId, songId, position) {
      const args: Record<string, unknown> = { playlist_id: playlistId, song_id: songId };
      if (position !== undefined) args.position = position;
      const data = await callTool<unknown>("music_playlist_add", args);
      if (data === null) return false;
      const obj = asRecord(data);
      if (obj === null) return false;
      const added = asBool(obj.added);
      // 如果当前正在查看该歌单，刷新歌曲列表
      if (added && state.currentPlaylistId === playlistId) {
        await this.fetchPlaylistSongs(playlistId);
      }
      // 刷新歌单列表（更新 song_count）
      if (added) {
        await this.fetchPlaylists();
      }
      return added;
    },
    async removeFromPlaylist(playlistId, songId) {
      const data = await callTool<unknown>("music_playlist_remove", {
        playlist_id: playlistId,
        song_id: songId,
      });
      if (data === null) return false;
      const obj = asRecord(data);
      if (obj === null) return false;
      const removed = asBool(obj.removed);
      if (removed && state.currentPlaylistId === playlistId) {
        await this.fetchPlaylistSongs(playlistId);
      }
      if (removed) {
        await this.fetchPlaylists();
      }
      return removed;
    },
    async decryptFile(path, outputPath, confirm = false) {
      if (!confirm) {
        patch({ error: "解密需确认（D19.1 合规约束）：传 confirm=true 确认已合法购买" });
        return null;
      }
      const args: Record<string, unknown> = { path, confirm: true };
      if (outputPath !== undefined) args.output_path = outputPath;
      const data = await callTool<unknown>("music_decrypt_file", args);
      if (data === null) return null;
      const normalized = normalizeDecryptResult(data);
      if (normalized === null) {
        patch({ error: "解密结果数据非法" });
        return null;
      }
      patch({ lastDecryptResult: normalized, error: null });
      return normalized;
    },
    setSearchQuery(query) {
      patch({ searchQuery: query });
    },
    clearError() {
      patch({ error: null });
    },
  };
}
