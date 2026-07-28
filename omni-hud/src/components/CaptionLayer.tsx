/**
 * CaptionLayer（M7.4）：mono 状态标 + 显影字幕 + 打断 glyph。
 *
 * 三层内容：
 * - 状态标（左上 mono 小字，胶片片头标风格）：voice.state 变化时显影，2.5s 渐隐；
 * - 字幕（下三分之一居中）：复用 subtitleStore 显影语义，由 voice-status 通道
 *   驱动——speaking + 新 replySeq → begin + appendChunk(完整回复)；离开 speaking
 *   → finish（完整展示 1.2s → 400ms 渐隐）；打断 → hide（立即收起）；
 * - 打断 glyph（speaking 时字幕区右端）：hover 显 square 图标，点击 →
 *   interruptSpeaking()（Rust voice_interrupt → 控制文件）+ subtitleStore.hide()。
 *
 * 分区：speaking + 字幕可见 + 非睡眠 → 字幕区注册为 active zone（hover 可触发 glyph）；
 * 睡眠态不注册、不显字幕（场近零，仅声井可交互）。
 *
 * 图标经 Icon.tsx（square）——禁止 emoji。Film Atelier：纯排版无框无底条，
 * 柔和文字阴影保可读，克制暗房风。
 */
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { interruptSpeaking } from "../lib/voice";
import { useRegisteredZone } from "../store/useRegisteredZone";
import { getZoneRegistry } from "../store/zoneRegistryRuntime";
import type { ZoneRegistry } from "../store/zoneRegistry";
import type { HudStore } from "../store/hudStore";
import type { StatusStore } from "../store/statusStore";
import type { SubtitleStore } from "../store/subtitleStore";
import { Icon } from "./ui/Icon";

export interface CaptionLayerProps {
  statusStore: StatusStore;
  hudStore: HudStore;
  subtitleStore: SubtitleStore;
  /** 注入 registry（测试替换）；缺省走运行时单例。 */
  registry?: ZoneRegistry;
}

const CAPTION_SUBTITLE_ZONE_ID = "caption-subtitle";
const STATUS_MARK_LINGER_MS = 2500;

export function CaptionLayer({
  statusStore,
  hudStore,
  subtitleStore,
  registry,
}: CaptionLayerProps): JSX.Element {
  const reg = registry ?? getZoneRegistry();
  const subtitleRef = useRef<HTMLDivElement | null>(null);

  const voice = useSyncExternalStore(statusStore.subscribe, statusStore.getState).voice;
  const hudState = useSyncExternalStore(hudStore.subscribe, hudStore.getState);
  const subtitleState = useSyncExternalStore(subtitleStore.subscribe, subtitleStore.getState);
  const sleeping = hudState.sleeping;

  const [markVisible, setMarkVisible] = useState(false);
  const [hovered, setHovered] = useState(false);

  const prevStateRef = useRef<string | null>(voice.state);
  const lastDrivenSeqRef = useRef<number | null>(null);
  const interruptedRef = useRef(false);
  const markTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isSpeaking = voice.state === "speaking";
  const subtitleActive = isSpeaking && subtitleState.visible && !sleeping;

  // 字幕分区：speaking + 可见 + 非睡眠时注册（hover 可触发打断 glyph）。
  useRegisteredZone(CAPTION_SUBTITLE_ZONE_ID, subtitleRef, {
    enabled: subtitleActive,
    registry: reg,
  });

  // 状态标 + 字幕联动：voice.state 变化驱动。
  useEffect(() => {
    const currState = voice.state;
    const prevState = prevStateRef.current;

    // 状态标：state 变化时显影 + 重置 2.5s 计时器。
    if (currState !== prevState) {
      setMarkVisible(true);
      if (markTimerRef.current !== null) {
        clearTimeout(markTimerRef.current);
      }
      markTimerRef.current = setTimeout(() => {
        markTimerRef.current = null;
        setMarkVisible(false);
      }, STATUS_MARK_LINGER_MS);
    }

    // 字幕联动：speaking + 新 replySeq → begin + appendChunk（完整回复）。
    if (currState === "speaking") {
      const seq = voice.replySeq;
      if (seq !== lastDrivenSeqRef.current && voice.reply) {
        subtitleStore.begin();
        subtitleStore.appendChunk(voice.reply);
        lastDrivenSeqRef.current = seq;
        interruptedRef.current = false;
      }
    } else if (prevState === "speaking") {
      // 离开 speaking：非打断 → finish（自然展示→渐隐）；打断 → hide 已抢先，跳过。
      if (!interruptedRef.current) {
        subtitleStore.finish();
      }
      interruptedRef.current = false;
    }

    prevStateRef.current = currState;
  }, [voice.state, voice.reply, voice.replySeq, subtitleStore]);

  // 卸载清理状态标计时器。
  useEffect(() => {
    return () => {
      if (markTimerRef.current !== null) {
        clearTimeout(markTimerRef.current);
        markTimerRef.current = null;
      }
    };
  }, []);

  const handleInterruptClick = (): void => {
    interruptedRef.current = true;
    void interruptSpeaking();
    subtitleStore.hide();
  };

  const voiceStateLabel = voice.state ?? "离线";

  // 字幕 CSS 类：
  // - visible && !fadingOut → --visible（opacity:1，文字锐利）
  // - visible && fadingOut → 无 visible 类（opacity:0，CSS 过渡渐隐）
  // - !visible → DOM 卸载
  const subtitleVisible = subtitleState.visible && !subtitleState.fadingOut;

  return (
    <div
      className="caption-layer"
      data-testid="caption-layer"
      data-sleeping={sleeping ? "true" : "false"}
    >
      <div
        className="caption-status-mark"
        data-testid="caption-status-mark"
        data-visible={markVisible ? "true" : "false"}
      >
        {voiceStateLabel}
      </div>
      {subtitleState.visible && !sleeping && (
        <div
          ref={subtitleRef}
          className={`caption-subtitle${subtitleVisible ? " caption-subtitle--visible" : ""}`}
          data-testid="caption-subtitle"
          data-revealed={subtitleVisible ? "true" : "false"}
          data-fading={subtitleState.fadingOut ? "true" : "false"}
          onPointerEnter={() => setHovered(true)}
          onPointerLeave={() => setHovered(false)}
        >
          <span className="caption-subtitle-text">{subtitleState.text}</span>
          {subtitleActive && hovered && (
            <button
              type="button"
              className="caption-interrupt"
              data-testid="caption-interrupt"
              onClick={handleInterruptClick}
              aria-label="打断"
            >
              <Icon name="square" label="打断" />
            </button>
          )}
        </div>
      )}
    </div>
  );
}
