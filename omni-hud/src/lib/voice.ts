/**
 * voice 桥接（M7.4）：HUD → Rust voice_interrupt command。
 *
 * Rust `voice_interrupt` command spawn `python3 -m omni_voice interrupt` CLI
 * 写控制文件（M7.5 已完成 Python 侧），是常驻语音管道打断当前播报的
 * 唯一跨进程通道。本模块是 TS 侧薄壳封装，沿用 window.ts 的降级模式：
 * 非 Tauri 环境（vitest / 纯 web 预览）静默 no-op；IPC 失败吞掉不抛错，
 * 避免按钮回调抛未处理 Promise rejection。
 *
 * 调用方（CaptionLayer 打断 glyph / WellZone 井心 caption 卡 / 未来其他
 * 入口）统一经 interruptSpeaking() 触发，不直接 invoke。
 */
import { invoke } from "@tauri-apps/api/core";

import { isTauri } from "./window";

export const CMD_VOICE_INTERRUPT = "voice_interrupt";

/**
 * 打断宿主语音管道当前播报（写控制文件 → 管道 50ms 轮询消费 →
 * 停播放 + 迁回 wake_listening + 发 voice.interrupted 事件）。
 *
 * 非阻塞、不抛错——IPC 失败仅静默降级；调用方无需 try/catch。
 */
export async function interruptSpeaking(): Promise<void> {
  if (!isTauri()) return;
  try {
    await invoke(CMD_VOICE_INTERRUPT);
  } catch {
    // IPC 错误（command 未注册 / Rust panic / Python 退出码非零）静默吞掉：
    // 打断是「尽力而为」通道，失败时管道自身超时会自然迁态，不致命。
  }
}
