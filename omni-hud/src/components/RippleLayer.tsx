/**
 * 水波纹层（M4.4）：点击内容区时从点击中心向外扩散多层同心圆，
 * 慢速大范围渐隐（参数硬约束见 src/ripple/ripple.ts）。
 * 波纹层 absolute 铺满、pointer-events 关闭、aria-hidden——
 * 绝不拦截指针、不遮挡文字交互。reducedMotion 下完全不产生波纹。
 */
import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";

import {
  RIPPLE_DURATION_MS,
  RIPPLE_LAYER_STAGGER_MS,
  RIPPLE_LAYERS,
  RIPPLE_MAX_RADIUS,
  rippleLayerDelays,
} from "../ripple/ripple";

export interface Ripple {
  readonly id: number;
  readonly x: number;
  readonly y: number;
}

export interface UseRipplesResult {
  readonly ripples: readonly Ripple[];
  /** 在宿主坐标系内生成一波波纹；reducedMotion 或非法坐标时忽略。 */
  readonly spawnRipple: (x: number, y: number) => void;
}

/** 波纹生成 / 到期清理的状态钩子。 */
export function useRipples(reducedMotion: boolean): UseRipplesResult {
  const [ripples, setRipples] = useState<readonly Ripple[]>([]);
  const nextId = useRef(0);
  const timers = useRef<number[]>([]);

  // 卸载时清掉全部待清理定时器，避免组件销毁后 setState。
  useEffect(
    () => () => {
      for (const timer of timers.current) clearTimeout(timer);
      timers.current = [];
    },
    [],
  );

  const spawnRipple = useCallback(
    (x: number, y: number) => {
      if (reducedMotion) return;
      if (!Number.isFinite(x) || !Number.isFinite(y)) return;
      nextId.current += 1;
      const id = nextId.current;
      setRipples((prev) => [...prev, { id, x, y }]);
      // 末层错峰起步后动画总长 = 主时长 + 错峰 × (层数-1)，加 100ms 余量再清除。
      const ttl = RIPPLE_DURATION_MS + RIPPLE_LAYER_STAGGER_MS * (RIPPLE_LAYERS - 1) + 100;
      const timer = window.setTimeout(() => {
        setRipples((prev) => prev.filter((r) => r.id !== id));
      }, ttl);
      timers.current.push(timer);
    },
    [reducedMotion],
  );

  return { ripples, spawnRipple };
}

export interface RippleLayerProps {
  readonly ripples: readonly Ripple[];
}

export function RippleLayer({ ripples }: RippleLayerProps) {
  const delays = rippleLayerDelays();
  const layerStyle = { "--omni-ripple-duration": `${RIPPLE_DURATION_MS}ms` } as CSSProperties;
  return (
    <div
      className="ripple-layer"
      data-testid="ripple-layer"
      aria-hidden="true"
      style={{ ...layerStyle, pointerEvents: "none" }}
    >
      {ripples.map((ripple) => (
        <span key={ripple.id} data-ripple className="ripple">
          {delays.map((delay, layer) => (
            <span
              key={layer}
              data-ripple-ring
              className="ripple__ring"
              style={{
                left: ripple.x,
                top: ripple.y,
                width: RIPPLE_MAX_RADIUS * 2,
                height: RIPPLE_MAX_RADIUS * 2,
                animationDelay: `${delay / 1000}s`,
              }}
            />
          ))}
        </span>
      ))}
    </div>
  );
}
