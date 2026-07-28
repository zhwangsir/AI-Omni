/**
 * mood 语音状态 → 3D 场景氛围映射（M5.3）：
 * statusStore voice.state → 流场流速倍率（flowScale）与 bloom 微升（bloomBoost）。
 * 六态分档：idle / wake_listening 平静基线；recording / transcribing / thinking
 * 轻微活跃（流速 ×1.3，bloom 持平）；speaking 明显活跃（流速 ×1.8，bloom 微升）。
 * 倍率硬钳制（流速 ≤×2.0、bloom 增量 ≤0.15）——活跃但不失控，克制红线。
 * 与 speakingDriver（数字人口型）共存：同一状态源，各管各的表现层。
 * 纯逻辑模块：不依赖 three / WebGL，fake StatusStore 可独立单测。
 */
import type { VoicePipelineState } from "../data/sources";
import type { StatusStore } from "../store/statusStore";

/** 场景氛围规格：流场流速倍率 + bloom 强度增量。 */
export interface MoodSpec {
  /** 流场流速倍率 [1, MOOD_MAX_FLOW_SCALE]：1 = 平静基线。 */
  readonly flowScale: number;
  /** bloom 强度增量 [0, MOOD_MAX_BLOOM_BOOST]：0 = 持平基线。 */
  readonly bloomBoost: number;
}

/** 平静基线：漂移 ×1.0，bloom 不加码。 */
export const MOOD_BASELINE: MoodSpec = { flowScale: 1, bloomBoost: 0 };
/** 流速倍率硬上限（克制：再活跃也不超过 ×2.0）。 */
export const MOOD_MAX_FLOW_SCALE = 2;
/** bloom 增量硬上限（微升感知，绝不全屏泛光）。 */
export const MOOD_MAX_BLOOM_BOOST = 0.15;

/**
 * 六态全映射（条目由单测逐态钉死、消费点再经 clampMoodSpec 二次钳制，恒在区间内）。
 * 中间态（录音 / 转写 / 思考）共用一档轻微活跃：有生命感但不喧宾夺主。
 * speaking 态为最强活跃：流速 ×2.0（上限）、bloom +0.15（上限），配合 CSS 脉动。
 */
export const MOOD_TABLE: Readonly<Record<VoicePipelineState, MoodSpec>> = {
  idle: MOOD_BASELINE,
  wake_listening: { flowScale: 1.2, bloomBoost: 0.03 },
  follow_up_listening: { flowScale: 1.1, bloomBoost: 0.02 },
  recording: { flowScale: 1.5, bloomBoost: 0.05 },
  transcribing: { flowScale: 1.6, bloomBoost: 0.06 },
  thinking: { flowScale: 1.5, bloomBoost: 0.05 },
  tool_using: { flowScale: 1.9, bloomBoost: 0.12 },
  speaking: { flowScale: 2.0, bloomBoost: 0.15 },
};

/** 语音状态 → 氛围规格；未知状态 / null / undefined / 空串回退平静基线。 */
export function moodForVoiceState(state: string | null | undefined): MoodSpec {
  if (state && state in MOOD_TABLE) {
    return MOOD_TABLE[state as VoicePipelineState];
  }
  return MOOD_BASELINE;
}

/**
 * 倍率硬钳制：flowScale ∈ [1, MAX]（不倒车）、bloomBoost ∈ [0, MAX]（不变暗）；
 * 任一分量 NaN 视为非法输入，整体回退基线。
 */
export function clampMoodSpec(spec: MoodSpec): MoodSpec {
  if (Number.isNaN(spec.flowScale) || Number.isNaN(spec.bloomBoost)) {
    return MOOD_BASELINE;
  }
  return {
    flowScale: Math.min(MOOD_MAX_FLOW_SCALE, Math.max(1, spec.flowScale)),
    bloomBoost: Math.min(MOOD_MAX_BLOOM_BOOST, Math.max(0, spec.bloomBoost)),
  };
}

/** mood 消费方最小契约（Space.setMood 的超集：null 表示回基线）。 */
export interface MoodTarget {
  setMood(spec: MoodSpec | null): void;
}

/**
 * 订阅 statusStore 的 voice.state，把氛围映射推给 target：
 * 绑定即推送当前映射；状态变化推送新 mood；映射值不变不重复推送（去重）。
 * 返回 dispose：退订完整，之后状态变化不再推送。
 */
export function bindSpaceMood(store: StatusStore, target: MoodTarget): () => void {
  let last: MoodSpec | null = null;

  const push = (): void => {
    const next = moodForVoiceState(store.getState().voice.state);
    if (last && last.flowScale === next.flowScale && last.bloomBoost === next.bloomBoost) {
      return; // 映射值未变：不重复推送
    }
    last = next;
    target.setMood(next);
  };

  const unsubscribe = store.subscribe(push);
  push(); // 初始推送当前状态映射
  return unsubscribe;
}
