/**
 * ImmersiveSpace（M5.1）：3D 沉浸粒子空间挂载层，替代 M4 的 2D ParticleField。
 * - 懒加载：createSpace 与 three 运行时全部经动态 import 进入，首屏 bundle 不含 three；
 * - WebGL 失败降级：createSpace 抛错（context 创建失败等）→ 回退 M4 的 2D ParticleField；
 * - 宿主层 pointer-events 关闭、aria-hidden，绝不遮挡文字与交互控件；
 * - 主题 / reduced-motion / 窗口尺寸 / 指针位置经 props 与全局监听转发到场景。
 */
import { useEffect, useRef, useState, type MutableRefObject } from "react";

import type { ParticleEngine } from "../particles/engine";
import type { Space } from "../space/createSpace";
import type { DarkroomTheme } from "../theme/themes";
import { ParticleField } from "./ParticleField";

export interface ImmersiveSpaceProps {
  /** 当前 Film Atelier 主题（雾色 / 色板 / bloom 参数源）。 */
  readonly theme: DarkroomTheme;
  /** 尊重 prefers-reduced-motion：全场景冻结为单帧静态画面。 */
  readonly reducedMotion?: boolean;
  /** M22.4 壁纸模式：粒子降密≤2000 + bloom 减半 + 后处理简化。 */
  readonly wallpaperMode?: boolean;
  /** 降级回退 2D 引擎时透传的引擎引用（M4.4 聚集交互在降级路径保持可用）。 */
  readonly engineRef?: MutableRefObject<ParticleEngine | null>;
  /** M5.3：3D 场景句柄透出（addRippleAt / pulseAttractor / morphTo / setMood 交互接线用）。 */
  readonly spaceRef?: MutableRefObject<Space | null>;
}

/** 窗口 380×560 契约下的缺省视口（jsdom 等 clientWidth 为 0 的环境兜底）。 */
const FALLBACK_WIDTH = 380;
const FALLBACK_HEIGHT = 560;

export function ImmersiveSpace({
  theme,
  reducedMotion = false,
  wallpaperMode = false,
  engineRef,
  spaceRef: spaceHandleRef,
}: ImmersiveSpaceProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const spaceRef = useRef<Space | null>(null);
  // ref 镜像最新 props：懒加载完成后以最新值创建场景，不受闭包快照限制。
  const themeRef = useRef(theme);
  themeRef.current = theme;
  const reducedRef = useRef(reducedMotion);
  reducedRef.current = reducedMotion;
  const wallpaperRef = useRef(wallpaperMode);
  wallpaperRef.current = wallpaperMode;
  const [webglFailed, setWebglFailed] = useState(false);

  // 挂载：懒加载 space 模块与 three 运行时，创建场景；卸载：幂等 dispose。
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let cancelled = false;
    void (async () => {
      try {
        const [{ createSpace }, runtimeModule] = await Promise.all([
          import("../space/createSpace"),
          import("../space/runtime"),
        ]);
        const runtime = await Promise.resolve(runtimeModule.loadSpaceRuntime());
        if (cancelled) return;
        spaceRef.current = createSpace(
          {
            three: runtime.three,
            postfx: runtime.postfx,
            width: host.clientWidth || FALLBACK_WIDTH,
            height: host.clientHeight || FALLBACK_HEIGHT,
            devicePixelRatio: window.devicePixelRatio || 1,
            now: () => performance.now(),
            requestFrame: (callback) => window.requestAnimationFrame(callback),
            cancelFrame: (handle) => window.cancelAnimationFrame(handle),
          },
          host,
          { theme: themeRef.current, reducedMotion: reducedRef.current },
        );
        // M5.3：场景句柄透出给父组件（addRippleAt / pulseAttractor / morphTo / setMood 接线）
        if (spaceHandleRef) spaceHandleRef.current = spaceRef.current;
        // 调试钩子：开发模式下暴露到 window，方便控制台直接切换形态测试
        if (import.meta.env.DEV) {
          (window as unknown as Record<string, unknown>).__debug_space__ = spaceRef.current;
        }
      } catch {
        // WebGL 不可用 / 模块加载失败 → 回退 2D ParticleField（M4 引擎保留即为此）
        if (!cancelled) setWebglFailed(true);
      }
    })();
    return () => {
      cancelled = true;
      spaceRef.current?.dispose();
      spaceRef.current = null;
      if (spaceHandleRef) spaceHandleRef.current = null; // 透出句柄同步失效，杜绝悬挂引用
      if (import.meta.env.DEV) {
        delete (window as unknown as Record<string, unknown>).__debug_space__;
      }
    };
  }, []);

  // 主题 / reduced-motion / wallpaper-mode 变化转发（场景未就绪时空操作）。
  useEffect(() => {
    spaceRef.current?.applyTheme(theme);
  }, [theme]);
  useEffect(() => {
    spaceRef.current?.setReducedMotion(reducedMotion);
  }, [reducedMotion]);
  // M22.4：壁纸模式 → 粒子降密 + bloom 减半 + 后处理简化
  useEffect(() => {
    spaceRef.current?.setWallpaperMode(wallpaperMode);
  }, [wallpaperMode]);

  // 相机视差：window 级指针监听，归一化到 [-1, 1]（y 轴屏幕向下 → 世界向上取反）。
  useEffect(() => {
    const onPointerMove = (event: PointerEvent): void => {
      const nx = (event.clientX / window.innerWidth) * 2 - 1;
      const ny = (event.clientY / window.innerHeight) * 2 - 1;
      spaceRef.current?.setPointer(nx, -ny);
    };
    window.addEventListener("pointermove", onPointerMove, { passive: true });
    return () => window.removeEventListener("pointermove", onPointerMove);
  }, []);

  // 尺寸跟随：宿主 resize → 场景同步（jsdom 无 ResizeObserver 时跳过）。
  useEffect(() => {
    const host = hostRef.current;
    if (!host || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) spaceRef.current?.resize(width, height);
    });
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  // WebGL 失败降级：回退 M4 的 2D 粒子画布（保留聚集交互 engineRef 透传）。
  if (webglFailed) {
    return (
      <ParticleField reducedMotion={reducedMotion} palette={theme.particles} engineRef={engineRef} />
    );
  }

  return (
    <div
      ref={hostRef}
      className="immersive-space-host"
      data-testid="immersive-space"
      aria-hidden="true"
      style={{ pointerEvents: "none" }}
    />
  );
}
