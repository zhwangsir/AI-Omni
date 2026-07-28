/**
 * interactions 点击交互编排（M5.3）：把「内容层 pointerdown」翻译成
 * 3D 空间的一组建模反馈——shader 水波纹 + 吸引子脉冲 + 粒子聚集成形，
 * 成形保持 GATHER_HOLD_MS 后缓释回散（morph 过渡本身 ≥600ms smoothstep，
 * 禁瞬跳）。形状在三种之间轮换，避免重复聚集同一形状的呆板。
 *
 * 纯逻辑模块：不依赖 React / three / DOM 定时器，全部经依赖注入，可独立单测。
 */
import { SHAPE_KINDS, type ShapeKind } from "./shapes";

/** 聚集成形保持时长：成形过渡（750ms）完成后再停留一拍，随后缓释回散。 */
export const GATHER_HOLD_MS = 1400;

/** 形状轮换顺序：与 shapes.SHAPE_KINDS 单一事实源。 */
export const MORPH_CYCLE: readonly ShapeKind[] = SHAPE_KINDS;

export interface NdcPoint {
  readonly x: number;
  readonly y: number;
}

/**
 * 客户端像素坐标 → NDC([-1, 1])；y 轴屏幕向下 → 世界向上取反。
 * 视口尺寸非法（非正 / 非有限）或坐标非有限抛 RangeError。
 */
export function ndcFromClientPoint(
  clientX: number,
  clientY: number,
  width: number,
  height: number,
): NdcPoint {
  if (!Number.isFinite(width) || width <= 0 || !Number.isFinite(height) || height <= 0) {
    throw new RangeError(`非法视口尺寸: ${width}×${height}`);
  }
  if (!Number.isFinite(clientX) || !Number.isFinite(clientY)) {
    throw new RangeError(`非法指针坐标: (${clientX}, ${clientY})`);
  }
  return {
    x: (clientX / width) * 2 - 1,
    y: -((clientY / height) * 2 - 1) + 0, // +0 归一化：中心点不出现 -0
  };
}

/** 点击聚集所需的场景面（Space 子集，测试可注入纯 stub）。 */
export interface InteractionSpace {
  addRippleAt(ndcX: number, ndcY: number): boolean;
  pulseAttractor(strength?: number): void;
  morphTo(shape: ShapeKind): void;
  releaseShape(): void;
}

export interface ClickGatherDeps {
  /** 惰性取场景：懒加载完成前返回 null，点击静默跳过（DOM 波纹不受影响）。 */
  readonly getSpace: () => InteractionSpace | null;
  readonly setTimer: (callback: () => void, ms: number) => unknown;
  readonly clearTimer: (handle: unknown) => void;
  /** 成形保持时长，缺省 GATHER_HOLD_MS；非正值抛 RangeError。 */
  readonly holdMs?: number;
}

export interface ClickGather {
  /** 点击（NDC 坐标）：波纹 + 脉冲 + 轮换形状聚集，并重置缓释计时。 */
  click(ndcX: number, ndcY: number): void;
  /** 卸载清理：取消未触发的缓释（dispose 后不再触碰场景）。 */
  cancel(): void;
}

export function createClickGather(deps: ClickGatherDeps): ClickGather {
  const holdMs = deps.holdMs ?? GATHER_HOLD_MS;
  if (!Number.isFinite(holdMs) || holdMs <= 0) {
    throw new RangeError(`非法聚集保持时长: ${holdMs}`);
  }
  let cycleIndex = 0;
  let releaseTimer: unknown = null;

  const clearRelease = (): void => {
    if (releaseTimer !== null) {
      deps.clearTimer(releaseTimer);
      releaseTimer = null;
    }
  };

  return {
    click(ndcX: number, ndcY: number): void {
      const space = deps.getSpace();
      if (!space) return; // 场景未就绪 / 已 dispose：静默跳过
      space.addRippleAt(ndcX, ndcY);
      space.pulseAttractor();
      space.morphTo(MORPH_CYCLE[cycleIndex % MORPH_CYCLE.length]!);
      cycleIndex += 1;
      clearRelease(); // 连续点击：重新计时，形状不提前消散
      releaseTimer = deps.setTimer(() => {
        releaseTimer = null;
        deps.getSpace()?.releaseShape(); // 缓释时取最新场景（可能已换实例）
      }, holdMs);
    },

    cancel(): void {
      clearRelease();
    },
  };
}
