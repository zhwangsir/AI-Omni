/**
 * subtitleStore 运行时单例（M7.4）：显影字幕的唯一事实源。
 *
 * M6.3 字幕事件接线随 avatar 系统退役（opentalkingBridge 删除）一并消失；
 * M7.4 改由 voice-status 事件通道驱动——voice.state 进入 speaking 且携带
 * reply 时，桥接层（CaptionLayer）调 begin() + finish(reply) 把完整回复作为
 * final 字幕显影（status 文件通道只给完整文本，无 chunk 流；final 停留渐隐
 * 语义不变）。打断（state 离开 speaking 且未自然 ended）→ hide() 立即收起。
 *
 * 独立成模块便于组件测试经 vi.mock 整体替换——真实定时器不进入 jsdom 测试。
 */
import { createSubtitleStore, type SubtitleStore } from "./subtitleStore";

let singleton: SubtitleStore | null = null;

export function getSubtitleStore(): SubtitleStore {
  singleton ??= createSubtitleStore();
  return singleton;
}
