/**
 * mood 语音状态 → 3D 场景氛围映射测试（M5.3 TDD 红）：
 * - 六态全映射：idle/wake_listening 平静基线；recording/transcribing/thinking 轻微活跃；
 *   speaking 明显活跃（流速 ≤×2.0、bloom 微升 ≤上限）；
 * - 未知状态 / null 回退基线；倍率常量硬钳制；
 * - bindSpaceMood 订阅接线：初始推送、变化推送、去重、dispose 完整。
 * 纯逻辑测试：fake StatusStore，不碰 Tauri / WebGL。
 */
import { describe, expect, it } from "vitest";

import type { VoicePipelineState } from "../data/sources";
import type { StatusStore } from "../store/statusStore";
import {
  bindSpaceMood,
  clampMoodSpec,
  moodForVoiceState,
  MOOD_BASELINE,
  MOOD_MAX_BLOOM_BOOST,
  MOOD_MAX_FLOW_SCALE,
  MOOD_TABLE,
  type MoodSpec,
} from "./mood";

const ALL_STATES: readonly VoicePipelineState[] = [
  "idle",
  "wake_listening",
  "follow_up_listening",
  "recording",
  "transcribing",
  "thinking",
  "tool_using",
  "speaking",
];

describe("mood 映射表（全态）", () => {
  it("所有状态全部有定义，且全部落在硬上限内", () => {
    for (const state of ALL_STATES) {
      const spec = MOOD_TABLE[state];
      expect(spec, state).toBeDefined();
      expect(spec.flowScale, state).toBeGreaterThanOrEqual(1);
      expect(spec.flowScale, state).toBeLessThanOrEqual(MOOD_MAX_FLOW_SCALE);
      expect(spec.bloomBoost, state).toBeGreaterThanOrEqual(0);
      expect(spec.bloomBoost, state).toBeLessThanOrEqual(MOOD_MAX_BLOOM_BOOST);
    }
  });

  it("idle 为平静漂移基线（×1.0、bloom 持平），wake_listening 微活跃（×1.2）", () => {
    expect(moodForVoiceState("idle")).toEqual(MOOD_BASELINE);
    const wake = moodForVoiceState("wake_listening");
    expect(wake.flowScale).toBe(1.2);
    expect(wake.bloomBoost).toBe(0.03);
  });

  it("recording / transcribing / thinking 中等活跃（×1.3~1.6、bloom 微升）", () => {
    for (const state of ["recording", "transcribing", "thinking"] as const) {
      const spec = moodForVoiceState(state);
      expect(spec.flowScale, state).toBeGreaterThan(1.3);
      expect(spec.flowScale, state).toBeLessThanOrEqual(1.6);
      expect(spec.bloomBoost, state).toBeGreaterThan(0);
      expect(spec.bloomBoost, state).toBeLessThanOrEqual(0.06);
    }
  });

  it("speaking 明显活跃（>1.3 且 ≤2.0，bloom 微升不超上限）", () => {
    const spec = moodForVoiceState("speaking");
    expect(spec.flowScale).toBeGreaterThan(1.3);
    expect(spec.flowScale).toBeLessThanOrEqual(MOOD_MAX_FLOW_SCALE);
    expect(spec.bloomBoost).toBeGreaterThan(0);
    expect(spec.bloomBoost).toBeLessThanOrEqual(MOOD_MAX_BLOOM_BOOST);
  });

  it("未知状态 / null / undefined / 空串回退基线", () => {
    expect(moodForVoiceState("dancing")).toEqual(MOOD_BASELINE);
    expect(moodForVoiceState(null)).toEqual(MOOD_BASELINE);
    expect(moodForVoiceState(undefined)).toEqual(MOOD_BASELINE);
    expect(moodForVoiceState("")).toEqual(MOOD_BASELINE);
  });
});

describe("clampMoodSpec 倍率硬钳制", () => {
  it("超上限值钳到上限", () => {
    expect(clampMoodSpec({ flowScale: 99, bloomBoost: 99 })).toEqual({
      flowScale: MOOD_MAX_FLOW_SCALE,
      bloomBoost: MOOD_MAX_BLOOM_BOOST,
    });
  });

  it("低于下限值钳到下限（流速不倒车、bloom 不变暗）", () => {
    expect(clampMoodSpec({ flowScale: 0.2, bloomBoost: -1 })).toEqual({
      flowScale: 1,
      bloomBoost: 0,
    });
  });

  it("NaN 回基线", () => {
    expect(clampMoodSpec({ flowScale: Number.NaN, bloomBoost: Number.NaN })).toEqual(
      MOOD_BASELINE,
    );
  });

  it("tool_using 高活跃（flowScale≈1.9、bloom≈0.12，接近 speaking 强度）", () => {
    const spec = moodForVoiceState("tool_using");
    expect(spec.flowScale).toBeGreaterThan(1.5);
    expect(spec.flowScale).toBeLessThan(2.0);
    expect(spec.bloomBoost).toBeGreaterThan(0.08);
    expect(spec.bloomBoost).toBeLessThanOrEqual(MOOD_MAX_BLOOM_BOOST);
  });

  it("MOOD_TABLE 所有条目恒满足钳制（模块级硬校验生效）", () => {
    for (const state of ALL_STATES) {
      expect(clampMoodSpec(MOOD_TABLE[state])).toEqual(MOOD_TABLE[state]);
    }
  });
});

/** 可控 fake StatusStore：仅实现 bindSpaceMood 消费的契约面。 */
function makeFakeStatusStore(initial: VoicePipelineState | null) {
  let state = initial;
  const listeners = new Set<() => void>();
  const store = {
    getState: () => ({ voice: { state } }),
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  } as unknown as StatusStore;
  return {
    store,
    listenerCount: () => listeners.size,
    setVoice(next: VoicePipelineState | null): void {
      state = next;
      for (const listener of [...listeners]) listener();
    },
  };
}

describe("bindSpaceMood 订阅接线", () => {
  it("初始即推送当前状态映射，变化时推送新 mood，状态不变不重复推送", () => {
    const { store, setVoice } = makeFakeStatusStore("idle");
    const seen: Array<MoodSpec | null> = [];
    const dispose = bindSpaceMood(store, { setMood: (mood) => seen.push(mood) });
    expect(seen).toEqual([MOOD_BASELINE]);
    setVoice("speaking");
    expect(seen.at(-1)).toEqual(MOOD_TABLE.speaking);
    setVoice("speaking"); // 状态未变：不重复推送
    expect(seen).toHaveLength(2);
    setVoice(null); // 源不可用：回退基线
    expect(seen.at(-1)).toEqual(MOOD_BASELINE);
    dispose();
  });

  it("dispose 完整：退订后状态变化不再推送，且无监听器残留", () => {
    const { store, setVoice, listenerCount } = makeFakeStatusStore(null);
    const seen: Array<MoodSpec | null> = [];
    const dispose = bindSpaceMood(store, { setMood: (mood) => seen.push(mood) });
    expect(listenerCount()).toBe(1);
    dispose();
    expect(listenerCount()).toBe(0);
    setVoice("recording");
    expect(seen).toHaveLength(1); // 仅初始推送
  });
});
