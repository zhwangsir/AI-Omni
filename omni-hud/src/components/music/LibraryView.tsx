/**
 * LibraryView 本地音乐库浏览视图（M19）。
 *
 * 三栏布局：
 * - 顶部状态栏：库状态（歌曲数 / 歌单数 / 上次扫描 / 监听指示）+ 扫描按钮
 * - 左栏歌单列表：创建 / 选中 / 歌单曲数
 * - 右栏歌曲列表：搜索结果或选中歌单内歌曲
 *
 * 订阅 libraryStore；扫描 / 搜索 / 歌单增删均经 store action 驱动。
 * 暗房风格（§六）；图标经 Icon.tsx（§五）；无 emoji。
 *
 * 组件不直接发起解密——解密入口由 DecryptDialog 独立承载（D19.1 合规
 * 隔离），LibraryView 只管浏览 / 搜索 / 歌单管理。
 */
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

import type { LibraryStore, LibrarySong, Playlist } from "../../store/libraryStore";
import { Icon } from "../ui/Icon";
import { formatTime } from "./shared";

export interface LibraryViewProps {
  store: LibraryStore;
  /** 挂载时自动拉取库状态与歌单列表，缺省 true。 */
  autoFetch?: boolean;
}

export function LibraryView({ store, autoFetch = true }: LibraryViewProps): JSX.Element {
  const state = useSyncExternalStore(store.subscribe, store.getState);

  useEffect(() => {
    if (!autoFetch) return;
    void store.fetchStatus();
    void store.fetchPlaylists();
  }, [store, autoFetch]);

  return (
    <div
      data-testid="library-view"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "10px",
        padding: "14px",
        background: "var(--omni-panel)",
        borderRadius: "var(--omni-radius)",
        border: "1px solid var(--omni-hairline)",
        color: "var(--omni-fog)",
        maxHeight: "520px",
      }}
    >
      <LibraryStatusBar store={store} />
      <div style={{ display: "flex", gap: "10px", flex: "1 1 auto", minHeight: 0 }}>
        <PlaylistSidebar store={store} />
        <SongListPanel store={store} />
      </div>
      {state.error ? (
        <div
          data-testid="library-error"
          style={{
            fontSize: "11px",
            color: "#b04a3a",
            padding: "4px 8px",
            background: "rgba(176, 74, 58, 0.08)",
            borderRadius: "4px",
          }}
        >
          {state.error}
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 顶部状态栏
// ---------------------------------------------------------------------------

function LibraryStatusBar({ store }: { store: LibraryStore }): JSX.Element {
  const state = useSyncExternalStore(store.subscribe, store.getState);
  const status = state.status;
  const scan = state.lastScanResult;
  const handleScan = useCallback((): void => {
    void store.scanLibrary();
  }, [store]);

  return (
    <div
      data-testid="library-status-bar"
      style={{
        display: "flex",
        alignItems: "center",
        gap: "14px",
        padding: "8px 10px",
        background: "var(--omni-abyss)",
        borderRadius: "6px",
        border: "1px solid var(--omni-hairline)",
      }}
    >
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "6px",
          fontSize: "11px",
          fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
          color: "var(--omni-dim)",
          letterSpacing: "0.08em",
          textTransform: "uppercase",
        }}
      >
        <Icon name="music" size={12} color="var(--omni-accent)" />
        本地音乐库
      </span>

      <span data-testid="library-status-counts" style={{ fontSize: "11px", color: "var(--omni-fog)" }}>
        {status ? `${status.song_count} 首 / ${status.playlist_count} 歌单` : "—"}
      </span>

      {status?.watching ? (
        <span
          data-testid="library-watching"
          style={{
            fontSize: "10px",
            color: "#6fb58a",
            display: "inline-flex",
            alignItems: "center",
            gap: "4px",
          }}
        >
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#6fb58a" }} />
          监听中
        </span>
      ) : null}

      {status?.last_scan_at ? (
        <span style={{ fontSize: "10px", color: "var(--omni-dim)" }}>
          上次扫描 {formatTimeAgo(status.last_scan_at)}
        </span>
      ) : null}

      {scan ? (
        <span data-testid="library-scan-summary" style={{ fontSize: "10px", color: "var(--omni-dim)" }}>
          扫描 {scan.scanned} / 新增 {scan.added} / 更新 {scan.updated}
          {scan.errors > 0 ? ` / 错误 ${scan.errors}` : ""}
        </span>
      ) : null}

      <button
        type="button"
        data-testid="library-scan-btn"
        onClick={handleScan}
        disabled={state.isLoading}
        aria-label="扫描本地音乐库"
        style={{
          marginLeft: "auto",
          display: "inline-flex",
          alignItems: "center",
          gap: "6px",
          padding: "4px 12px",
          borderRadius: "4px",
          border: "1px solid var(--omni-accent)",
          background: "transparent",
          color: "var(--omni-accent)",
          cursor: state.isLoading ? "wait" : "pointer",
          fontSize: "11px",
          opacity: state.isLoading ? 0.6 : 1,
          transition: "opacity 200ms ease-out",
        }}
      >
        <Icon name="repeat" size={11} label="扫描" />
        {state.isLoading ? "扫描中" : "扫描"}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 左栏：歌单列表
// ---------------------------------------------------------------------------

function PlaylistSidebar({ store }: { store: LibraryStore }): JSX.Element {
  const state = useSyncExternalStore(store.subscribe, store.getState);
  const [newName, setNewName] = useState("");
  const playlists = state.playlists;
  const currentId = state.currentPlaylistId;

  const handleCreate = useCallback((): void => {
    const name = newName.trim();
    if (!name) return;
    void store.createPlaylist(name).then((pid) => {
      if (pid !== null) setNewName("");
    });
  }, [store, newName]);

  const handleSelect = useCallback(
    (id: number): void => {
      void store.selectPlaylist(id);
    },
    [store],
  );

  return (
    <div
      data-testid="library-playlist-sidebar"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "4px",
        width: "180px",
        flexShrink: 0,
        padding: "8px",
        background: "var(--omni-abyss)",
        borderRadius: "6px",
        border: "1px solid var(--omni-hairline)",
        overflowY: "auto",
        scrollbarWidth: "thin",
      }}
    >
      <span
        style={{
          fontSize: "10px",
          fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
          color: "var(--omni-dim)",
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          marginBottom: "4px",
        }}
      >
        歌单
      </span>

      {playlists.length === 0 ? (
        <span style={{ fontSize: "11px", color: "var(--omni-dim)", padding: "4px 0" }}>
          暂无歌单
        </span>
      ) : (
        playlists.map((pl) => (
          <PlaylistRow
            key={pl.id}
            playlist={pl}
            isCurrent={pl.id === currentId}
            onSelect={handleSelect}
          />
        ))
      )}

      <div style={{ display: "flex", gap: "4px", marginTop: "6px" }}>
        <input
          data-testid="library-new-playlist-input"
          type="text"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleCreate();
          }}
          placeholder="新歌单名称"
          aria-label="新歌单名称"
          style={{
            flex: "1 1 auto",
            minWidth: 0,
            padding: "4px 6px",
            fontSize: "11px",
            background: "var(--omni-panel)",
            color: "var(--omni-fog)",
            border: "1px solid var(--omni-hairline)",
            borderRadius: "4px",
            outline: "none",
          }}
        />
        <button
          type="button"
          data-testid="library-create-playlist-btn"
          onClick={handleCreate}
          disabled={!newName.trim()}
          aria-label="创建歌单"
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: "26px",
            height: "26px",
            borderRadius: "4px",
            border: "1px solid var(--omni-hairline)",
            background: "transparent",
            color: "var(--omni-accent)",
            cursor: newName.trim() ? "pointer" : "not-allowed",
            opacity: newName.trim() ? 1 : 0.4,
            padding: 0,
          }}
        >
          <Icon name="plus" size={12} label="创建" />
        </button>
      </div>
    </div>
  );
}

