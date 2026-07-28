/**
 * 环境光（M4.4）：一团低透明度的强调色光晕，以低幅度 lerp 缓动
 * 柔和跟随鼠标（呼吸感，非生硬追踪）。reducedMotion 下静止在窗口中央。
 * pointer-events 关闭、aria-hidden，z-index 沉到内容之下。
 */
import { useEffect, useRef } from "react";

import { FOLLOW_LERP, lerpPoint } from "../motion/follow";

export interface AmbientLightProps {
  reducedMotion?: boolean;
}

export function AmbientLight({ reducedMotion = false }: AmbientLightProps) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (reducedMotion || typeof requestAnimationFrame !== "function") {
      // 降级：静止在宿主中央，不开跟随循环。
      el.style.left = "50%";
      el.style.top = "50%";
      return;
    }

    const host = el.parentElement;
    const rect = host?.getBoundingClientRect();
    const current = { x: (rect?.width ?? 0) / 2, y: (rect?.height ?? 0) / 2 };
    const target = { ...current };

    const onPointerMove = (event: PointerEvent): void => {
      const box = host?.getBoundingClientRect();
      target.x = event.clientX - (box?.left ?? 0);
      target.y = event.clientY - (box?.top ?? 0);
    };

    let raf = 0;
    const frame = (): void => {
      const next = lerpPoint(current, target, FOLLOW_LERP);
      current.x = next.x;
      current.y = next.y;
      el.style.transform = `translate3d(${current.x}px, ${current.y}px, 0)`;
      raf = requestAnimationFrame(frame);
    };

    window.addEventListener("pointermove", onPointerMove);
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("pointermove", onPointerMove);
    };
  }, [reducedMotion]);

  return (
    <div
      ref={ref}
      className="ambient-light"
      data-testid="ambient-light"
      aria-hidden="true"
      style={{ pointerEvents: "none" }}
    />
  );
}
