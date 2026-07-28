/**
 * 音乐组件共享辅助（M17.10）。
 *
 * NowPlaying / PlayControlBar / QueueList 共用的循环模式图标映射、
 * 时间格式化与状态文案。纯函数无副作用，便于单测。
 */
import type { IconName } from "../ui/Icon";
import type { PlayerStateName, RepeatMode, Song } from "../../store/musicStore";

/** 循环模式 → Icon 名（Icon.tsx 登记的 lucide 图标）。 */
export const REPEAT_MODE_ICON: Record<RepeatMode, IconName> = {
  sequence: "listMusic",
  list_loop: "repeat",
  single: "repeat1",
  random: "shuffle",
};

/** 循环模式 → 中文短标签（aria-label / title）。 */
export const REPEAT_MODE_LABEL: Record<RepeatMode, string> = {
  sequence: "顺序播放",
  list_loop: "列表循环",
  single: "单曲循环",
  random: "随机播放",
};

/** 循环模式切换顺序：sequence → list_loop → single → random → sequence。 */
export const REPEAT_MODE_CYCLE: readonly RepeatMode[] = [
  "sequence",
  "list_loop",
  "single",
  "random",
];

/** 取下一个循环模式（用于点击切换按钮）。 */
export function nextRepeatMode(mode: RepeatMode): RepeatMode {
  const idx = REPEAT_MODE_CYCLE.indexOf(mode);
  const nextIdx = (idx + 1) % REPEAT_MODE_CYCLE.length;
  return REPEAT_MODE_CYCLE[nextIdx]!;
}

/** 播放状态 → 是否正在播放。 */
export function isPlaying(state: PlayerStateName | null | undefined): boolean {
  return state === "playing";
}

/**
 * 秒数 → "m:ss" 文案（如 75 → "1:15"）；NaN / 负数 → "0:00"。
 * 超过 1 小时 → "h:mm:ss"。
 */
export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** 艺术家列表 → 拼接字符串（"周杰伦 / 费玉清"）；空 → "未知艺术家"。 */
export function formatArtists(artists: readonly string[]): string {
  return artists.length > 0 ? artists.join(" / ") : "未知艺术家";
}

/** 取当前曲目的可播放 URL（null 表示 VIP / 无权限）。 */
export function getSongUrl(song: Song | null): string | null {
  return song?.url ?? null;
}
