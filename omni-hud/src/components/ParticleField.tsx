/**
 * 粒子背景层：canvas 全屏铺在内容层之下（z-index 0），pointer-events 关闭，
 * 绝不拦截指针、不遮挡文字与控件。渲染循环只依赖 ParticleEngine 的快照；
 * jsdom 等无 canvas 实现的环境下安静跳过，不影响测试与服务端渲染。
 */
import { useEffect, useRef, type MutableRefObject } from "react";

import { ParticleEngine } from "../particles/engine";

export interface ParticleFieldProps {
  /** 默认粒子数（永远会被钳制到 ≤ 300）。 */
  count?: number;
  /** 尊重 prefers-reduced-motion：开启后只画一帧静止画面。 */
  reducedMotion?: boolean;
  /** M4.4 主题换肤：自定义粒子调色板（≤ 5 色，引擎内硬校验）。 */
  palette?: readonly string[];
  /** M4.4 聚集交互：把引擎实例暴露给父组件以设置 / 清除吸引目标。 */
  engineRef?: MutableRefObject<ParticleEngine | null>;
}

export function ParticleField({
  count = 96,
  reducedMotion = false,
  palette,
  engineRef,
}: ParticleFieldProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return; // 测试环境无 canvas 实现，跳过渲染循环

    const resize = (): void => {
      canvas.width = canvas.clientWidth || 320;
      canvas.height = canvas.clientHeight || 480;
    };
    resize();

    const engine = new ParticleEngine({
      width: canvas.width,
      height: canvas.height,
      count,
      reducedMotion,
      palette,
    });
    if (engineRef) engineRef.current = engine;

    const draw = (): void => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (const p of engine.getParticles()) {
        ctx.globalAlpha = 0.5;
        ctx.fillStyle = p.color;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        ctx.fill();
      }
    };

    if (reducedMotion) {
      draw(); // 静止一帧，不启动循环
      return () => {
        if (engineRef) engineRef.current = null;
      };
    }

    let raf = 0;
    let last = performance.now();
    const frame = (now: number): void => {
      const dt = (now - last) / (1000 / 60);
      last = now;
      engine.step(dt);
      draw();
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    window.addEventListener("resize", resize);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      if (engineRef) engineRef.current = null;
    };
  }, [count, reducedMotion, palette, engineRef]);

  return (
    <canvas
      ref={canvasRef}
      className="particle-field"
      aria-hidden="true"
      style={{ pointerEvents: "none" }}
    />
  );
}
