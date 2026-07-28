/**
 * shelf/shelfStage 3D 卡片架场景装配（M20.1 / M20.5）。
 *
 * 设计决策 D20.1：ShelfStage 作为 FieldStage 子场景——共享 Space 的 renderer/camera/scene，
 * 在 scene 中挂载自己的 Group（卡片 Mesh 列表），由 Space 帧循环统一渲染。避免第二 WebGL 上下文
 * 与透明窗口 alpha 冲突；ShelfStage 自身只负责卡片 layout 编排 + 状态机 + 帧循环。
 *
 * 设计决策 D20.5：入场动画从 enterOffset.z（远方）→ 目标 z 的 spring 收敛；reducedMotion 直挂。
 * 悬停放大 / 选中居中由 step 推进（spring lerp，Film Atelier 风格克制有物理感）。
 * 卡片资源生命周期（geometry/material/texture）由 card3d.ts 拥有，shelfStage 编排调用。
 *
 * 不依赖 React / DOM 定时器；时序经 ShelfHost 注入，可独立单测。
 */
import { buildCardMesh, disposeCard, updateCardState, type CardRuntime } from "./card3d";
import type { CardData } from "./dataSource";
import {
  ARC_DEFAULT_SPAN_DEG,
  ARC_RADIUS_DEFAULT,
  computeArcLayout,
} from "./layout";
import type { ShelfGroup, ShelfHost } from "../createSpace";

/** 悬停放大系数（克制，不爆炸）。 */
export const HOVER_SCALE = 1.12;
/** 选中放大系数（卡片居中放大）。 */
export const SELECT_SCALE = 1.35;

export interface ShelfStageOptions {
  /** reducedMotion=true 时卡片直挂目标位置，无入场动画。 */
  readonly reducedMotion?: boolean;
  /** 弧半径（缺省 ARC_RADIUS_DEFAULT）。 */
  readonly radius?: number;
  /** 张角跨度（缺省 ARC_DEFAULT_SPAN_DEG）。 */
  readonly spanDeg?: number;
  /** 选中卡片回调（携带 CardData）。 */
  readonly onSelect?: (card: CardData) => void;
}

export interface ShelfStage {
  /** 替换卡片数据（旧卡片 dispose，新卡片按 layout 排布）。 */
  setCards(cards: readonly CardData[]): void;
  /** 设置悬停卡片 index（null = 取消悬停）。 */
  setHover(index: number | null): void;
  /** 选中卡片 index（触发 onSelect 回调 + 居中放大）。 */
  select(index: number): void;
  /** 推进一帧动画（now 毫秒）。 */
  step(now: number): void;
  /** 幂等 dispose：从 scene 移除 Group，释放所有资源。 */
  dispose(): void;
  /** 当前卡片数（只读）。 */
  readonly cardCount: number;
}

export function createShelfStage(
  host: ShelfHost,
  options: ShelfStageOptions = {},
): ShelfStage {
  const reducedMotion = options.reducedMotion ?? false;
  const radius = options.radius ?? ARC_RADIUS_DEFAULT;
  const spanDeg = options.spanDeg ?? ARC_DEFAULT_SPAN_DEG;
  const onSelect = options.onSelect;
  const three = host.three;

  // 创建 Group 并挂到 scene
  const group: ShelfGroup = new three.Group();
  host.scene.add(group);

  let disposed = false;
  let cards: readonly CardData[] = [];
  let runtimes: CardRuntime[] = [];
  let hoverIndex: number | null = null;
  let selectedIndex: number | null = null;
  let lastNow = 0;

  /** 释放全部卡片运行时。 */
  const disposeAllRuntimes = (): void => {
    for (const rt of runtimes) disposeCard(group, rt);
    runtimes = [];
  };

  return {
    get cardCount() {
      return runtimes.length;
    },

    setCards(nextCards: readonly CardData[]): void {
      if (disposed) return;
      disposeAllRuntimes();
      cards = nextCards;
      const layout = computeArcLayout(nextCards.length, {
        radius,
        spanDeg,
        reducedMotion,
      });
      runtimes = nextCards.map((card, i) =>
        buildCardMesh(three, group, layout[i]!, card, reducedMotion),
      );
    },

    setHover(index: number | null): void {
      if (disposed) return;
      if (index !== null && (index < 0 || index >= runtimes.length)) return;
      hoverIndex = index;
    },

    select(index: number): void {
      if (disposed) return;
      if (index < 0 || index >= runtimes.length) return;
      selectedIndex = index;
      if (onSelect && cards[index]) {
        onSelect(cards[index]!);
      }
    },

    step(now: number): void {
      if (disposed) return;
      const dt = lastNow === 0 ? 1 / 60 : Math.min(0.1, Math.max(0, (now - lastNow) / 1000));
      lastNow = now;
      for (let i = 0; i < runtimes.length; i++) {
        const rt = runtimes[i]!;
        updateCardState(rt, hoverIndex === i, selectedIndex === i, dt);
      }
    },

    dispose(): void {
      if (disposed) return;
      disposed = true;
      disposeAllRuntimes();
      host.scene.remove(group);
    },
  };
}

// 显式 re-export 类型供外部消费（避免循环引用陷阱）
export type { ShelfGroup, ShelfHost };
