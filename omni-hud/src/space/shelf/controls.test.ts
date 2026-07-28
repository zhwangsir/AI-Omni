/**
 * shelf/controls 交互控制（M20.3 TDD 红）：
 * - 拖拽旋转：pointer dx → group.rotation.y 增量，钳制在 [MIN, MAX]；
 * - 滚轮缩放：deltaY → 相机 z 偏移，钳制在 [ZOOM_MIN, ZOOM_MAX]；
 * - 惯性阻尼：拖拽松开后角速度逐帧衰减（spring ease-out，Film Atelier 风格）；
 * - 悬停命中：NDC 坐标 + 卡片 layout → 命中卡片 index（射线投影到弧形圆周的简化版）；
 * - 点击触发：命中卡片 → select(index)；
 * - reducedMotion：拖拽 / 滚轮仍生效（交互不被禁用），但惯性阻尼归零（瞬停）。
 *
 * 纯逻辑模块：不依赖 React / three / DOM；输入输出明确，可独立单测。
 */
import { describe, expect, it, vi } from "vitest";

import { computeArcLayout } from "./layout";
import {
  DRAG_ROTATION_MAX,
  DRAG_ROTATION_MIN,
  ZOOM_MAX,
  ZOOM_MIN,
  computeHoverHit,
  createShelfControls,
} from "./controls";

describe("computeHoverHit 悬停命中", () => {
  const layout = computeArcLayout(5, { radius: 4, spanDeg: 90 });

  it("指针在卡片正上方（NDC 接近卡片屏幕位置）返回该卡片 index", () => {
    // 中间卡片 index=2 在正前方，NDC (0, 0) 应命中
    const hit = computeHoverHit(0, 0, layout, { width: 800, height: 600, cameraZ: 8, fovDeg: 42 });
    expect(hit).toBe(2);
  });

  it("指针偏离所有卡片返回 null", () => {
    // 远离弧形区域的 NDC
    const hit = computeHoverHit(0.95, 0.95, layout, { width: 800, height: 600, cameraZ: 8, fovDeg: 42 });
    expect(hit).toBeNull();
  });

  it("命中半径内取最近卡片（多卡重叠时选最近的）", () => {
    // 卡片密集排列时，NDC 命中半径内的卡片
    const denseLayout = computeArcLayout(10, { radius: 4, spanDeg: 60 });
    const hit = computeHoverHit(0, 0, denseLayout, { width: 800, height: 600, cameraZ: 8, fovDeg: 42 });
    expect(hit).not.toBeNull();
    expect(hit).toBeGreaterThanOrEqual(0);
    expect(hit).toBeLessThan(10);
  });
});

describe("ShelfControls 拖拽旋转", () => {
  it("初始 rotationY=0", () => {
    const ctrl = createShelfControls();
    expect(ctrl.getState().rotationY).toBe(0);
  });

  it("拖拽 dx>0 → rotationY 增加（向右拖拽卡片架向左转）", () => {
    const ctrl = createShelfControls();
    ctrl.onPointerDown(0, 0);
    ctrl.onDragMove(0.2, 0, 800);
    expect(ctrl.getState().rotationY).toBeGreaterThan(0);
  });

  it("拖拽 dx<0 → rotationY 减小", () => {
    const ctrl = createShelfControls();
    ctrl.onPointerDown(0, 0);
    ctrl.onDragMove(-0.2, 0, 800);
    expect(ctrl.getState().rotationY).toBeLessThan(0);
  });

  it("rotationY 钳制在 [DRAG_ROTATION_MIN, DRAG_ROTATION_MAX]", () => {
    const ctrl = createShelfControls();
    ctrl.onPointerDown(0, 0);
    // 极大 NDC dx 触发上限钳制
    ctrl.onDragMove(100, 0, 800);
    expect(ctrl.getState().rotationY).toBeLessThanOrEqual(DRAG_ROTATION_MAX);
    expect(ctrl.getState().rotationY).toBeGreaterThanOrEqual(DRAG_ROTATION_MIN);
  });

  it("onDragEnd 启动惯性（角速度非零时不立即归零）", () => {
    const ctrl = createShelfControls();
    ctrl.onPointerDown(0, 0);
    ctrl.onDragMove(0.2, 0, 800);
    ctrl.onDragEnd(0.4, 0, 800);
    const v0 = ctrl.getState().angularVelocity;
    expect(v0).not.toBe(0);
    // step 后角速度衰减
    ctrl.step(0.016);
    const v1 = ctrl.getState().angularVelocity;
    expect(Math.abs(v1)).toBeLessThan(Math.abs(v0));
  });

  it("reducedMotion=true 时 onDragEnd 角速度立即归零（瞬停）", () => {
    const ctrl = createShelfControls({ reducedMotion: true });
    ctrl.onPointerDown(0, 0);
    ctrl.onDragMove(0.2, 0, 800);
    ctrl.onDragEnd(0.4, 0, 800);
    expect(ctrl.getState().angularVelocity).toBe(0);
  });

  it("惯性 step 多次后角速度收敛到 0（阻尼衰减）", () => {
    const ctrl = createShelfControls();
    ctrl.onPointerDown(0, 0);
    ctrl.onDragMove(0.2, 0, 800);
    ctrl.onDragEnd(0.4, 0, 800);
    for (let i = 0; i < 200; i++) ctrl.step(0.016);
    expect(Math.abs(ctrl.getState().angularVelocity)).toBeCloseTo(0, 4);
  });

  it("惯性期间 rotationY 持续变化（积分角速度）", () => {
    const ctrl = createShelfControls();
    ctrl.onPointerDown(0, 0);
    ctrl.onDragMove(0.2, 0, 800);
    ctrl.onDragEnd(0.4, 0, 800);
    const rot0 = ctrl.getState().rotationY;
    for (let i = 0; i < 30; i++) ctrl.step(0.016);
    const rot1 = ctrl.getState().rotationY;
    expect(rot1).not.toBeCloseTo(rot0, 4);
  });
});