function PlaylistRow({
  playlist,
  isCurrent,
  onSelect,
}: {
  playlist: Playlist;
  isCurrent: boolean;
  onSelect: (id: number) => void;
}): JSX.Element {
  return (
    <button
      type="button"
      data-testid="library-playlist-row"
      data-playlist-id={playlist.id}
      data-current={isCurrent ? "true" : "false"}
      onClick={() => onSelect(playlist.id)}
      aria-label={`选中歌单：${playlist.name}`}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "6px",
        padding: "5px 8px",
        borderRadius: "4px",
        border: "none",
        borderLeft: isCurrent ? "2px solid var(--omni-accent)" : "2px solid transparent",
        background: "transparent",
        color: isCurrent ? "var(--omni-accent)" : "var(--omni-fog)",
        cursor: "pointer",
        textAlign: "left",
        width: "100%",
        transition: "background-color 160ms ease-out",
      }}
    >
      <Icon name="listMusic" size={10} color={isCurrent ? "var(--omni-accent)" : "var(--omni-dim)"} />
      <span
        style={{
          flex: "1 1 auto",
          minWidth: 0,
          fontSize: "11px",
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {playlist.name}
      </span>
      <span style={{ fontSize: "9px", color: "var(--omni-dim)", flexShrink: 0 }}>
        {playlist.song_count}
      </span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// 右栏：歌曲列表（搜索结果 / 歌单内歌曲）
// ---------------------------------------------------------------------------

function SongListPanel({ store }: { store: LibraryStore }): JSX.Element {
  const state = useSyncExternalStore(store.subscribe, store.getState);
  const [query, setQuery] = useState("");

  const handleSearch = useCallback((): void => {
    void store.searchLibrary(query);
  }, [store, query]);

  // 当前展示的歌曲列表：优先搜索结果，其次歌单内歌曲
  const songs = state.songs ?? state.playlistSongs ?? [];
  const mode: "search" | "playlist" | "empty" =
    state.songs !== null ? "search" : state.currentPlaylistId !== null ? "playlist" : "empty";

  return (
    <div
      data-testid="library-song-panel"
      data-mode={mode}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "6px",
        flex: "1 1 auto",
        minWidth: 0,
        padding: "8px",
        background: "var(--omni-abyss)",
        borderRadius: "6px",
        border: "1px solid var(--omni-hairline)",
        overflowY: "auto",
        scrollbarWidth: "thin",
      }}
    >
      <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
        <input
          data-testid="library-search-input"
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSearch();
          }}
          placeholder="搜索歌曲 / 艺术家 / 专辑"
          aria-label="搜索音乐库"
          style={{
            flex: "1 1 auto",
            minWidth: 0,
            padding: "4px 8px",
            fontSize: "11px",
            background: "var(--omni-panel)",
            color: "var(--omni-fog)",
            border: "1px solid var(--omni-hairline)",
            borderRadius: "4px",
            outline: "none",
          }}
        />
        <button
          type="button"
          data-testid="library-search-btn"
          onClick={handleSearch}
          aria-label="搜索"
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: "26px",
            height: "26px",
            borderRadius: "4px",
            border: "1px solid var(--omni-hairline)",
            background: "transparent",
            color: "var(--omni-fog)",
            cursor: "pointer",
            padding: 0,
          }}
        >
          <Icon name="search" size={12} label="搜索" />
        </button>
      </div>

      {mode === "empty" ? (
        <div
          data-testid="library-song-empty"
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: "8px",
            padding: "24px 0",
            color: "var(--omni-dim)",
            fontSize: "11px",
          }}
        >
          <Icon name="music" size={28} color="var(--omni-dim)" />
          <span>搜索或选中歌单以浏览歌曲</span>
        </div>
      ) : songs.length === 0 ? (
        <div
          data-testid="library-song-empty"
          style={{
            padding: "16px 0",
            textAlign: "center",
            color: "var(--omni-dim)",
            fontSize: "11px",
          }}
        >
          {mode === "search" ? "无匹配歌曲" : "歌单为空"}
        </div>
      ) : (
        <div
          data-testid="library-song-list"
          data-song-count={songs.length}
          style={{ display: "flex", flexDirection: "column", gap: "2px" }}
        >
          {songs.map((song, i) => (
            <LibrarySongRow key={`${song.id}-${i}`} song={song} />
          ))}
        </div>
      )}
    </div>
  );
}

