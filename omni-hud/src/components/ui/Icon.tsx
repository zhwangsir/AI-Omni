/**
 * Icon 封装：lucide-react 是全站唯一图标源（CLAUDE.md 第五节）。
 * 业务代码一律经本组件按名字取用图标，不直接 import lucide-react；
 * 尺寸 / 描边宽度 / 颜色在此统一收口。新图标需求先在此登记。
 */
import {
  Activity,
  Cpu,
  FileText,
  GripHorizontal,
  House,
  ListMusic,
  Mic,
  Moon,
  Music,
  Music2,
  Palette,
  Pause,
  Play,
  Plus,
  Radio,
  Repeat,
  Repeat1,
  Search,
  Shuffle,
  SkipBack,
  SkipForward,
  Square,
  Sun,
  Video,
  Waves,
  X,
  type LucideIcon,
} from "lucide-react";

const ICONS = {
  activity: Activity,
  cpu: Cpu,
  // M18 歌词面板空状态占位
  fileText: FileText,
  grip: GripHorizontal,
  house: House,
  // M17.10 音乐播放控制：play/pause/skip/stop/repeat/shuffle/queue/music/close
  listMusic: ListMusic,
  mic: Mic,
  moon: Moon,
  music: Music,
  music2: Music2,
  pause: Pause,
  play: Play,
  palette: Palette,
  // M19 本地音乐库：plus（添加到歌单）/ search（搜索）
  plus: Plus,
  radio: Radio,
  repeat: Repeat,
  repeat1: Repeat1,
  search: Search,
  shuffle: Shuffle,
  skipBack: SkipBack,
  skipForward: SkipForward,
  square: Square,
  sun: Sun,
  video: Video,
  waves: Waves,
  x: X,
} as const satisfies Record<string, LucideIcon>;

export type IconName = keyof typeof ICONS;

export const ICON_DEFAULT_SIZE = 16;
export const ICON_DEFAULT_STROKE_WIDTH = 1.5;

export interface IconProps {
  name: IconName;
  size?: number;
  strokeWidth?: number;
  /** 颜色 token，默认继承文本色。 */
  color?: string;
  className?: string;
  /** 提供时对辅助技术暴露 role=img 与可访问名；缺省则 aria-hidden。 */
  label?: string;
}

export function Icon({
  name,
  size = ICON_DEFAULT_SIZE,
  strokeWidth = ICON_DEFAULT_STROKE_WIDTH,
  color = "currentColor",
  className,
  label,
}: IconProps) {
  const Glyph = ICONS[name];
  return (
    <Glyph
      size={size}
      strokeWidth={strokeWidth}
      color={color}
      className={className}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    />
  );
}