describe("ShelfControls 滚轮缩放", () => {
  it("初始 zoomZ=0（相机在默认位置）", () => {
    const ctrl = createShelfControls();
    expect(ctrl.getState().zoomZ).toBe(0);
  });

  it("deltaY>0（向下滚）→ zoomZ 增加（相机后退，卡片变小）", () => {
    const ctrl = createShelfControls();
    ctrl.onWheel(100);
    expect(ctrl.getState().zoomZ).toBeGreaterThan(0);
  });

  it("deltaY<0（向上滚）→ zoomZ 减小（相机前进，卡片变大）", () => {
    const ctrl = createShelfControls();
    ctrl.onWheel(-100);
    expect(ctrl.getState().zoomZ).toBeLessThan(0);
  });

  it("zoomZ 钳制在 [ZOOM_MIN, ZOOM_MAX]", () => {
    const ctrl = createShelfControls();
    ctrl.onWheel(-100000);
    expect(ctrl.getState().zoomZ).toBeGreaterThanOrEqual(ZOOM_MIN);
    ctrl.onWheel(100000);
    expect(ctrl.getState().zoomZ).toBeLessThanOrEqual(ZOOM_MAX);
  });
});

describe("ShelfControls 重置", () => {
  it("reset 把 rotationY / zoomZ / angularVelocity 归零", () => {
    const ctrl = createShelfControls();
    ctrl.onPointerDown(0, 0);
    ctrl.onDragMove(0.2, 0, 800);
    ctrl.onDragEnd(0.4, 0, 800);
    ctrl.onWheel(100);
    ctrl.reset();
    expect(ctrl.getState().rotationY).toBe(0);
    expect(ctrl.getState().zoomZ).toBe(0);
    expect(ctrl.getState().angularVelocity).toBe(0);
  });
});

describe("ShelfControls 点击触发", () => {
  it("onPointerDown + onPointerUp（无拖拽）→ 触发点击回调（命中 index）", () => {
    const layout = computeArcLayout(3, { radius: 4, spanDeg: 90 });
    const onClick = vi.fn();
    const ctrl = createShelfControls({ onClick });
    // 中间卡片在 NDC (0,0)
    ctrl.onPointerDown(0, 0);
    const clicked = ctrl.onPointerUp(0, 0, layout, { width: 800, height: 600, cameraZ: 8, fovDeg: 42 });
    expect(clicked).toBe(true);
    expect(onClick).toHaveBeenCalledWith(1); // 中间卡片 index=1
  });

  it("拖拽移动后 onPointerUp 不触发点击（视为拖拽而非点击）", () => {
    const layout = computeArcLayout(3, { radius: 4, spanDeg: 90 });
    const onClick = vi.fn();
    const ctrl = createShelfControls({ onClick });
    ctrl.onPointerDown(0, 0);
    ctrl.onDragMove(50, 0, 800); // 拖拽
    const clicked = ctrl.onPointerUp(50, 0, layout, { width: 800, height: 600, cameraZ: 8, fovDeg: 42 });
    expect(clicked).toBe(false);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("未命中卡片时不触发点击回调", () => {
    const layout = computeArcLayout(3, { radius: 4, spanDeg: 90 });
    const onClick = vi.fn();
    const ctrl = createShelfControls({ onClick });
    ctrl.onPointerDown(0.95, 0.95);
    const clicked = ctrl.onPointerUp(0.95, 0.95, layout, { width: 800, height: 600, cameraZ: 8, fovDeg: 42 });
    expect(clicked).toBe(false);
    expect(onClick).not.toHaveBeenCalled();
  });
});
