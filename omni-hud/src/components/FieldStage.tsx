/**
 * FieldStage 四态场语义层（M7.3 实现）：
 * 订阅 statusStore.voice.state + hudStore.reducedMotion → resolveFieldState
 * 得 FieldParams → 经 Space.setField 注入 3D 粒子场 uniforms；
 * 进入聆听态（wake_listening / recording）一次性触发声井 addRipple；
 * speaking 时渲染底部细波形流线 canvas（reduced-motion 下不渲染）。
 *
 * 红线（CLAUDE.md §六 + spec m7 §四）：
 * - 状态未变化不重复推送 setField（去重，避免每帧抖动）；
 * - 进入聆听态边触发一次 addRipple，同态持续不重复；
 * - reduced-motion 下 resolveFieldState 已剥离动效附属，setField 仍推送 dim（静态视觉态）；
 * - 流线层 pointer-events: none + aria-hidden，绝不遮挡字幕与交互。
 */
import { useEffect, useRef, useState, type MutableRefObject } from "react";

import type { VoicePipelineState } from "../data/sources";
import { resolveFieldState, type FieldParams } from "../field/fieldState";
import type { Space } from "../space/createSpace";
import type { HudStore } from "../store/hudStore";
import type { StatusStore } from "../store/statusStore";

/** 流线 canvas 帧时长（ms）：克制，呼吸感而非高频抖动。 */
const FLOWLINE_FRAME_MS = 60;

export interface FieldStageProps {
  /** 3D 场景句柄（场景未就绪时为 null，挂载与状态切换静默跳过不抛错）。 */
  readonly spaceRef: MutableRefObject<Space | null>;
  readonly statusStore: StatusStore;
  readonly hudStore: HudStore;
}

