/**
 * NowPlaying 当前播放信息卡（M17.10）。
 *
 * 完整播放信息展示 + 控制：
 * - 封面图（cover_url，无则暗房灰底 + Music 图标占位）；
 * - 歌名 / 艺术家 / 专辑（mono 小字 label）；
 * - 进度条（position_s / duration_s，可拖动 seek，range 输入）；
 * - 控制按钮：上一首 / 播放-暂停 / 下一首 / 停止 / 循环模式切换；
 * - 无 current_song 时显示空状态占位（Music 图标 + 「未在播放」）。
 *
 * 订阅 musicStore.playerState（useSyncExternalStore），按钮回调直接调 store action。
 * Film Atelier 暗房风（CLAUDE.md §六）：rgba 半透明深底 + backdrop-filter blur、
 * 低亮度、克制动画（240ms ease-out）、不闪烁、对比度满足可读性。
 * 图标全经 Icon.tsx 封装（CLAUDE.md §五，禁 emoji / 禁 lucide 直 import / 禁 SVG）。
 */
import { useCallback, useMemo, useSyncExternalStore } from "react";

import type { MusicStore, RepeatMode } from "../../store/musicStore";
import { Icon } from "../ui/Icon";
import {
  REPEAT_MODE_ICON,
  REPEAT_MODE_LABEL,
  formatArtists,
  formatTime,
  isPlaying,
  nextRepeatMode,
} from "./shared";

export interface NowPlayingProps {
  store: MusicStore;
}

/** 控制按钮基础样式（暗房克制风）。 */
const CTRL_BTN_STYLE: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: "36px",
  height: "36px",
  borderRadius: "50%",
  border: "1px solid var(--omni-hairline)",
  background: "transparent",
  color: "var(--omni-fog)",
  cursor: "pointer",
  transition: "background-color 200ms ease-out, color 200ms ease-out, border-color 200ms ease-out",
  padding: 0,
};

/** 主播放按钮（强调色）。 */
const PRIMARY_BTN_STYLE: React.CSSProperties = {
  ...CTRL_BTN_STYLE,
  width: "44px",
  height: "44px",
  color: "var(--omni-abyss)",
  background: "var(--omni-accent)",
  borderColor: "var(--omni-accent)",
};

