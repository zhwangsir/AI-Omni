/**
 * ShelfView Page Object（M20 3D 歌单架 E2E）。
 *
 * 封装对 ShelfView 组件（src/components/ShelfView.tsx）的查询与交互：
 * - data-testid="shelf-view"：根节点（Full 模式下恒挂载，aria-hidden=true）
 * - data-testid="shelf-card-count"：卡片数量（display:none，经 evaluate 读 textContent）
 *
 * 交互：
 * - rightClick()：dispatch contextmenu 事件触发 hudStore.toggleFieldMode（space↔shelf）
 *
 * fieldMode 与 cardCount 的关系（ShelfView.tsx 实现）：
 * - fieldMode="space"（默认）：ShelfStage 未创建 / 已 dispose → cardCount=0
 * - fieldMode="shelf" + Space 就绪：ShelfStage 创建 + setCards(playlists) → cardCount=playlists.length
 * - fieldMode="shelf" + Space 未就绪：ShelfStage 未创建（host=null 静默跳过）→ cardCount=0
 *
 * 故 cardCount 是验证 fieldMode 切换的可靠指标（需预填充 playlists 且 Space 已就绪）。
 *
 * Space 就绪判定：ImmersiveSpace.tsx:81 在 DEV 模式暴露 window.__debug_space__，
 * 标志 spaceRef.current 已赋值（createSpace 完成）。ShelfView 的 shelf 分支依赖
 * spaceRef.current.getShelfHost() 获取 ShelfHost，未就绪时静默跳过不创建 ShelfStage。
 */
import { expect, type Page, type Locator } from "@playwright/test";

import { GLOBAL_KEYS } from "../support/env";
import type { FieldMode } from "../../src/store/hudStore";

/** __omniDebug 全局对象 key（inline 供 page.evaluate 使用）。 */
const OMNI_DEBUG_KEY = GLOBAL_KEYS.OMNI_DEBUG;

/** ShelfView 根节点选择器。 */
export const SHELF_VIEW_SELECTOR = '[data-testid="shelf-view"]';
/** 卡片数量选择器（display:none span）。 */
export const SHELF_CARD_COUNT_SELECTOR = '[data-testid="shelf-card-count"]';
/** hud-root 选择器（用于读取 data-field-mode 属性）。 */
export const HUD_ROOT_SELECTOR = '[data-testid="hud-root"]';

/**
 * 等待 ImmersiveSpace 场景就绪的超时时间。
 *
 * createSpace 异步动态 import three/postfx runtime + WebGL 上下文初始化，
 * headless Chromium 经 swiftshader 软渲染可能较慢，留 15s 缓冲。
 */
export const SPACE_READY_TIMEOUT = 15_000;

export class ShelfViewPage {
  readonly page: Page;
  readonly root: Locator;
  /** shelf-view 容器 Locator（与 root 同义，便于 spec 引用）。 */
  readonly shelfView: Locator;
  readonly cardCountLocator: Locator;
  readonly hudRoot: Locator;

  constructor(page: Page) {
    this.page = page;
    this.root = page.locator(SHELF_VIEW_SELECTOR);
    this.shelfView = page.locator(SHELF_VIEW_SELECTOR);
    this.cardCountLocator = page.locator(SHELF_CARD_COUNT_SELECTOR);
    this.hudRoot = page.locator(HUD_ROOT_SELECTOR);
  }

  /**
   * 等待 ShelfView 根节点挂载（Full 模式下由 App.tsx:353 渲染）。
   *
   * mini 模式下 App.tsx 走 mini 分支（line 308），ShelfView 不渲染；
   * Full / Wallpaper 模式下 ShelfView 恒挂载（div 始终在 DOM）。
   */
  async waitForMounted(timeout = 10_000): Promise<void> {
    await this.root.waitFor({ state: "attached", timeout });
  }