export function FieldStage({ spaceRef, statusStore, hudStore }: FieldStageProps) {
  // 流线 canvas 仅在 speaking 且非 reduced-motion 时挂载（条件渲染）。
  const [flowlineOn, setFlowlineOn] = useState(false);

  // 上一轮推送的 voice.state 去重快照：状态未变化不重复推送。
  const lastVoiceStateRef = useRef<VoicePipelineState | null | undefined>(undefined);
  // 上一轮推送的 reducedMotion 去重快照。
  const lastReducedRef = useRef<boolean | undefined>(undefined);
  // 流线动画帧句柄（卸载 / 状态切换时取消，杜绝悬挂引用）。
  const flowlineHandleRef = useRef<number | null>(null);
  // 流线 canvas 引用。
  const flowlineCanvasRef = useRef<HTMLCanvasElement | null>(null);

  /**
   * 进入聆听态边一次性触发声井 addRipple（同态持续不重复）。
   * reduced-motion 下 resolveFieldState 已剥离 ripple，自然跳过。
   */
  const maybeTriggerRipple = (params: FieldParams): void => {
    if (params.ripple === null) return;
    const space = spaceRef.current;
    if (!space) return; // 场景未就绪静默跳过
    space.addRipple({
      x: params.ripple.origin.x,
      y: params.ripple.origin.y,
      z: params.ripple.origin.z,
      durationMs: params.ripple.durationMs,
    });
  };

  // 订阅 statusStore + hudStore：状态变化时推送场参数 + 触发 ripple / flowline 切换。
  useEffect(() => {
    // 挂载即推送一次（捕获初始状态，即便与上次同值也需首次推送）。
    // space 可能尚未就绪（ImmersiveSpace 懒加载 three.js 是异步的），
    // 因此设短间隔轮询直到 space 可用后推送首帧，随后停止轮询。
    let readyPoll: number | null = null;
    const pushInitial = (): void => {
      const space = spaceRef.current;
      if (!space) return;
      const initialVoiceState = statusStore.getState().voice.state;
      const initialReduced = hudStore.getState().reducedMotion;
      const initialParams = resolveFieldState(initialVoiceState, initialReduced);
      space.setField(initialParams);
      lastVoiceStateRef.current = initialVoiceState;
      lastReducedRef.current = initialReduced;
      maybeTriggerRipple(initialParams);
      setFlowlineOn(initialParams.flowline !== null);
      if (readyPoll !== null) {
        window.clearInterval(readyPoll);
        readyPoll = null;
      }
    };
    pushInitial();
    if (!spaceRef.current) {
      readyPoll = window.setInterval(pushInitial, 100);
    }

    const onChange = (): void => {
      const voiceState = statusStore.getState().voice.state;
      const reduced = hudStore.getState().reducedMotion;
      if (voiceState === lastVoiceStateRef.current && reduced === lastReducedRef.current) {
        return;
      }
      const space = spaceRef.current;
      if (!space) return;
      // 状态滞后：null（未识别/不可用）且上一个状态为活跃形态时，保持形态不释放，
      // 防止 Rust 侧发送未收录状态字符串或短暂 IPC 抖动导致粒子误消散。
      // 显式 "idle" 字符串正常切换到待机球体（不会释放为自由流）。
      let params = resolveFieldState(voiceState, reduced);
      const prev = lastVoiceStateRef.current;
      const lastHadActiveShape = prev !== null && prev !== undefined && prev !== "idle";
      if (voiceState === null && lastHadActiveShape) {
        return;
      }
      space.setField(params);
      if (voiceState !== lastVoiceStateRef.current) {
        maybeTriggerRipple(params);
      }
      lastVoiceStateRef.current = voiceState;
      lastReducedRef.current = reduced;
      setFlowlineOn(params.flowline !== null);
    };

    const unsubscribeStatus = statusStore.subscribe(onChange);
    const unsubscribeHud = hudStore.subscribe(onChange);
    return () => {
      if (readyPoll !== null) window.clearInterval(readyPoll);
      unsubscribeStatus();
      unsubscribeHud();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusStore, hudStore]);

  // 流线 canvas 动画：speaking 时绘制底部细波形，卸载 / 切换状态时取消动画帧。
  useEffect(() => {
    if (!flowlineOn) return;
    const canvas = flowlineCanvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // 读取流线振幅（从 statusStore + hudStore 重算一次，避免闭包快照陈旧）。
    const params = resolveFieldState(
      statusStore.getState().voice.state,
      hudStore.getState().reducedMotion,
    );
    const amplitude = params.flowline?.amplitude ?? 0.3;

    let phase = 0;
    const draw = (): void => {
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      // 底部细波形：振幅相对 canvas 半高，克制有界（呼吸感而非高频抖动）。
      ctx.strokeStyle = "rgba(201, 168, 106, 0.45)"; // 显影琥珀 accent（与主题色板第 1 槽对齐）
      ctx.lineWidth = 1;
      ctx.beginPath();
      const baseline = h - 8;
      const amp = h * amplitude;
      for (let x = 0; x <= w; x += 2) {
        // 多频正弦复合：克制不抖动，呼吸感（慢速）。
        const y =
          baseline -
          Math.sin(x * 0.012 + phase) * amp * 0.4 -
          Math.sin(x * 0.03 + phase * 1.3) * amp * 0.2;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      phase += 0.04;
      flowlineHandleRef.current = window.setTimeout(draw, FLOWLINE_FRAME_MS);
    };
    draw();

    return () => {
      if (flowlineHandleRef.current !== null) {
        window.clearTimeout(flowlineHandleRef.current);
        flowlineHandleRef.current = null;
      }
    };
  }, [flowlineOn, statusStore, hudStore]);

  return (
    <div className="field-stage" data-testid="field-stage" aria-hidden="true">
      {flowlineOn && (
        <canvas
          ref={flowlineCanvasRef}
          data-testid="field-flowline"
          aria-hidden="true"
          width={380}
          height={80}
          style={{ pointerEvents: "none" }}
        />
      )}
    </div>
  );
}
