/**
 * musicStore 运行时单例（M17.10 + M18 接线）。
 *
 * 进程内唯一 musicStore 实例，供 App.tsx / AudioPlayer / NowPlaying /
 * LyricsDisplay 等共享同一份播放器状态。与 statusRuntime / subtitleRuntime 同款
 * 懒构造单例——测试经 ``createMusicStore({ invoker })`` 自建实例，不读本单例。
 *
 * M18 起 LyricsDisplay 经 ``bindLyricsSync`` 订阅 musicStore.current_song 变化
 * 触发 lyricsStore.fetchLyrics；position_s 由 LyricsDisplay 的 ``positionS`` prop
 * 驱动 ``refreshCurrentLine``（本地二分，不打 IPC）。
 */
import { createMusicStore, type MusicStore } from "./musicStore";

let singleton: MusicStore | null = null;

/** 获取进程内 musicStore 单例（首次调用懒构造）。 */
export function getMusicStore(): MusicStore {
  singleton ??= createMusicStore();
  return singleton;
}
