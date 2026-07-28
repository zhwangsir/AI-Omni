/**
 * 音乐播放组件统一导出（M17.10 + M19）。
 *
 * - NowPlaying：完整播放信息卡（封面 / 进度 / 控制按钮）
 * - PlayControlBar：底部精简控制条
 * - LoginQrDialog：扫码登录二维码弹窗
 * - QueueList：播放队列列表
 * - AudioPlayer：隐藏 <audio> 元素（实际音频播放桥接）
 * - LibraryView：本地音乐库浏览视图（M19，扫描/搜索/歌单）
 * - DecryptDialog：加密音频解密弹窗（M19，D19.1 合规）
 *
 * store 经 src/store/musicStore + src/store/libraryStore 导出，不在此重复。
 */
export { NowPlaying } from "./NowPlaying";
export type { NowPlayingProps } from "./NowPlaying";

export { PlayControlBar } from "./PlayControlBar";
export type { PlayControlBarProps } from "./PlayControlBar";

export { LoginQrDialog } from "./LoginQrDialog";
export type { LoginQrDialogProps } from "./LoginQrDialog";

export { QueueList } from "./QueueList";
export type { QueueListProps } from "./QueueList";

export { AudioPlayer } from "./AudioPlayer";
export type { AudioPlayerProps } from "./AudioPlayer";

export { LibraryView } from "./LibraryView";
export type { LibraryViewProps } from "./LibraryView";

export { DecryptDialog } from "./DecryptDialog";
export type { DecryptDialogProps } from "./DecryptDialog";

export {
  REPEAT_MODE_ICON,
  REPEAT_MODE_LABEL,
  REPEAT_MODE_CYCLE,
  nextRepeatMode,
  formatTime,
  formatArtists,
  isPlaying,
  getSongUrl,
} from "./shared";
