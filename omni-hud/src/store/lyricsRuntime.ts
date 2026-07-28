/**
 * lyricsStore 运行时单例 + 音乐同步器（M18 前端接线）。
 *
 * 职责：
 * 1. 暴露 ``getLyricsStore`` 进程内单例（与 musicRuntime / subtitleRuntime 同款），
 *    供 App.tsx / LyricsDisplay 共享同一份 lyricsStore 实例；
 * 2. ``bindLyricsSync(musicStore, lyricsStore)`` 把 musicStore.playerState.current_song
 *    变化同步到 lyricsStore：
 *    - 切歌（current_song.id 变化）→ ``fetchLyrics(newSongId)`` 拉取新歌词；
 *    - current_song 变 null（停止播放）→ ``clear()`` 清空歌词面板；
 *    - 同一歌曲内 position_s 变化不在此处理——由 LyricsDisplay 的 ``positionS``
 *      prop 驱动 ``refreshCurrentLine``（本地二分，避免高频 IPC）。
 *
 * 单向同步：lyricsStore 只读 musicStore，不反向写。退订在组件卸载 / 测试 teardown
 * 时由返回的清理函数执行。
 */
import type { MusicStore } from "./musicStore";
import { createLyricsStore, type LyricsStore } from "./lyricsStore";

let singleton: LyricsStore | null = null;

/** 获取进程内 lyricsStore 单例（首次调用懒构造）。 */
export function getLyricsStore(): LyricsStore {
  singleton ??= createLyricsStore();
  return singleton;
}

/**
 * 把 musicStore.current_song 变化同步到 lyricsStore。
 *
 * 返回解绑函数（组件卸载 / 测试 teardown 调用）。幂等：多次绑定同一对 store
 * 会产生多个独立订阅，生产环境只绑定一次（App.tsx 挂载时）。
 *
 * position_s 驱动 refreshCurrentLine 不在此处理——由 LyricsDisplay 的
 * ``positionS`` prop 内部 useEffect 负责，避免双重触发。
 */
export function bindLyricsSync(musicStore: MusicStore, lyricsStore: LyricsStore): () => void {
  let lastSongId: string | null = null;

  const onChange = (): void => {
    const player = musicStore.getState().playerState;
    const song = player?.current_song ?? null;
    const songId = song?.id ?? null;
    if (songId === lastSongId) return;
    lastSongId = songId;
    if (songId === null) {
      lyricsStore.clear();
      return;
    }
    void lyricsStore.fetchLyrics(songId);
  };

  // 首次同步：把当前 songId 作为基线，避免挂载即把存量歌曲触发一次 fetch
  // （若 App.tsx 挂载时已有 current_song，仍应 fetch 一次——不设基线）。
  // 但若 musicStore 尚未拉取 playerState（playerState === null），songId=null，
  // 不会触发 fetch；后续 fetchPlayerState 后 onChange 会触发。
  const unsubscribe = musicStore.subscribe(onChange);
  // 首次手动触发一次（若已有 current_song）
  onChange();
  return () => {
    unsubscribe();
    lastSongId = null;
  };
}
