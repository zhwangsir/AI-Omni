/**
 * musicMood 音乐状态 → 3D 场景氛围映射（M21.5）：
 * musicStore playerState.state + hasCurrentSong → 流场流速倍率 + bloom 微升。
 * 三档：music_playing 活跃 / music_paused 保持 / music_idle(stopped) 基线。
 *
 * 与 mood.ts（语音氛围）正交：音乐氛围优先级高于语音氛围
 *（音乐播放时音乐氛围覆盖语音氛围；暂停/停止回退语音氛围）。
 * 倍率硬钳制（流速 ≤×2.2、bloom 增量 ≤0.18）——活跃但不失控，克制红线。
 *
 * 纯逻辑模块：不依赖 three / WebGL，fake MusicStore 可独立单测。
 */
import type { MusicStore, PlayerStateName } from "../store/musicStore";

/** 音乐氛围规格：与 MoodSpec 同构，便于复用 Space.setMood。 */
export interface MusicMoodSpec {
  /** 流场流速倍率 [1, MUSIC_MOOD_MAX_FLOW_SCALE]：1 = 平静基线。 */
  readonly flowScale: number;
  /** bloom 强度增量 [0, MUSIC_MOOD_MAX_BLOOM_BOOST]：0 = 持平基线。 */
  readonly bloomBoost: number;
}

/** 平静基线：漂移 ×1.0，bloom 不加码。 */
export const MUSIC_MOOD_BASELINE: MusicMoodSpec = { flowScale: 1, bloomBoost: 0 };
/** 流速倍率硬上限（音乐模式略高于语音：×2.2，配合节奏粒子脉冲）。 */
export const MUSIC_MOOD_MAX_FLOW_SCALE = 2.2;
/** bloom 增量硬上限（音乐模式略高于语音：0.18，配合 beat 脉冲叠加）。 */
export const MUSIC_MOOD_MAX_BLOOM_BOOST = 0.18;

/** playing 档：活跃（流速 ×1.8、bloom +0.12，配合节奏粒子脉冲）。 */
export const MUSIC_MOOD_PLAYING: MusicMoodSpec = { flowScale: 1.8, bloomBoost: 0.12 };
/** paused 档：保持（流速 ×1.05、bloom +0.02，维持构图不活跃）。 */
export const MUSIC_MOOD_PAUSED: MusicMoodSpec = { flowScale: 1.05, bloomBoost: 0.02 };

/**
 * 三档全映射（条目由单测逐态钉死、消费点再经 clampMusicMoodSpec 二次钳制）。
 * stopped = 基线（无音乐 = 默认氛围，回退语音 mood）。
 */
export const MUSIC_MOOD_TABLE: Readonly<Record<PlayerStateName, MusicMoodSpec>> = {
  stopped: MUSIC_MOOD_BASELINE,
  playing: MUSIC_MOOD_PLAYING,
  paused: MUSIC_MOOD_PAUSED,
};

/**
 * 音乐状态 → 氛围规格。
 * - hasCurrentSong=false 时恒基线（无曲目 = 无音乐模式）
 * - null / undefined state 回退基线
 */
export function musicMoodForState(
  state: PlayerStateName | null | undefined,
  hasCurrentSong: boolean,
): MusicMoodSpec {
  if (!hasCurrentSong) return MUSIC_MOOD_BASELINE;
  if (state && state in MUSIC_MOOD_TABLE) {
    return MUSIC_MOOD_TABLE[state];
  }
  return MUSIC_MOOD_BASELINE;
}

/**
 * 倍率硬钳制：flowScale ∈ [1, MAX]（不倒车）、bloomBoost ∈ [0, MAX]（不变暗）；
 * 任一分量 NaN 视为非法输入，整体回退基线。
 */
export function clampMusicMoodSpec(spec: MusicMoodSpec): MusicMoodSpec {
  if (Number.isNaN(spec.flowScale) || Number.isNaN(spec.bloomBoost)) {
    return MUSIC_MOOD_BASELINE;
  }
  return {
    flowScale: Math.min(MUSIC_MOOD_MAX_FLOW_SCALE, Math.max(1, spec.flowScale)),
    bloomBoost: Math.min(MUSIC_MOOD_MAX_BLOOM_BOOST, Math.max(0, spec.bloomBoost)),
  };
}

/** musicMood 消费方最小契约：null 表示回基线（停止音乐模式）。 */
export interface MusicMoodTarget {
  setMusicMood(spec: MusicMoodSpec | null): void;
}

/**
 * 订阅 musicStore 的 playerState，把氛围映射推给 target：
 * 绑定即推送当前映射；状态变化推送新 mood；映射值不变不重复推送（去重）。
 * 返回 dispose：退订完整，之后状态变化不再推送。
 *
 * 与 bindSpaceMood（语音氛围）正交：调用方负责优先级合并
 *（音乐播放时 musicMood 覆盖 voiceMood；停止时回退 voiceMood）。
 */
export function bindMusicMood(store: MusicStore, target: MusicMoodTarget): () => void {
  let last: MusicMoodSpec | null = null;

  const readState = (): { state: PlayerStateName | null; hasCurrentSong: boolean } => {
    const ps = store.getState().playerState;
    return {
      state: ps?.state ?? null,
      hasCurrentSong: ps?.current_song != null,
    };
  };

  const push = (): void => {
    const { state, hasCurrentSong } = readState();
    const next = musicMoodForState(state, hasCurrentSong);
    if (last && last.flowScale === next.flowScale && last.bloomBoost === next.bloomBoost) {
      return; // 映射值未变：不重复推送
    }
    last = next;
    // 始终推送 spec（含基线）；target 自行决定基线时是否回退语音氛围
    target.setMusicMood(next);
  };

  const unsubscribe = store.subscribe(push);
  push(); // 初始推送当前状态映射
  return unsubscribe;
}
