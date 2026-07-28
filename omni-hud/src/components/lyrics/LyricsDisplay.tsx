/**
 * LyricsDisplay 同步歌词面板（M18 前端）。
 *
 * 订阅 lyricsStore，渲染解析后的歌词行列表；当前行高亮（accent + 加粗），
 * 非当前行雾化（fog + 缩小）。逐字行在 currentWordIndex 非空时高亮当前字。
 * 翻译在原文下方渲染（更小、二级色）。
 *
 * 自动滚动当前行进入视区（useEffect + scrollIntoView，``typeof`` 守卫 jsdom）。
 * 偏移指示器显示 ``+N.Ns`` / ``-N.Ns``。空状态显示 FileText 图标 + 「暂无歌词」。
 *
 * Film Atelier 暗房风格（CLAUDE.md §六）：rgba 半透明深底 + backdrop-filter blur、
 * 低亮度、克制动画（220ms ease-out，prefers-reduced-motion 时禁用）、不闪烁。
 * 图标经 Icon.tsx（CLAUDE.md §五，禁 emoji / 禁 lucide 直 import）。
 * 容器 pointer-events:none —— 纯展示组件，不拦截桌面交互。
 *
 * ``positionS`` prop 由父组件（musicStore.playerState.position_s 或 AudioPlayer
 * timeupdate）驱动，组件内 useEffect 调 ``store.refreshCurrentLine(positionS)``，
 * 本地二分查找更新索引，**不每帧打 IPC**（性能红线）。
 */
import { useEffect, useSyncExternalStore } from "react";

import type { LyricsLine, LyricsStore } from "../../store/lyricsStore";
import { Icon } from "../ui/Icon";

export interface LyricsDisplayProps {
  /** lyrics store 单例（App.tsx module-level singleton 注入）。 */
  store: LyricsStore;
  /** 当前播放位置（秒），驱动 refreshCurrentLine；缺省不驱动。 */
  positionS?: number;
}

/** 偏移格式化：+0.3s / -1.2s / +0.0s（固定一位小数 + 符号）。 */
function formatOffset(offsetS: number): string {
  if (!Number.isFinite(offsetS)) return "+0.0s";
  const sign = offsetS >= 0 ? "+" : "-";
  const abs = Math.abs(offsetS).toFixed(1);
  return `${sign}${abs}s`;
}

/** 容器基础样式（暗房克制风 + 非交互）。 */
const ROOT_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "2px",
  padding: "16px 14px",
  background: "var(--omni-panel)",
  borderRadius: "var(--omni-radius)",
  border: "1px solid var(--omni-hairline)",
  backdropFilter: "blur(8px)",
  WebkitBackdropFilter: "blur(8px)",
  maxHeight: "420px",
  overflowY: "auto",
  scrollbarWidth: "thin",
  scrollbarColor: "rgba(216, 217, 220, 0.18) transparent",
  pointerEvents: "none",
  position: "relative",
};

/** 偏移指示器样式（右上角 mono 小字）。 */
const OFFSET_STYLE: React.CSSProperties = {
  position: "absolute",
  top: "8px",
  right: "10px",
  fontSize: "10px",
  color: "var(--omni-dim)",
  fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
  letterSpacing: "0.06em",
  pointerEvents: "none",
};

export function LyricsDisplay({ store, positionS }: LyricsDisplayProps): JSX.Element {
  const state = useSyncExternalStore(store.subscribe, store.getState);
  const lyrics = state.currentLyrics;
  const parsed = lyrics?.parsed ?? [];
  const currentIndex = state.currentIndex;
  const currentWordIndex = state.currentWordIndex;
  const reducedMotion =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // positionS 变化 → 本地二分查找更新当前行（不打 IPC）
  useEffect(() => {
    if (positionS === undefined) return;
    if (!Number.isFinite(positionS)) return;
    store.refreshCurrentLine(positionS);
  }, [positionS, store]);

  // 当前行变化 → 自动滚动进入视区（typeof 守卫 jsdom / 非 DOM 环境）
  useEffect(() => {
    if (currentIndex < 0 || parsed.length === 0) return;
    const el = document.querySelector<HTMLElement>(
      `[data-testid="lyrics-row"][data-current="true"]`,
    );
    if (el === null) return;
    // typeof 守卫：jsdom 可能未实现 scrollIntoView
    if (typeof el.scrollIntoView !== "function") return;
    el.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "center" });
  }, [currentIndex, parsed.length, reducedMotion]);

  // 空状态：无歌词 / parsed 为空
  const isEmpty = lyrics === null || parsed.length === 0;
  if (isEmpty) {
    return (
      <div
        data-testid="lyrics-display"
        data-empty="true"
        data-source={lyrics?.source ?? "none"}
        data-reduced-motion={reducedMotion ? "true" : "false"}
        data-error={state.error ?? undefined}
        aria-label={state.error !== null ? `歌词错误：${state.error}` : "暂无歌词"}
        style={{ ...ROOT_STYLE, alignItems: "center", justifyContent: "center", gap: "8px" }}
      >
        <Icon name="fileText" size={24} color="var(--omni-dim)" label="暂无歌词" />
        <span style={{ fontSize: "12px", color: "var(--omni-dim)", letterSpacing: "0.1em" }}>
          {state.error !== null ? state.error : "暂无歌词"}
        </span>
      </div>
    );
  }

  return (
    <div
      data-testid="lyrics-display"
      data-empty="false"
      data-source={lyrics!.source}
      data-current-index={String(currentIndex)}
      data-reduced-motion={reducedMotion ? "true" : "false"}
      aria-label={`歌词面板，当前第 ${currentIndex + 1} 行`}
      style={ROOT_STYLE}
    >
      {/* 偏移指示器 */}
      <span data-testid="lyrics-offset" style={OFFSET_STYLE}>
        {formatOffset(state.offsetS)}
      </span>
      {parsed.map((line, idx) => (
        <LyricsRow
          key={`lyrics-${idx}-${line.time_s}`}
          line={line}
          isCurrent={idx === currentIndex}
          currentWordIndex={isCurrentLine(idx, currentIndex) ? currentWordIndex : null}
        />
      ))}
    </div>
  );
}

