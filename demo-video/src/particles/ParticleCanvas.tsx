import React, { useLayoutEffect, useMemo, useRef } from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";

import { computeParticles, drawParticles, SpriteCache } from "./engine";
import type { SafeZone } from "./engine";
import { BEHAVIORS } from "./behaviors";
import type { BehaviorName } from "./behaviors";

/**
 * 粒子画布（M46）：把行为函数渲染到 Canvas 2D。
 *
 * 帧驱动：useCurrentFrame() → 纯函数 computeParticles → useLayoutEffect
 * 内同步绘制（绘制在 paint 前完成，Remotion 逐帧截图可靠）。
 * 全部状态 = f(frame)，并行/乱序 seek 安全。
 */

interface ParticleCanvasProps {
  behavior: BehaviorName;
  from: number; // 场景起始帧（全局时间轴）
  duration: number; // 场景帧数（progress 归一基准）
  count?: number;
  seed?: number;
  focal?: { x: number; y: number }; // 归一焦点 [0,1]
  safeZones?: SafeZone[];
  connections?: boolean; // 远/中层连线（星图感）
  opacity?: number; // 整体强度
}

/** 模块级精灵缓存：跨帧复用，同源确定性 */
let spriteCache: SpriteCache | null = null;
const getSprites = (): SpriteCache => {
  if (!spriteCache) spriteCache = new SpriteCache(64);
  return spriteCache;
};

export const ParticleCanvas: React.FC<ParticleCanvasProps> = ({
  behavior,
  from,
  duration,
  count = 240,
  seed = 42,
  focal = { x: 0.62, y: 0.42 },
  safeZones = [],
  connections = false,
  opacity = 1,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const local = frame - from;
  const active = local >= 0 && local < duration;
  const progress = duration > 0 ? Math.min(1, Math.max(0, local / duration)) : 0;

  const env = useMemo(
    () => ({
      frame: Math.max(0, local),
      fps,
      width,
      height,
      cx: focal.x * width,
      cy: focal.y * height,
      progress,
      safeZones,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [local, fps, width, height, behavior],
  );

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !active) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const states = computeParticles(BEHAVIORS[behavior], env, count, seed);
    drawParticles(ctx, states, getSprites(), {
      width,
      height,
      connections,
      connectionOpacity: 0.16,
    });
  }, [active, env, behavior, count, seed, connections, width, height]);

  if (!active) return null;
  return (
    <AbsoluteFill style={{ opacity }}>
      <canvas
        ref={canvasRef}
        width={width}
        height={height}
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
      />
    </AbsoluteFill>
  );
};
