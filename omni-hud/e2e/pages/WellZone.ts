/**
 * WellZone Page Object（M4-M7 显影场 E2E）。
 *
 * 封装对 WellZone 组件（src/components/WellZone.tsx）的查询与断言：
 * - data-testid="well-zone"：WellZone 根节点（底部居中椭圆区）
 *   - data-sleeping="true|false"：是否处于睡眠态
 * - data-testid="well-ring"：控制环（hover 时显影；spec §二：sleeping 时只留唤醒入口）
 * - data-testid="well-status-dot"：语音状态点（control ring 内）
 *   - data-state="idle|speaking|..."：当前 voice.state（用于断言场语义切换）
 * - data-testid="well-sleep-toggle"：睡眠切换按钮
 * - data-testid="well-center"：井心 caption 卡入口按钮
 *
 * 行为契约（WellZone.tsx）：
 * - well 分区恒注册（包括睡眠态），故 well-zone 元素在 full 形态下始终挂载
 * - mini 形态下 App.tsx 不渲染 WellZone（仅 MiniBar）
 * - control ring 仅在 hovered 时渲染（showRing = hovered）
 */
import { expect, type Page, type Locator } from "@playwright/test";

/** WellZone 根节点选择器。 */
export const WELL_ZONE_SELECTOR = '[data-testid="well-zone"]';
/** 控制环选择器。 */
export const WELL_RING_SELECTOR = '[data-testid="well-ring"]';
/** 语音状态点选择器。 */
export const WELL_STATUS_DOT_SELECTOR = '[data-testid="well-status-dot"]';

export class WellZonePage {
  readonly page: Page;
  readonly root: Locator;
  readonly ring: Locator;
  readonly statusDot: Locator;

  constructor(page: Page) {
    this.page = page;
    this.root = page.locator(WELL_ZONE_SELECTOR);
    this.ring = page.locator(WELL_RING_SELECTOR);
    this.statusDot = page.locator(WELL_STATUS_DOT_SELECTOR);
  }

  /** 等待 WellZone 根节点挂载（full 形态下出现）。 */
  async waitForMounted(timeout = 5_000): Promise<void> {
    await this.root.waitFor({ state: "attached", timeout });
  }

  /** 等待 WellZone 根节点卸载（切到 mini 形态后消失）。 */
  async waitForUnmounted(timeout = 5_000): Promise<void> {
    await this.root.waitFor({ state: "detached", timeout });
  }

  /** 读取 data-sleeping 属性值。 */
  async getSleeping(): Promise<boolean> {
    const attr = await this.root.getAttribute("data-sleeping");
    return attr === "true";
  }

  /**
   * 触发 pointerover 事件让 WellZone 进入 hovered 态（控制环显影）。
   *
   * WellZone.tsx:113 onPointerEnter 回调设置 hovered=true → showRing=true
   * → well-ring 元素挂载。React 18 委托 pointerenter 通过监听 pointerover
   * （冒泡事件）在根容器合成。直接 dispatch pointerover（bubbles=true）
   * 可靠触发 React handler，与 HudApp.hoverCaptionSubtitle 同款模式。
   */
  async hover(): Promise<void> {
    await this.page.evaluate(() => {
      const el = document.querySelector('[data-testid="well-zone"]');
      if (!el) return;
      el.dispatchEvent(
        new PointerEvent("pointerover", {
          bubbles: true,
          cancelable: true,
          relatedTarget: null,
        }),
      );
      el.dispatchEvent(
        new MouseEvent("mouseover", {
          bubbles: true,
          cancelable: true,
          relatedTarget: null,
        }),
      );
    });
  }

  /** 触发 pointerout 事件让 WellZone 离开 hovered 态（控制环收起）。 */
  async unhover(): Promise<void> {
    await this.page.evaluate(() => {
      const el = document.querySelector('[data-testid="well-zone"]');
      if (!el) return;
      el.dispatchEvent(
        new PointerEvent("pointerout", {
          bubbles: true,
          cancelable: true,
          relatedTarget: null,
        }),
      );
      el.dispatchEvent(
        new MouseEvent("mouseout", {
          bubbles: true,
          cancelable: true,
          relatedTarget: null,
        }),
      );
    });
  }

  /** 等待控制环挂载（hover 后）。 */
  async waitForRingMounted(timeout = 5_000): Promise<void> {
    await this.ring.waitFor({ state: "attached", timeout });
  }

  /** 读取状态点的 data-state 属性值（当前 voice.state ?? "离线"）。 */
  async getStatusDotState(): Promise<string> {
    return (await this.statusDot.getAttribute("data-state")) ?? "";
  }

  /** 等待状态点 data-state 等于目标值。 */
  async waitForStatusDotState(state: string, timeout = 5_000): Promise<void> {
    await expect(this.statusDot).toHaveAttribute("data-state", state, { timeout });
  }
}
