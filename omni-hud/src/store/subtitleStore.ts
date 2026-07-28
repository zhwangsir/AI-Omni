/**
 * 字幕状态 store（M6.3 建，M7.2 从 avatar/ 迁至 store/ 保留——显影字幕逻辑复用，
 * M7.4 CaptionLayer 的唯一事实源；框架无关订阅模式，与 themeStore 同款）。
 *
 * 事件接线（语音 SSE hooks → 本 store）：
 *   speech.started → begin()       新 turn 清空并显示
 *   subtitle.chunk → appendChunk() 按增量语义累计（依据见下）
 *   speech.ended   → finish()      定稿，完整展示 finalShowMs → 渐隐 fadeOutMs → 隐藏
 *   打断 / 卸载    → hide()        立即隐藏并取消挂起计时器
 *
 * subtitle.chunk 的 text 语义 = **增量分片**（非累计全文），接收方自行累加：
 * - opentalking/pipeline/speak/synthesis_runner.py:2256-2260 与 2604-2610
 *   `_publish_subtitle_chunk`：每个 TTS 分片的字幕片段（sub_tag）逐段发布，
 *   is_final 恒 False；
 * - opentalking/apps/web/src/App.tsx:2126 官方前端 `subtitleAccRef.current += t`
 *   累加（:889 注释 "Cumulative assistant text for the current speech turn"）。
 * finality 由 speech.ended 给出；ended 携带完整 text 时以权威全文替换累计。
 *
 * 渐隐节奏（三阶段）：
 *   streaming → final_show → fading_out → hidden
 *   1. streaming：文字流式追加，逐字显影（blur→sharp）
 *   2. final_show：TTS 结束后完整文字清晰展示 finalShowMs（默认 1200ms）
 *   3. fading_out：CSS opacity 过渡 fadeOutMs（默认 400ms）到透明
 *   4. hidden：visible=false，DOM 卸载
 *
 * 时序行为集中在 store 可单测，UI 纯渲染；CSS 过渡由 store 的 fadingOut 标记驱动。
 * prefers-reduced-motion 下直接显隐（样式层处理，store 行为不变）。
 */

export interface SubtitleState {
  readonly text: string;
  /** true = 本轮播报已结束（speech.ended），字幕进入停留或渐隐阶段。 */
  readonly isFinal: boolean;
  /** true = 正在渐隐（opacity 从 1 过渡到 0）。 */
  readonly fadingOut: boolean;
  readonly visible: boolean;
}

export interface SubtitleStoreDeps {
  /** 定时器注入（测试可替换）；缺省全局 setTimeout/clearTimeout。 */
  readonly setTimer?: (callback: () => void, ms: number) => unknown;
  readonly clearTimer?: (handle: unknown) => void;
  /** final 文字停留时长（ms），缺省 SUBTITLE_FINAL_SHOW_MS。 */
  readonly finalShowMs?: number;
  /** 渐隐动画时长（ms），缺省 SUBTITLE_FADE_OUT_MS。 */
  readonly fadeOutMs?: number;
}

export interface SubtitleStore {
  getState: () => SubtitleState;
  subscribe: (listener: () => void) => () => void;
  /** speech.started：新 turn——清空旧文、取消挂起隐藏、置为可见。 */
  begin: () => void;
  /** subtitle.chunk：增量分片累计（text 语义见文件注释）。 */
  appendChunk: (chunk: string) => void;
  /** speech.ended：定稿；携带完整文本时以权威全文替换累计。展示→渐隐→隐藏。 */
  finish: (fullText?: string) => void;
  /** 打断 / 组件卸载：立即隐藏并取消挂起计时器（幂等）。 */
  hide: () => void;
}

/** final 文字停留时长：TTS 结束后给用户 1.2s 读完整句话。 */
export const SUBTITLE_FINAL_SHOW_MS = 1200;
/** 渐隐动画时长：400ms 平滑淡出。 */
export const SUBTITLE_FADE_OUT_MS = 400;

const INITIAL_STATE: SubtitleState = { text: "", isFinal: false, fadingOut: false, visible: false };

export function createSubtitleStore(deps?: SubtitleStoreDeps): SubtitleStore {
  const setTimer = deps?.setTimer ?? ((cb: () => void, ms: number) => setTimeout(cb, ms));
  const clearTimer =
    deps?.clearTimer ?? ((handle: unknown) => clearTimeout(handle as ReturnType<typeof setTimeout>));
  const finalShowMs = deps?.finalShowMs ?? SUBTITLE_FINAL_SHOW_MS;
  const fadeOutMs = deps?.fadeOutMs ?? SUBTITLE_FADE_OUT_MS;

  let state: SubtitleState = INITIAL_STATE;
  let fadeStartTimer: unknown = null;
  let hideTimer: unknown = null;
  const listeners = new Set<() => void>();

  const emit = (): void => {
    for (const listener of listeners) listener();
  };

  const cancelPendingTimers = (): void => {
    if (fadeStartTimer !== null) {
      clearTimer(fadeStartTimer);
      fadeStartTimer = null;
    }
    if (hideTimer !== null) {
      clearTimer(hideTimer);
      hideTimer = null;
    }
  };

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    begin() {
      cancelPendingTimers();
      state = { text: "", isFinal: false, fadingOut: false, visible: true };
      emit();
    },
    appendChunk(chunk) {
      state = { ...state, text: state.text + chunk, visible: true, fadingOut: false };
      emit();
    },
    finish(fullText) {
      cancelPendingTimers();
      state = {
        text: typeof fullText === "string" && fullText.length > 0 ? fullText : state.text,
        isFinal: true,
        fadingOut: false,
        visible: true,
      };
      emit();
      // 阶段 1：完整文字展示 finalShowMs 后开始渐隐
      fadeStartTimer = setTimer(() => {
        fadeStartTimer = null;
        state = { ...state, fadingOut: true };
        emit();
        // 阶段 2：渐隐 fadeOutMs 后隐藏（卸载 DOM）
        hideTimer = setTimer(() => {
          hideTimer = null;
          state = { ...state, visible: false };
          emit();
        }, fadeOutMs);
      }, finalShowMs);
    },
    hide() {
      cancelPendingTimers();
      if (!state.visible) return;
      state = { ...state, visible: false, fadingOut: false };
      emit();
    },
  };
}
