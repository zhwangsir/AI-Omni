/**
 * AudioPlayer 隐藏音频元素（M17.10，D17.1 前端 WebAudio 优先）。
 *
 * 单例 ``<audio>`` 挂载到 DOM（hidden），桥接 musicStore 状态 ↔ 实际音频播放：
 * - ``current_song.url`` 变化 → 设置 ``audio.src`` 并按 state 决定是否 play；
 * - ``playerState.state`` 变化 → ``audio.play()`` / ``audio.pause()`` / 停止归零；
 * - ``playerState.position_s`` 变化（与 audio.currentTime 差距 >1.5s 时）→ seek，
 *   处理后端 next/previous 重置进度或跨端 seek，避免自身 timeupdate 反馈环；
 * - ``timeupdate`` 事件 → 节流 1s 推送 position_s 回后端（store.seek 不刷新状态，无反馈环）；
 * - ``ended`` 事件 → 调 ``store.next()`` 切下一首。
 *
 * 不渲染任何可见 UI（仅一个 hidden audio）；图标不涉及。
 * 尊重 prefers-reduced-motion（音频不涉及动画，但遵循全局约定不主动加视觉反馈）。
 */
import { useEffect, useRef, useSyncExternalStore } from "react";

import type { MusicStore } from "../../store/musicStore";

export interface AudioPlayerProps {
  store: MusicStore;
}

/** position_s 与 audio.currentTime 差距超过此阈值才 seek（秒），避免反馈环。 */
const SEEK_THRESHOLD_S = 1.5;

/** timeupdate 推送间隔（毫秒）。 */
const TIMEUPDATE_THROTTLE_MS = 1000;

export function AudioPlayer({ store }: AudioPlayerProps): JSX.Element {
  const state = useSyncExternalStore(store.subscribe, store.getState);
  const player = state.playerState;
  const song = player?.current_song ?? null;
  const songUrl = song?.url ?? null;
  const playState = player?.state ?? "stopped";
  const positionS = player?.position_s ?? 0;

  const audioRef = useRef<HTMLAudioElement | null>(null);
  /** 上次 timeupdate 推送时间戳，节流用。 */
  const lastPushRef = useRef<number>(0);
  /** 标记是否正由 store 状态驱动 seek，避免 timeupdate 即时回推。 */
  const seekingRef = useRef<boolean>(false);

  // current_song.url 变化 → 设置 src
  useEffect(() => {
    const audio = audioRef.current;
    if (audio === null) return;
    if (songUrl === null) {
      // 无 URL（VIP / 无权限）：清空 src，暂停
      if (audio.src !== "") {
        audio.removeAttribute("src");
        audio.load();
      }
      return;
    }
    if (audio.src !== songUrl) {
      audio.src = songUrl;
      audio.load();
    }
  }, [songUrl]);

  // state 变化 → play / pause / stop
  useEffect(() => {
    const audio = audioRef.current;
    if (audio === null) return;
    if (playState === "playing") {
      // play() 在 jsdom 返回 rejected Promise，catch 掉避免未处理 rejection
      void audio.play().catch(() => {});
    } else if (playState === "paused") {
      audio.pause();
    } else {
      // stopped
      audio.pause();
      seekingRef.current = true;
      audio.currentTime = 0;
      seekingRef.current = false;
    }
  }, [playState]);

  // position_s 变化 → seek（仅当与 audio.currentTime 差距超阈值）
  useEffect(() => {
    const audio = audioRef.current;
    if (audio === null) return;
    if (playState === "stopped") return; // stopped 已归零，不重复 seek
    const diff = Math.abs(audio.currentTime - positionS);
    if (diff > SEEK_THRESHOLD_S) {
      seekingRef.current = true;
      audio.currentTime = positionS;
      seekingRef.current = false;
    }
  }, [positionS, playState]);

  // timeupdate → 节流推送 position_s 回后端
  const handleTimeUpdate = (): void => {
    if (seekingRef.current) return;
    const audio = audioRef.current;
    if (audio === null) return;
    const now = Date.now();
    if (now - lastPushRef.current < TIMEUPDATE_THROTTLE_MS) return;
    lastPushRef.current = now;
    const current = audio.currentTime;
    if (Number.isFinite(current) && current >= 0) {
      void store.seek(current);
    }
  };

  // ended → 下一首
  const handleEnded = (): void => {
    void store.next();
  };

  return (
    <audio
      ref={audioRef}
      data-testid="audio-player"
      hidden
      onTimeUpdate={handleTimeUpdate}
      onEnded={handleEnded}
    />
  );
}
