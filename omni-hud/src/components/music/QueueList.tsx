/**
 * QueueList 播放队列列表（M17.10）。
 *
 * 渲染 playerState.queue：当前曲目高亮（accent 左边框 + 加粗），
 * 点击任意项调 store.play({index}) 跳转播放。空队列显示占位文案。
 *
 * 订阅 musicStore.playerState；Film Atelier 暗房风（§六）；
 * 图标经 Icon.tsx（§五）。纯展示 + 点击跳转，不持状态。
 */
import { useCallback, useMemo, useSyncExternalStore } from "react";

import type { MusicStore, Song } from "../../store/musicStore";
import { Icon } from "../ui/Icon";
import { formatArtists } from "./shared";

export interface QueueListProps {
  store: MusicStore;
  /** 最大显示行数，缺省全部（不限制）。 */
  maxRows?: number;
}

export function QueueList({ store, maxRows }: QueueListProps): JSX.Element {
  const state = useSyncExternalStore(store.subscribe, store.getState);
  const player = state.playerState;
  const queue = player?.queue ?? [];
  const currentIndex = player?.current_index ?? -1;

  const items = useMemo(() => {
    const list = maxRows !== undefined ? queue.slice(0, maxRows) : queue;
    return list;
  }, [queue, maxRows]);

  const handlePlay = useCallback(
    (index: number) => {
      void store.play({ index });
    },
    [store],
  );

  if (queue.length === 0) {
    return (
      <div
        data-testid="queue-list"
        data-empty="true"
        aria-label="播放队列为空"
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          padding: "16px 14px",
          color: "var(--omni-dim)",
          fontSize: "12px",
          background: "var(--omni-panel)",
          borderRadius: "var(--omni-radius)",
          border: "1px solid var(--omni-hairline)",
        }}
      >
        <Icon name="listMusic" size={14} color="var(--omni-dim)" />
        <span>队列为空</span>
      </div>
    );
  }

  return (
    <div
      data-testid="queue-list"
      data-empty="false"
      data-queue-length={queue.length}
      aria-label={`播放队列，共 ${queue.length} 首`}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "2px",
        padding: "8px",
        background: "var(--omni-panel)",
        borderRadius: "var(--omni-radius)",
        border: "1px solid var(--omni-hairline)",
        maxHeight: "320px",
        overflowY: "auto",
        scrollbarWidth: "thin",
        scrollbarColor: "rgba(216, 217, 220, 0.18) transparent",
      }}
    >
      {items.map((song, i) => (
        <QueueRow
          key={`${song.source}-${song.id}-${i}`}
          song={song}
          index={i}
          isCurrent={i === currentIndex}
          onPlay={handlePlay}
        />
      ))}
    </div>
  );
}

interface QueueRowProps {
  song: Song;
  index: number;
  isCurrent: boolean;
  onPlay: (index: number) => void;
}

function QueueRow({ song, index, isCurrent, onPlay }: QueueRowProps): JSX.Element {
  return (
    <button
      type="button"
      data-testid="queue-list-row"
      data-index={index}
      data-current={isCurrent ? "true" : "false"}
      data-song-id={song.id}
      onClick={() => onPlay(index)}
      aria-label={`播放第 ${index + 1} 首：${song.name}`}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "10px",
        padding: "6px 10px",
        borderRadius: "6px",
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
      <span
        style={{
          flexShrink: 0,
          width: "20px",
          fontSize: "10px",
          color: "var(--omni-dim)",
          fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
          textAlign: "right",
        }}
      >
        {isCurrent ? <Icon name="play" size={10} color="var(--omni-accent)" /> : index + 1}
      </span>
      <div style={{ flex: "1 1 auto", minWidth: 0, display: "flex", flexDirection: "column", gap: "1px" }}>
        <span
          style={{
            fontSize: "12px",
            fontWeight: isCurrent ? 600 : 400,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {song.name}
        </span>
        <span
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
    </button>
  );
}
