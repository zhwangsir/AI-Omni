/**
 * PlayControlBar 底部播放控制条（M17.10）。
 *
 * NowPlaying 的精简版，固定在窗口底部（与 AgentPanel 同区不冲突时使用）：
 * - 当前歌名 + 艺术家（单行省略）；
 * - 上一首 / 播放-暂停 / 下一首 按钮；
 * - 细进度条（position_s / duration_s，可 seek）；
 * - 循环模式图标（点击切换）。
 *
 * 无 current_song 时渲染紧凑占位条（Music 图标 + 「未在播放」），不占太多高度。
 * 订阅 musicStore.playerState；Film Atelier 暗房风（半透明深底 + blur）。
 * 图标全经 Icon.tsx（CLAUDE.md §五）。
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

export interface PlayControlBarProps {
  store: MusicStore;
}

/** 紧凑控制按钮样式。 */
const COMPACT_BTN_STYLE: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: "28px",
  height: "28px",
  borderRadius: "50%",
  border: "1px solid transparent",
  background: "transparent",
  color: "var(--omni-fog)",
  cursor: "pointer",
  transition: "color 200ms ease-out, background-color 200ms ease-out",
  padding: 0,
  flexShrink: 0,
};

export function PlayControlBar({ store }: PlayControlBarProps): JSX.Element {
  const state = useSyncExternalStore(store.subscribe, store.getState);
  const player = state.playerState;
  const song = player?.current_song ?? null;
  const playing = isPlaying(player?.state);
  const duration = song?.duration_s ?? 0;
  const position = player?.position_s ?? 0;

  const repeatMode: RepeatMode = player?.repeat_mode ?? "sequence";

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

  const progressPct = useMemo(() => {
    if (duration <= 0) return 0;
    return Math.min(100, (position / duration) * 100);
  }, [position, duration]);

  if (song === null) {
    return (
      <div
        data-testid="play-control-bar"
        data-empty="true"
        aria-label="未在播放"
        style={{
          display: "flex",
          alignItems: "center",
          gap: "10px",
          padding: "8px 14px",
          height: "44px",
          boxSizing: "border-box",
          color: "var(--omni-dim)",
          background: "rgba(11, 12, 14, 0.72)",
          backdropFilter: "blur(8px)",
          WebkitBackdropFilter: "blur(8px)",
          borderTop: "1px solid var(--omni-hairline)",
          pointerEvents: "auto",
          fontSize: "12px",
        }}
      >
        <Icon name="music" size={14} color="var(--omni-dim)" />
        <span style={{ letterSpacing: "0.06em" }}>未在播放</span>
      </div>
    );
  }

  return (
    <div
      data-testid="play-control-bar"
      data-empty="false"
      data-player-state={player?.state ?? "stopped"}
      aria-label={`播放控制条：${song.name}`}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "12px",
        padding: "8px 14px",
        minHeight: "48px",
        boxSizing: "border-box",
        background: "rgba(11, 12, 14, 0.72)",
        backdropFilter: "blur(8px)",
        WebkitBackdropFilter: "blur(8px)",
        borderTop: "1px solid var(--omni-hairline)",
        pointerEvents: "auto",
      }}
    >
      {/* 曲目信息（左） */}
      <div
        style={{
          flex: "0 1 180px",
          minWidth: 0,
          display: "flex",
          flexDirection: "column",
          gap: "1px",
        }}
      >
        <span
          data-testid="play-control-bar-title"
          style={{
            fontSize: "12px",
            color: "var(--omni-fog)",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {song.name}
        </span>
        <span
          data-testid="play-control-bar-artists"
          style={{
            fontSize: "10px",
            color: "var(--omni-dim)",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {formatArtists(song.artists)}
        </span>
      </div>

      {/* 控制 + 进度（中，flex 占满） */}
      <div
        style={{
          flex: "1 1 auto",
          display: "flex",
          alignItems: "center",
          gap: "10px",
          minWidth: 0,
        }}
      >
        <button
          type="button"
          data-testid="play-control-bar-previous"
          onClick={() => void store.previous()}
          aria-label="上一首"
          style={COMPACT_BTN_STYLE}
        >
          <Icon name="skipBack" size={14} label="上一首" />
        </button>
        <button
          type="button"
          data-testid="play-control-bar-play-pause"
          onClick={handlePlayPause}
          aria-label={playing ? "暂停" : "播放"}
          style={{ ...COMPACT_BTN_STYLE, color: "var(--omni-accent)" }}
        >
          <Icon name={playing ? "pause" : "play"} size={16} label={playing ? "暂停" : "播放"} />
        </button>
        <button
          type="button"
          data-testid="play-control-bar-next"
          onClick={() => void store.next()}
          aria-label="下一首"
          style={COMPACT_BTN_STYLE}
        >
          <Icon name="skipForward" size={14} label="下一首" />
        </button>

        {/* 细进度条 */}
        <input
          data-testid="play-control-bar-progress"
          type="range"
          min={0}
          max={duration > 0 ? duration : 0}
          step={1}
          value={Math.min(position, duration)}
          onChange={handleSeek}
          aria-label="播放进度"
          style={{
            flex: "1 1 auto",
            minWidth: "60px",
            height: "3px",
            appearance: "none",
            background: `linear-gradient(to right, var(--omni-accent) ${progressPct}%, var(--omni-hairline) ${progressPct}%)`,
            borderRadius: "2px",
            cursor: "pointer",
          }}
        />
        <span
          style={{
            fontSize: "10px",
            color: "var(--omni-dim)",
            fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
            flexShrink: 0,
          }}
        >
          {formatTime(position)} / {formatTime(duration)}
        </span>
      </div>

      {/* 循环模式（右） */}
      <button
        type="button"
        data-testid="play-control-bar-repeat"
        onClick={handleRepeat}
        aria-label={REPEAT_MODE_LABEL[repeatMode]}
        title={REPEAT_MODE_LABEL[repeatMode]}
        data-repeat-mode={repeatMode}
        style={{
          ...COMPACT_BTN_STYLE,
          color: repeatMode === "sequence" ? "var(--omni-dim)" : "var(--omni-accent)",
          flexShrink: 0,
        }}
      >
        <Icon name={REPEAT_MODE_ICON[repeatMode]} size={14} label={REPEAT_MODE_LABEL[repeatMode]} />
      </button>
    </div>
  );
}
