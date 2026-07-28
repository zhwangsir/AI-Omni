/**
 * musicMood 音乐状态 → 3D 场景氛围映射测试（M21.5 TDD）：
 * 三档映射：music_playing 活跃（流速提升、bloom 微升）/
 * music_paused 保持（流速降低、维持构图）/
 * music_idle 基线（无音乐 = 默认氛围）。
 *
 * 与 mood.ts（语音氛围）正交：音乐氛围优先级高于语音氛围
 *（音乐播放时音乐氛围覆盖语音氛围；暂停/停止回退语音氛围）。
 *
 * 纯逻辑测试：fake MusicStore，不碰 three / WebGL。
 */
import { describe, expect, it } from "vitest";

import type { PlayerStateName } from "../store/musicStore";
import type { MusicStore } from "../store/musicStore";
import {
  MUSIC_MOOD_BASELINE,
  MUSIC_MOOD_MAX_BLOOM_BOOST,
  MUSIC_MOOD_MAX_FLOW_SCALE,
  MUSIC_MOOD_PAUSED,
  MUSIC_MOOD_PLAYING,
  MUSIC_MOOD_TABLE,
  bindMusicMood,
  clampMusicMoodSpec,
  musicMoodForState,
  type MusicMoodSpec,
} from "./musicMood";

const ALL_STATES: readonly PlayerStateName[] = ["stopped", "playing", "paused"];

describe("musicMood 映射表（三档）", () => {
  it("所有状态全部有定义，且全部落在硬上限内", () => {
    for (const state of ALL_STATES) {
      const spec = MUSIC_MOOD_TABLE[state];
      expect(spec, state).toBeDefined();
      expect(spec.flowScale, state).toBeGreaterThanOrEqual(1);
      expect(spec.flowScale, state).toBeLessThanOrEqual(MUSIC_MOOD_MAX_FLOW_SCALE);
      expect(spec.bloomBoost, state).toBeGreaterThanOrEqual(0);
      expect(spec.bloomBoost, state).toBeLessThanOrEqual(MUSIC_MOOD_MAX_BLOOM_BOOST);
    }
  });

  it("playing 为活跃档（流速 >1.3、bloom 微升），对应 MUSIC_MOOD_PLAYING", () => {
    expect(musicMoodForState("playing", true)).toEqual(MUSIC_MOOD_PLAYING);
    expect(MUSIC_MOOD_PLAYING.flowScale).toBeGreaterThan(1.3);
    expect(MUSIC_MOOD_PLAYING.flowScale).toBeLessThanOrEqual(MUSIC_MOOD_MAX_FLOW_SCALE);
    expect(MUSIC_MOOD_PLAYING.bloomBoost).toBeGreaterThan(0);
    expect(MUSIC_MOOD_PLAYING.bloomBoost).toBeLessThanOrEqual(MUSIC_MOOD_MAX_BLOOM_BOOST);
  });

  it("paused 为保持档（流速接近基线、bloom 微降），对应 MUSIC_MOOD_PAUSED", () => {
    expect(musicMoodForState("paused", true)).toEqual(MUSIC_MOOD_PAUSED);
    // paused 流速低于 playing（保持但不活跃）
    expect(MUSIC_MOOD_PAUSED.flowScale).toBeLessThan(MUSIC_MOOD_PLAYING.flowScale);
    expect(MUSIC_MOOD_PAUSED.flowScale).toBeGreaterThanOrEqual(1);
  });

  it("stopped 为基线档（无音乐 = 默认氛围），对应 MUSIC_MOOD_BASELINE", () => {
    expect(musicMoodForState("stopped", true)).toEqual(MUSIC_MOOD_BASELINE);
    expect(MUSIC_MOOD_BASELINE.flowScale).toBe(1);
    expect(MUSIC_MOOD_BASELINE.bloomBoost).toBe(0);
  });

  it("无当前曲目（hasCurrentSong=false）恒基线，无论 state 为何", () => {
    expect(musicMoodForState("playing", false)).toEqual(MUSIC_MOOD_BASELINE);
    expect(musicMoodForState("paused", false)).toEqual(MUSIC_MOOD_BASELINE);
    expect(musicMoodForState("stopped", false)).toEqual(MUSIC_MOOD_BASELINE);
  });

  it("null / undefined state 回退基线", () => {
    expect(musicMoodForState(null, true)).toEqual(MUSIC_MOOD_BASELINE);
    expect(musicMoodForState(undefined, true)).toEqual(MUSIC_MOOD_BASELINE);
  });
});