  /**
   * 等待 ShelfView 根节点卸载（切到 mini 模式时）。
   *
   * 用于验证 mini 模式下 ShelfView 不渲染（App.tsx mini 分支仅渲染 MiniBar）。
   */
  async waitForUnmounted(timeout = 5_000): Promise<void> {
    await this.root.waitFor({ state: "detached", timeout });
  }

  /**
   * 读取 shelf-card-count 的 textContent（display:none 元素，经 evaluate 读取）。
   *
   * cardCount 反映 ShelfStage 内部卡片数量：
   * - fieldMode=space：cardCount=0（ShelfStage 未创建 / 已 dispose）
   * - fieldMode=shelf + Space 就绪：cardCount=playlists.length
   * - fieldMode=shelf + Space 未就绪：cardCount=0（ShelfStage 未创建）
   *
   * 使用 page.evaluate 直接读 textContent 而非 locator.textContent()，
   * 确保 display:none 元素的文本也能可靠读取（Playwright 对 hidden 元素的
   * textContent 在某些版本下可能受 visibility 检查影响）。
   */
  async getCardCount(): Promise<number> {
    const text = await this.page.evaluate(() => {
      const el = document.querySelector('[data-testid="shelf-card-count"]');
      return el?.textContent ?? "0";
    });
    const n = Number(text);
    return Number.isFinite(n) ? n : 0;
  }

  /**
   * 等待 cardCount 等于目标值（轮询直到匹配或超时）。
   *
   * 用于等待 ShelfStage 创建 / setCards 完成后的 cardCount 更新——
   * React 重渲染 + ShelfStage.setCards 是异步过程，直接断言可能时序竞争。
   */
  async waitForCardCount(expected: number, timeout = 5_000): Promise<void> {
    await expect.poll(async () => this.getCardCount(), { timeout }).toBe(expected);
  }

  /**
   * 模拟右键 contextmenu 事件触发 hudStore.toggleFieldMode。
   *
   * ShelfView.tsx:126 onContextMenu 调 hudStore.toggleFieldMode()，
   * 在 space↔shelf 间翻转。使用 dispatchEvent 派发原生 contextmenu 事件
   * （React 18 经根委托监听 contextmenu，bubbles=true 确保冒泡到根容器）。
   *
   * 不用 locator.click({ button: "right" })：shelf-view div 无显式尺寸
   * （aria-hidden=true + pointerEvents=auto 但无 width/height），
   * Playwright 的点击需要可命中的元素盒，dispatchEvent 更可靠。
   */
  async rightClick(): Promise<void> {
    await this.page.evaluate(() => {
      const el = document.querySelector('[data-testid="shelf-view"]');
      if (!el) return;
      el.dispatchEvent(
        new MouseEvent("contextmenu", {
          bubbles: true,
          cancelable: true,
          clientX: 0,
          clientY: 0,
        }),
      );
    });
  }

  /**
   * 等待 ImmersiveSpace 场景就绪（spaceRef.current != null）。
   *
   * ImmersiveSpace.tsx:63 异步动态 import createSpace + runtime 后赋值
   * spaceRef.current，并在 DEV 模式（line 81）暴露 window.__debug_space__。
   *
   * ShelfView 的 shelf 分支依赖 spaceRef.current.getShelfHost() 获取 ShelfHost，
   * 场景未就绪时 host=null 静默跳过（ShelfStage 不创建，cardCount 保持 0）。
   * 测试在 rightClick 前需确保场景已就绪，否则 cardCount 不会更新。
   *
   * headless Chromium 经 swiftshader 软渲染，createSpace 可能较慢。
   */
  async waitForSpaceReady(timeout = SPACE_READY_TIMEOUT): Promise<void> {
    await this.page.waitForFunction(
      () =>
        (window as unknown as Record<string, unknown>).__debug_space__ != null,
      undefined,
      { timeout },
    );
  }

