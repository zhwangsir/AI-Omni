/**
 * ShelfView 3D 卡片架视图组件（M20.6）：
 * 订阅 hudStore.fieldMode + libraryStore.playlists → 挂载/卸载 ShelfStage。
 *
 * 设计决策 D20.6：
 * - fieldMode="shelf" 时经 spaceRef.getShelfHost() 获取共享场景，创建 ShelfStage
 *   子场景（Group 加入 scene），由 Space 帧循环统一渲染。
 * - fieldMode="space" 或空间未就绪时静默跳过，不抛错。
 * - 右键 contextmenu 翻转 fieldMode（space ↔ shelf），实现「右键唤起 3D 卡片架」。
 * - libraryStore.playlists 变化时调 shelfStage.setCards() 重建卡片。
 * - 卸载/切回 space 时 dispose ShelfStage（幂等），从 scene 移除 Group。
 * - 粒子背景淡化：shelf 激活时 setMood 重置基线，避免语音态放大粒子干扰卡片可读性。
 *
 * 不直接渲染 Three.js 对象（ShelfStage 拥有 mesh 生命周期），本组件只编排 React 生命周期。
 */
import { useEffect, useRef, useState, type MutableRefObject } from "react";

import type { Space } from "../space/createSpace";
import { createShelfStage, type ShelfStage } from "../space/shelf/shelfStage";
import { playlistToCards } from "../space/shelf/dataSource";
import type { HudStore } from "../store/hudStore";
import type { LibraryStore } from "../store/libraryStore";

export interface ShelfViewProps {
  /** 3D 场景句柄（场景未就绪时为 null，挂载静默跳过）。 */
  readonly spaceRef: MutableRefObject<Space | null>;
  readonly hudStore: HudStore;
  readonly libraryStore: LibraryStore;
}

export function ShelfView({ spaceRef, hudStore, libraryStore }: ShelfViewProps) {
  const [cardCount, setCardCount] = useState(0);
  const shelfRef = useRef<ShelfStage | null>(null);
  // 帧循环句柄
  const frameHandleRef = useRef<number | null>(null);

  // 订阅 hudStore.fieldMode：shelf 模式下挂载 ShelfStage，space 模式下卸载。
  useEffect(() => {
    const onChange = (): void => {
      const fieldMode = hudStore.getState().fieldMode;
      const space = spaceRef.current;

      if (fieldMode !== "shelf") {
        // 切回 space：dispose ShelfStage
        if (shelfRef.current !== null) {
          shelfRef.current.dispose();
          shelfRef.current = null;
          setCardCount(0);
        }
        // 停止帧循环
        if (frameHandleRef.current !== null) {
          window.cancelAnimationFrame(frameHandleRef.current);
          frameHandleRef.current = null;
        }
        // 恢复粒子氛围（交还 FieldStage 控制）
        space?.setMood(null);
        return;
      }

      // shelf 模式：创建 ShelfStage（若尚未创建）
      if (shelfRef.current !== null) return; // 已创建，跳过
      const host = space?.getShelfHost() ?? null;
      if (host === null) return; // 空间未就绪静默跳过

      const reducedMotion = hudStore.getState().reducedMotion;
      shelfRef.current = createShelfStage(host, {
        reducedMotion,
        onSelect: (card) => {
          // 点击卡片回调（M20.3 控制）：当前仅日志，后续可接播放歌单
          if (import.meta.env.DEV) {
            console.log("[shelf] card selected:", card.id);
          }
        },
      });

      // 粒子背景淡化：重置 mood 到基线，避免语音态放大粒子干扰卡片可读性
      space?.setMood(null);

      // 注入初始卡片数据
      const playlists = libraryStore.getState().playlists;
      const cards = playlistToCards(playlists);
      shelfRef.current.setCards(cards);
      setCardCount(cards.length);

      // 启动帧循环（推进 ShelfStage 动画）
      const loop = (t: number): void => {
        if (shelfRef.current === null) return;
        shelfRef.current.step(t);
        frameHandleRef.current = window.requestAnimationFrame(loop);
      };
      frameHandleRef.current = window.requestAnimationFrame(loop);
    };

    onChange();
    const unsubscribe = hudStore.subscribe(onChange);
    return () => {
      unsubscribe();
      if (frameHandleRef.current !== null) {
        window.cancelAnimationFrame(frameHandleRef.current);
        frameHandleRef.current = null;
      }
      if (shelfRef.current !== null) {
        shelfRef.current.dispose();
        shelfRef.current = null;
      }
    };
  }, [hudStore, libraryStore, spaceRef]);

  // 订阅 libraryStore.playlists：数据变化时更新卡片
  useEffect(() => {
    const onChange = (): void => {
      const shelf = shelfRef.current;
      if (shelf === null) return; // shelf 未挂载，跳过
      const playlists = libraryStore.getState().playlists;
      const cards = playlistToCards(playlists);
      shelf.setCards(cards);
      setCardCount(cards.length);
    };
    const unsubscribe = libraryStore.subscribe(onChange);
    return () => {
      unsubscribe();
    };
  }, [libraryStore]);

  // 右键 contextmenu 翻转 fieldMode
  const handleContextMenu = (event: React.MouseEvent<HTMLDivElement>): void => {
    event.preventDefault();
    hudStore.toggleFieldMode();
  };

  return (
    <div
      className="shelf-view"
      data-testid="shelf-view"
      onContextMenu={handleContextMenu}
      aria-hidden="true"
      style={{ pointerEvents: "auto" }}
    >
      <span data-testid="shelf-card-count" aria-hidden="true" style={{ display: "none" }}>
        {cardCount}
      </span>
    </div>
  );
}