function LibrarySongRow({ song }: { song: LibrarySong }): JSX.Element {
  const title = song.title ?? "未知曲目";
  const artist = song.artist ?? "未知艺术家";
  return (
    <div
      data-testid="library-song-row"
      data-song-id={song.id}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "8px",
        padding: "5px 8px",
        borderRadius: "4px",
        background: "transparent",
        color: "var(--omni-fog)",
        transition: "background-color 160ms ease-out",
      }}
    >
      <Icon name="music2" size={10} color="var(--omni-dim)" />
      <div style={{ flex: "1 1 auto", minWidth: 0, display: "flex", flexDirection: "column", gap: "1px" }}>
        <span
          style={{
            fontSize: "11px",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {title}
        </span>
        <span
          style={{
            fontSize: "9px",
            color: "var(--omni-dim)",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {artist}
          {song.album ? ` · ${song.album}` : ""}
        </span>
      </div>
      <span
        style={{
          fontSize: "9px",
          color: "var(--omni-dim)",
          fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
          flexShrink: 0,
        }}
      >
        {song.duration_s > 0 ? formatTime(song.duration_s) : ""}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 辅助：时间戳 → 「x 分钟前 / x 小时前 / x 天前」
// ---------------------------------------------------------------------------

/** 把秒级时间戳转为相对当前时间的简短文案（用于「上次扫描」显示）。 */
function formatTimeAgo(timestamp: number): string {
  const now = Date.now() / 1000;
  const diff = Math.max(0, now - timestamp);
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  return `${Math.floor(diff / 86400)} 天前`;
}