export function NowPlaying({ store }: NowPlayingProps): JSX.Element {
  const state = useSyncExternalStore(store.subscribe, store.getState);
  const player = state.playerState;
  const song = player?.current_song ?? null;
  const playing = isPlaying(player?.state);
  const duration = song?.duration_s ?? 0;
  const position = player?.position_s ?? 0;

  const repeatMode: RepeatMode = player?.repeat_mode ?? "sequence";
  const repeatIcon = REPEAT_MODE_ICON[repeatMode];
  const repeatLabel = REPEAT_MODE_LABEL[repeatMode];

  const handleSeek = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const value = Number(e.target.value);
      if (Number.isFinite(value)) {
        void store.seek(value);
      }
    },
    [store],
  );

  const handlePlayPause = useCallback(() => {
    if (playing) {
      void store.pause();
    } else {
      void store.resume();
    }
  }, [playing, store]);

  const handleRepeat = useCallback(() => {
    void store.setRepeatMode(nextRepeatMode(repeatMode));
  }, [repeatMode, store]);

  const artistsText = useMemo(() => (song ? formatArtists(song.artists) : ""), [song]);
  const progressPct = useMemo(() => {
    if (duration <= 0) return 0;
    return Math.min(100, (position / duration) * 100);
  }, [position, duration]);

  if (song === null) {
    return (
      <div
        data-testid="now-playing"
        data-empty="true"
        aria-label="当前无播放"
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "10px",
          padding: "32px 20px",
          color: "var(--omni-dim)",
          background: "var(--omni-panel)",
          borderRadius: "var(--omni-radius)",
          border: "1px solid var(--omni-hairline)",
        }}
      >
        <Icon name="music" size={28} color="var(--omni-dim)" label="未在播放" />
        <span style={{ fontSize: "12px", letterSpacing: "0.1em" }}>未在播放</span>
      </div>
    );
  }

  return (
    <div
      data-testid="now-playing"
      data-empty="false"
      data-player-state={player?.state ?? "stopped"}
      aria-label={`正在播放：${song.name}`}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "16px",
        padding: "20px",
        background: "var(--omni-panel)",
        borderRadius: "var(--omni-radius)",
        border: "1px solid var(--omni-hairline)",
        backdropFilter: "blur(8px)",
        WebkitBackdropFilter: "blur(8px)",
      }}
    >
      {/* 封面 + 曲目信息 */}
      <div style={{ display: "flex", gap: "16px", alignItems: "center" }}>
        {song.cover_url ? (
          <img
            data-testid="now-playing-cover"
            src={song.cover_url}
            alt={`${song.name} 封面`}
            style={{
              width: "96px",
              height: "96px",
              borderRadius: "8px",
              objectFit: "cover",
              flexShrink: 0,
              background: "var(--omni-abyss)",
            }}
          />
        ) : (
          <div
            data-testid="now-playing-cover"
            aria-hidden="true"
            style={{
              width: "96px",
              height: "96px",
              borderRadius: "8px",
              flexShrink: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "var(--omni-abyss)",
              border: "1px solid var(--omni-hairline)",
            }}
          >
            <Icon name="music" size={32} color="var(--omni-dim)" />
          </div>
        )}

        <div style={{ flex: "1 1 auto", minWidth: 0, display: "flex", flexDirection: "column", gap: "4px" }}>
          <span
            data-testid="now-playing-title"
            style={{
              fontSize: "15px",
              fontWeight: 600,
              color: "var(--omni-fog)",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {song.name}
          </span>
          <span
            data-testid="now-playing-artists"
            style={{
              fontSize: "12px",
              color: "var(--omni-dim)",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {artistsText}
          </span>
          {song.album ? (
            <span
              data-testid="now-playing-album"
              style={{
                fontSize: "11px",
                color: "var(--omni-dim)",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
                letterSpacing: "0.06em",
              }}
            >
              {song.album}
            </span>
          ) : null}
        </div>
      </div>

      {/* 进度条 */}
      <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
        <input
          data-testid="now-playing-progress"
          type="range"
          min={0}
          max={duration > 0 ? duration : 0}
          step={1}
          value={Math.min(position, duration)}
          onChange={handleSeek}
          aria-label="播放进度"
          style={{
            width: "100%",
            height: "4px",
            appearance: "none",
            background: `linear-gradient(to right, var(--omni-accent) ${progressPct}%, var(--omni-hairline) ${progressPct}%)`,
            borderRadius: "2px",
            cursor: "pointer",
          }}
        />
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: "11px",
            color: "var(--omni-dim)",
            fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
          }}
        >
          <span data-testid="now-playing-position">{formatTime(position)}</span>
          <span data-testid="now-playing-duration">{formatTime(duration)}</span>
        </div>
      </div>

      {/* 控制按钮 */}
      <div
        data-testid="now-playing-controls"
        style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "12px" }}
      >
        <button
          type="button"
          data-testid="now-playing-previous"
          onClick={() => void store.previous()}
          aria-label="上一首"
          style={CTRL_BTN_STYLE}
        >
          <Icon name="skipBack" size={16} label="上一首" />
        </button>
        <button
          type="button"
          data-testid="now-playing-play-pause"
          onClick={handlePlayPause}
          aria-label={playing ? "暂停" : "播放"}
          style={PRIMARY_BTN_STYLE}
        >
          <Icon name={playing ? "pause" : "play"} size={18} label={playing ? "暂停" : "播放"} />
        </button>
        <button
          type="button"
          data-testid="now-playing-next"
          onClick={() => void store.next()}
          aria-label="下一首"
          style={CTRL_BTN_STYLE}
        >
          <Icon name="skipForward" size={16} label="下一首" />
        </button>
        <button
          type="button"
          data-testid="now-playing-stop"
          onClick={() => void store.stop()}
          aria-label="停止"
          style={CTRL_BTN_STYLE}
        >
          <Icon name="square" size={14} label="停止" />
        </button>
        <button
          type="button"
          data-testid="now-playing-repeat"
          onClick={handleRepeat}
          aria-label={repeatLabel}
          title={repeatLabel}
          data-repeat-mode={repeatMode}
          style={{
            ...CTRL_BTN_STYLE,
            color: repeatMode === "sequence" ? "var(--omni-dim)" : "var(--omni-accent)",
            borderColor: repeatMode === "sequence" ? "var(--omni-hairline)" : "var(--omni-accent)",
          }}
        >
          <Icon name={repeatIcon} size={16} label={repeatLabel} />
        </button>
      </div>
    </div>
  );
}