  /**
   * 判断 ImmersiveSpace 场景是否已就绪（非阻塞，不等待）。
   *
   * 用于测试 7（场景未就绪不抛错）：在场景可能未就绪时先 toggle 一次验证不 crash，
   * 再等就绪后正常验证。区别于 waitForSpaceReady 的阻塞等待。
   */
  async isSpaceReady(): Promise<boolean> {
    return await this.page.evaluate(() =>
      (window as unknown as Record<string, unknown>).__debug_space__ != null,
    );
  }

  /**
   * 读取 hud-root 的 data-field-mode 属性（space / shelf）。
   *
   * App.tsx 把 hudStore.fieldMode 暴露到 data-field-mode 属性供 E2E 断言。
   */
  async getFieldMode(): Promise<FieldMode> {
    const attr = await this.hudRoot.getAttribute("data-field-mode");
    return attr === "shelf" ? "shelf" : "space";
  }

  /**
   * 等待 hud-root 的 data-field-mode 等于目标值。
   */
  async waitForFieldMode(mode: FieldMode, timeout = 5_000): Promise<void> {
    await expect(this.hudRoot).toHaveAttribute("data-field-mode", mode, { timeout });
  }

  /**
   * 在 shelf-view 容器上触发滚轮事件（不 crash 即可）。
   *
   * 当前 ShelfView 不绑定 onWheel，事件被忽略；测试验证页面不抛错。
   */
  async wheel(deltaY: number): Promise<void> {
    await this.page.evaluate(
      (dy) => {
        const el = document.querySelector('[data-testid="shelf-view"]');
        if (!el) return;
        el.dispatchEvent(
          new WheelEvent("wheel", {
            bubbles: true,
            cancelable: true,
            deltaY: dy,
          }),
        );
      },
      deltaY,
    );
  }

  /**
   * 在 shelf-view 容器上模拟拖拽（pointerdown → pointermove → pointerup）。
   *
   * 当前 ShelfView 不绑定 onPointerDown/Move/Up，事件被忽略；测试验证页面不抛错。
   */
  async drag(dx: number, dy: number): Promise<void> {
    await this.page.evaluate(
      ([dx, dy]) => {
        const el = document.querySelector('[data-testid="shelf-view"]');
        if (!el) return;
        const rect = el.getBoundingClientRect();
        const startX = rect.left + rect.width / 2;
        const startY = rect.top + rect.height / 2;
        el.dispatchEvent(
          new PointerEvent("pointerdown", {
            bubbles: true,
            cancelable: true,
            clientX: startX,
            clientY: startY,
            pointerId: 1,
          }),
        );
        el.dispatchEvent(
          new PointerEvent("pointermove", {
            bubbles: true,
            cancelable: true,
            clientX: startX + dx,
            clientY: startY + dy,
            pointerId: 1,
          }),
        );
        el.dispatchEvent(
          new PointerEvent("pointerup", {
            bubbles: true,
            cancelable: true,
            clientX: startX + dx,
            clientY: startY + dy,
            pointerId: 1,
          }),
        );
      },
      [dx, dy] as const,
    );
  }

  /**
   * 在 shelf-view 容器上模拟点击（pointerdown → pointerup 同位置 + click）。
   *
   * 当前 ShelfView 不绑定点击事件（卡片是 3D Mesh，经 ShelfControls 命中测试）；
   * 测试验证页面不抛错。
   */
  async click(): Promise<void> {
    await this.page.evaluate(() => {
      const el = document.querySelector('[data-testid="shelf-view"]');
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const x = rect.left + rect.width / 2;
      const y = rect.top + rect.height / 2;
      el.dispatchEvent(
        new PointerEvent("pointerdown", {
          bubbles: true,
          cancelable: true,
          clientX: x,
          clientY: y,
          pointerId: 1,
        }),
      );
      el.dispatchEvent(
        new PointerEvent("pointerup", {
          bubbles: true,
          cancelable: true,
          clientX: x,
          clientY: y,
          pointerId: 1,
        }),
      );
      el.dispatchEvent(
        new MouseEvent("click", {
          bubbles: true,
          cancelable: true,
          clientX: x,
          clientY: y,
        }),
      );
    });
  }
}
