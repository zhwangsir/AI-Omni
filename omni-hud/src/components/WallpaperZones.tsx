/**
 * 壁纸模式交互分区（M22.3）：壁纸态下专属的可交互区域。
 *
 * 壁纸模式窗口沉到桌面图标下方（M22.1 D22.1），默认全穿透——桌面点击
 * 不被 HUD 拦截。本组件注册 3 个交互分区 + 1 个双击唤醒区，让壁纸态
 * 仍可操作 HUD：
 *
 * - **右下角控制条**（wallpaper-control-bar）：240×60 底部右下角，
 *   含退出壁纸模式按钮（Lucide React 图标，无 emoji）；
 * - **左边缘触发条**（wallpaper-left-edge）：8px 宽全高，悬停唤起歌单架；
 * - **右边缘触发条**（wallpaper-right-edge）：8px 宽全高，悬停唤起历史；
 * - **双击唤醒区**（wallpaper-wake-zone）：全屏透明层，双击触发 onWake
 *   回调（唤醒雪莉 → 壁纸层浮出到 screenSaver level，M22.5）。
 *
 * 分区经 useRegisteredZone 注册到 zoneRegistry，Rust 侧 zones 轮询在
 * 光标落入分区时关闭穿透（分区可交互），否则保持穿透（桌面点击透传）。
 *
 * 仅 wallpaperMode=true 时挂载；false 时完全卸载并注销全部分区。
 * 双击唤醒区虽覆盖全屏，但它只注册为交互分区（拦截点击），不遮挡视觉
 * （pointer-events: auto + background: transparent）。
 */
import { useRef } from "react";
import { Minimize2 } from "lucide-react";

import { useRegisteredZone } from "../store/useRegisteredZone";
import type { ZoneRegistry } from "../store/zoneRegistry";
import { getZoneRegistry } from "../store/zoneRegistryRuntime";

export interface WallpaperZonesProps {
  /** 是否处于壁纸模式（true = 挂载分区，false = 卸载全部分区）。 */
  wallpaperMode: boolean;
  /** 双击唤醒回调（触发壁纸层→screenSaver level 浮出，M22.5）。 */
  onWake: () => void;
  /** 退出壁纸模式回调（点击控制条退出按钮）。 */
  onExitWallpaper?: () => void;
  /** 注入 zoneRegistry（测试替换）；缺省走运行时单例。 */
  registry?: ZoneRegistry;
}

/** 壁纸模式交互分区 ID（与 zoneRegistry 注册一一对应）。 */
export const WALLPAPER_CONTROL_BAR_ZONE_ID = "wallpaper-control-bar";
export const WALLPAPER_LEFT_EDGE_ZONE_ID = "wallpaper-left-edge";
export const WALLPAPER_RIGHT_EDGE_ZONE_ID = "wallpaper-right-edge";
export const WALLPAPER_WAKE_ZONE_ID = "wallpaper-wake-zone";

export function WallpaperZones({
  wallpaperMode,
  onWake,
  onExitWallpaper,
  registry,
}: WallpaperZonesProps): React.ReactElement | null {
  const reg = registry ?? getZoneRegistry();
  const controlBarRef = useRef<HTMLDivElement | null>(null);
  const leftEdgeRef = useRef<HTMLDivElement | null>(null);
  const rightEdgeRef = useRef<HTMLDivElement | null>(null);
  const wakeZoneRef = useRef<HTMLDivElement | null>(null);

  // 注册 3 个交互分区（仅 wallpaperMode=true 时启用）
  useRegisteredZone(WALLPAPER_CONTROL_BAR_ZONE_ID, controlBarRef, {
    enabled: wallpaperMode,
    registry: reg,
  });
  useRegisteredZone(WALLPAPER_LEFT_EDGE_ZONE_ID, leftEdgeRef, {
    enabled: wallpaperMode,
    registry: reg,
  });
  useRegisteredZone(WALLPAPER_RIGHT_EDGE_ZONE_ID, rightEdgeRef, {
    enabled: wallpaperMode,
    registry: reg,
  });
  // 双击唤醒区也注册为交互分区（否则壁纸态全穿透，双击事件传不到前端）
  useRegisteredZone(WALLPAPER_WAKE_ZONE_ID, wakeZoneRef, {
    enabled: wallpaperMode,
    registry: reg,
  });

  if (!wallpaperMode) return null;

  return (
    <>
      {/* 双击唤醒区：全屏透明层，拦截点击用于双击检测；视觉不遮挡 */}
      <div
        ref={wakeZoneRef}
        data-testid="wallpaper-wake-zone"
        className="wallpaper-wake-zone"
        onDoubleClick={onWake}
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 1,
          background: "transparent",
        }}
      />

      {/* 左边缘触发条：8px 宽全高，悬停唤起歌单架 */}
      <div
        ref={leftEdgeRef}
        data-testid="wallpaper-left-edge"
        className="wallpaper-edge-zone wallpaper-edge-left"
        style={{
          position: "fixed",
          left: 0,
          top: 0,
          width: 8,
          height: "100vh",
          zIndex: 2,
          background: "transparent",
        }}
      />

      {/* 右边缘触发条：8px 宽全高，悬停唤起历史 */}
      <div
        ref={rightEdgeRef}
        data-testid="wallpaper-right-edge"
        className="wallpaper-edge-zone wallpaper-edge-right"
        style={{
          position: "fixed",
          right: 0,
          top: 0,
          width: 8,
          height: "100vh",
          zIndex: 2,
          background: "transparent",
        }}
      />

      {/* 右下角控制条：240×60，含退出壁纸模式按钮 */}
      <div
        ref={controlBarRef}
        data-testid="wallpaper-control-bar"
        className="wallpaper-control-bar"
        style={{
          position: "fixed",
          right: 24,
          bottom: 24,
          width: 240,
          height: 60,
          zIndex: 3,
          display: "flex",
          alignItems: "center",
          justifyContent: "flex-end",
          padding: "0 16px",
          borderRadius: 12,
          background: "rgba(12, 12, 14, 0.55)",
          backdropFilter: "blur(12px)",
          border: "1px solid rgba(255, 255, 255, 0.06)",
        }}
      >
        {onExitWallpaper ? (
          <button
            type="button"
            data-testid="wallpaper-exit-button"
            className="wallpaper-exit-button"
            onClick={onExitWallpaper}
            aria-label="退出壁纸模式"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 36,
              height: 36,
              borderRadius: 8,
              border: "none",
              background: "rgba(255, 255, 255, 0.08)",
              color: "rgba(255, 255, 255, 0.7)",
              cursor: "pointer",
              transition: "background 0.2s ease, color 0.2s ease",
            }}
          >
            <Minimize2 size={18} strokeWidth={1.5} />
          </button>
        ) : (
          <button
            type="button"
            data-testid="wallpaper-exit-button"
            className="wallpaper-exit-button"
            disabled
            aria-label="退出壁纸模式"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 36,
              height: 36,
              borderRadius: 8,
              border: "none",
              background: "rgba(255, 255, 255, 0.04)",
              color: "rgba(255, 255, 255, 0.3)",
              cursor: "default",
            }}
          >
            <Minimize2 size={18} strokeWidth={1.5} />
          </button>
        )}
      </div>
    </>
  );
}