describe("clampMusicMoodSpec 倍率硬钳制", () => {
  it("超上限值钳到上限", () => {
    expect(clampMusicMoodSpec({ flowScale: 99, bloomBoost: 99 })).toEqual({
      flowScale: MUSIC_MOOD_MAX_FLOW_SCALE,
      bloomBoost: MUSIC_MOOD_MAX_BLOOM_BOOST,
    });
  });

  it("低于下限值钳到下限（流速不倒车、bloom 不变暗）", () => {
    expect(clampMusicMoodSpec({ flowScale: 0.2, bloomBoost: -1 })).toEqual({
      flowScale: 1,
      bloomBoost: 0,
    });
  });

  it("NaN 回基线", () => {
    expect(clampMusicMoodSpec({ flowScale: Number.NaN, bloomBoost: Number.NaN })).toEqual(
      MUSIC_MOOD_BASELINE,
    );
  });

  it("MUSIC_MOOD_TABLE 所有条目恒满足钳制（模块级硬校验生效）", () => {
    for (const state of ALL_STATES) {
      expect(clampMusicMoodSpec(MUSIC_MOOD_TABLE[state])).toEqual(MUSIC_MOOD_TABLE[state]);
    }
  });
});

/** 可控 fake MusicStore：仅实现 bindMusicMood 消费的契约面。 */
function makeFakeMusicStore(
  initial: PlayerStateName | null,
  hasCurrentSong: boolean,
) {
  let state: PlayerStateName | null = initial;
  let currentSong = hasCurrentSong;
  const listeners = new Set<() => void>();
  const store = {
    getState: () => ({
      playerState: state ? { state, current_song: currentSong ? { id: "s1" } : null } : null,
    }),
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  } as unknown as MusicStore;
  return {
    store,
    listenerCount: () => listeners.size,
    setPlayer(next: PlayerStateName | null): void {
      state = next;
      for (const listener of [...listeners]) listener();
    },
    setCurrentSong(flag: boolean): void {
      currentSong = flag;
      for (const listener of [...listeners]) listener();
    },
  };
}

describe("bindMusicMood 订阅接线", () => {
  it("初始即推送当前状态映射，变化时推送新 mood，映射值不变不重复推送", () => {
    const { store, setPlayer } = makeFakeMusicStore("playing", true);
    const seen: Array<MusicMoodSpec | null> = [];
    const dispose = bindMusicMood(store, { setMusicMood: (mood) => seen.push(mood) });
    expect(seen).toEqual([MUSIC_MOOD_PLAYING]);
    setPlayer("paused");
    expect(seen.at(-1)).toEqual(MUSIC_MOOD_PAUSED);
    setPlayer("paused"); // 状态未变：不重复推送
    expect(seen).toHaveLength(2);
    setPlayer("stopped"); // 回基线
    expect(seen.at(-1)).toEqual(MUSIC_MOOD_BASELINE);
    dispose();
  });

  it("无曲目时初始推基线，曲目出现且 playing 时推送活跃档", () => {
    const { store, setCurrentSong } = makeFakeMusicStore("playing", false);
    const seen: Array<MusicMoodSpec | null> = [];
    const dispose = bindMusicMood(store, { setMusicMood: (mood) => seen.push(mood) });
    expect(seen).toEqual([MUSIC_MOOD_BASELINE]); // 无曲目 → 基线
    setCurrentSong(true); // 曲目出现，playing → 活跃档
    expect(seen.at(-1)).toEqual(MUSIC_MOOD_PLAYING);
    dispose();
  });

  it("dispose 完整：退订后状态变化不再推送，且无监听器残留", () => {
    const { store, setPlayer, listenerCount } = makeFakeMusicStore("playing", true);
    const seen: Array<MusicMoodSpec | null> = [];
    const dispose = bindMusicMood(store, { setMusicMood: (mood) => seen.push(mood) });
    expect(listenerCount()).toBe(1);
    dispose();
    expect(listenerCount()).toBe(0);
    setPlayer("paused");
    expect(seen).toHaveLength(1); // 仅初始推送
  });

  it("reduced-motion：仍推送状态映射（reduced-motion 由 Space 侧消费时归零，store 层不特判）", () => {
    const { store } = makeFakeMusicStore("playing", true);
    const seen: Array<MusicMoodSpec | null> = [];
    const dispose = bindMusicMood(store, { setMusicMood: (mood) => seen.push(mood) });
    // musicMood 层只做映射，不做 reduced-motion 特判（与 mood.ts 一致）
    expect(seen).toEqual([MUSIC_MOOD_PLAYING]);
    dispose();
  });
});