/** 判断 idx 是否为当前行（抽出便于可读性）。 */
function isCurrentLine(idx: number, currentIndex: number): boolean {
  return idx === currentIndex;
}

interface LyricsRowProps {
  line: LyricsLine;
  isCurrent: boolean;
  /** 仅当前行传入；非当前行传 null。 */
  currentWordIndex: number | null;
}

function LyricsRow({ line, isCurrent, currentWordIndex }: LyricsRowProps): JSX.Element {
  return (
    <div
      data-testid="lyrics-row"
      data-current={isCurrent ? "true" : "false"}
      data-time={line.time_s}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "2px",
        padding: isCurrent ? "6px 8px" : "4px 8px",
        borderRadius: "4px",
        transition: isCurrent
          ? "color 220ms ease-out, background-color 220ms ease-out"
          : "color 220ms ease-out",
        background: isCurrent ? "rgba(201, 168, 106, 0.06)" : "transparent",
      }}
    >
      <LyricsLineText
        line={line}
        isCurrent={isCurrent}
        currentWordIndex={currentWordIndex}
      />
      {line.translation !== null ? (
        <span
          data-testid="lyrics-row-translation"
          style={{
            fontSize: "11px",
            color: isCurrent ? "var(--omni-dim)" : "var(--omni-dim)",
            opacity: isCurrent ? 0.9 : 0.6,
            lineHeight: 1.4,
          }}
        >
          {line.translation}
        </span>
      ) : null}
    </div>
  );
}

interface LyricsLineTextProps {
  line: LyricsLine;
  isCurrent: boolean;
  currentWordIndex: number | null;
}

function LyricsLineText({
  line,
  isCurrent,
  currentWordIndex,
}: LyricsLineTextProps): JSX.Element {
  // 非当前行 / 无 words / 当前字为 null → 整行文本渲染
  if (!isCurrent || line.words === null || line.words.length === 0 || currentWordIndex === null) {
    return (
      <span
        style={{
          fontSize: isCurrent ? "14px" : "12px",
          fontWeight: isCurrent ? 600 : 400,
          color: isCurrent ? "var(--omni-accent)" : "var(--omni-fog)",
          opacity: isCurrent ? 1 : 0.7,
          lineHeight: 1.5,
          letterSpacing: "0.02em",
        }}
      >
        {line.text}
      </span>
    );
  }
  // 当前行 + 逐字高亮：渲染每个字，当前字 accent + 加粗
  return (
    <span
      style={{
        fontSize: "14px",
        fontWeight: 600,
        color: "var(--omni-accent)",
        lineHeight: 1.5,
        letterSpacing: "0.02em",
      }}
    >
      {line.words.map((word, idx) => {
        const isCurrentWord = idx === currentWordIndex;
        return (
          <span
            key={`word-${idx}-${word.time_s}`}
            data-testid="lyrics-word"
            data-current={isCurrentWord ? "true" : "false"}
            style={{
              color: isCurrentWord ? "var(--omni-accent)" : "var(--omni-fog)",
              opacity: isCurrentWord ? 1 : 0.55,
              fontWeight: isCurrentWord ? 700 : 500,
              transition: "color 160ms ease-out, opacity 160ms ease-out",
            }}
          >
            {isCurrentWord ? (
              <span
                data-testid="lyrics-word-current"
                style={{
                  background: "transparent",
                  color: "var(--omni-accent)",
                  fontWeight: 700,
                }}
              >
                {word.char}
              </span>
            ) : (
              word.char
            )}
          </span>
        );
      })}
    </span>
  );
}
