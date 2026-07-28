/**
 * WellZone（M7.4）：声井 + 召唤控制环。
 *
 * 底部居中椭圆区（约 320×180，下缘贴屏）。鼠标滑入（经 M7.1 分区可交互）→
 * 控制环显影：语音状态点 / 主题点 / 睡眠切换 / 井心 caption 卡入口；
 * 滑出 → 环收起恢复穿透。休眠态收窄为仅唤醒入口，但分区始终保留
 * （spec §二：休眠=场近零+仅声井可交互，窗口不隐藏防失锚）。
 *
 * 分区协调：well 分区恒注册（休眠也留）；caption 卡展开时增注 well-caption 分区。
 * 经 zoneRegistry 统一合并下发，不直接 setInteractiveZones 互相覆盖。
 *
 * 图标经 Icon.tsx（Moon/Sun）——禁止 emoji（CLAUDE.md §五）。
 * Film Atelier：克制暗房风，控制环以发丝描边 + accent 点缀，无高饱和爆闪。
 */
import { useEffect, useRef, useState, useSyncExternalStore, type MutableRefObject } from "react";

import type { Space } from "../space/createSpace";
import { THEMES } from "../theme/themes";
import { Icon } from "./ui/Icon";
import { useRegisteredZone } from "../store/useRegisteredZone";
import { getZoneRegistry } from "../store/zoneRegistryRuntime";
import type { ZoneRegistry } from "../store/zoneRegistry";
import type { HudStore } from "../store/hudStore";
import type { StatusStore } from "../store/statusStore";
import type { ThemeStore } from "../theme/themeStore";

export interface WellZoneProps {
  statusStore: StatusStore;
  hudStore: HudStore;
  themeStore: ThemeStore;
  /**
   * 3D 场景句柄（与 FieldStage 同源，App.tsx 透传）；
   * hover 时触发粒子聚集成控制环（spec §五），离开散开恢复自由流场。
   */
  spaceRef: MutableRefObject<Space | null>;
  /** 注入 registry（测试替换）；缺省走运行时单例。 */
  registry?: ZoneRegistry;
}

const WELL_ZONE_ID = "well";
const WELL_CAPTION_ZONE_ID = "well-caption";

export function WellZone({
  statusStore,
  hudStore,
  themeStore,
  spaceRef,
  registry,
}: WellZoneProps): JSX.Element {
  const reg = registry ?? getZoneRegistry();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const captionCardRef = useRef<HTMLDivElement | null>(null);

  const [hovered, setHovered] = useState(false);
  const [cardOpen, setCardOpen] = useState(false);

  // well 分区恒注册（休眠也留——唯一可交互区）。
  useRegisteredZone(WELL_ZONE_ID, containerRef, { registry: reg });
  // caption 卡展开时增注分区（卡区可交互）。
  useRegisteredZone(WELL_CAPTION_ZONE_ID, captionCardRef, {
    enabled: cardOpen,
    registry: reg,
  });

  const voice = useSyncExternalStore(statusStore.subscribe, statusStore.getState).voice;
  const hudState = useSyncExternalStore(hudStore.subscribe, hudStore.getState);
  const themeState = useSyncExternalStore(themeStore.subscribe, themeStore.getState);
  const sleeping = hudState.sleeping;
  const reducedMotion = hudState.reducedMotion;

  // 睡眠态自动收起 caption 卡（避免悬挂的卡分区）。
  useEffect(() => {
    if (sleeping && cardOpen) setCardOpen(false);
  }, [sleeping, cardOpen]);

  // hover 进入 → 粒子聚集成控制环（ring 形状，复用既有水平环）；
  // hover 离开 → 散开恢复自由流场。reduced-motion 下空操作（spec §五 + CLAUDE.md §六）。
  // spaceRef.current 为 null（场景未就绪）时 morphTo / releaseShape 静默跳过不抛错。
  const handlePointerEnter = (): void => {
    setHovered(true);
    if (!reducedMotion) {
      spaceRef.current?.morphTo("ring");
    }
  };
  const handlePointerLeave = (): void => {
    setHovered(false);
    if (!reducedMotion) {
      spaceRef.current?.releaseShape();
    }
  };

  const handleSleepToggle = (): void => {
    hudStore.toggleSleeping();
  };

  const handleCenterClick = (): void => {
    if (sleeping) return;
    setCardOpen((open) => !open);
  };

  const handleThemeClick = (id: string): void => {
    themeStore.setTheme(id);
  };

  const showRing = hovered;
  const voiceStateLabel = voice.state ?? "离线";

  return (
    <div
      ref={containerRef}
      className="well-zone"
      data-testid="well-zone"
      data-sleeping={sleeping ? "true" : "false"}
      onPointerEnter={handlePointerEnter}
      onPointerLeave={handlePointerLeave}
    >
      {showRing && (
        <div className="well-ring" data-testid="well-ring" aria-hidden="true">
          {sleeping ? (
            // 睡眠态：仅唤醒入口
            <button
              type="button"
              className="well-sleep-toggle"
              data-testid="well-sleep-toggle"
              data-sleeping="true"
              onClick={handleSleepToggle}
              aria-label="唤醒"
            >
              <Icon name="sun" label="唤醒" />
            </button>
          ) : (
            <>
              <span
                className="well-status-dot"
                data-testid="well-status-dot"
                data-state={voiceStateLabel}
                data-available={voice.available ? "true" : "false"}
              />
              {THEMES.map((theme) => (
                <button
                  type="button"
                  key={theme.id}
                  className="well-theme-dot"
                  data-testid="well-theme-dot"
                  data-active={themeState.themeId === theme.id ? "true" : "false"}
                  data-theme-id={theme.id}
                  onClick={() => handleThemeClick(theme.id)}
                  aria-label={`切换至${theme.label}`}
                  style={{ background: theme.tokens.accent }}
                />
              ))}
              <button
                type="button"
                className="well-sleep-toggle"
                data-testid="well-sleep-toggle"
                data-sleeping="false"
                onClick={handleSleepToggle}
                aria-label="睡眠"
              >
                <Icon name="moon" label="睡眠" />
              </button>
              <button
                type="button"
                className="well-center"
                data-testid="well-center"
                onClick={handleCenterClick}
                aria-label="语音状态"
              />
            </>
          )}
        </div>
      )}
      {cardOpen && !sleeping && (
        <div
          ref={captionCardRef}
          className="well-caption-card"
          data-testid="well-caption-card"
        >
          <span className="well-caption-state">{voiceStateLabel}</span>
          <span className="well-caption-reply">
            {voice.reply ?? "（暂无回复）"}
          </span>
        </div>
      )}
    </div>
  );
}
