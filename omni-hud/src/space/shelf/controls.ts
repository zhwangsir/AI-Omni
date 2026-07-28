/**
 * shelf/controls 交互控制（M20.3）。
 *
 * 设计决策 D20.3：自定义交互控制（不用 OrbitControls）——
 * - OrbitControls 会覆盖 FieldStage 相机 rig（视差）；我们只需 Y 轴弧形旋转 + 有界缩放。
 * - 纯逻辑模块：状态机 + 数学，不依赖 React / three / DOM；时序与副作用经依赖注入。
 * - 拖拽：pointer dx → rotationY 增量（视口宽度归一化），钳制 [MIN, MAX]。
 * - 惯性：松开后角速度逐帧衰减（ROTATION_DAMPING/s），reducedMotion 瞬停。
 * - 滚轮：deltaY → zoomZ 增量，钳制 [ZOOM_MIN, ZOOM_MAX]（相机 z 偏移，正=后退）。
 * - 悬停：NDC + layout → 命中卡片 index（简化射线投影：NDC 反投影到弧形圆周平面）。
 * - 点击：down→up 位移 < CLICK_THRESHOLD_PX 视为点击，触发 onClick(index)。
 *
 * Film Atelier 风格：阻尼克制（spring ease-out），无高频抖动；reducedMotion 仍可交互但瞬停。
 */
import type { CardPosition } from "./layout";

/** 拖拽旋转角度下限（弧度，约 -60°）。 */
export const DRAG_ROTATION_MIN = -Math.PI / 3;
/** 拖拽旋转角度上限（弧度，约 +60°）。 */
export const DRAG_ROTATION_MAX = Math.PI / 3;
/** 拖拽灵敏度：1 视口宽度的 dx → 旋转弧度（约 30°/视口宽，克制）。 */
export const DRAG_SENSITIVITY = Math.PI / 6;
/** 惯性角速度衰减率（/s，~0.7s 内衰减到 ~10%，Film Atelier 风格克制）。 */
export const ROTATION_DAMPING = 3.5;
/** 惯性角速度下限（低于此值直接归零，避免无穷小漂移）。 */
export const ANGULAR_VELOCITY_EPSILON = 0.001;
/** 滚轮缩放下限（相机 z 偏移，正=后退；-3 = 前进 3 单位）。 */
export const ZOOM_MIN = -3;
/** 滚轮缩放上限（+4 = 后退 4 单位）。 */
export const ZOOM_MAX = 4;
/** 滚轮灵敏度（deltaY 单位 → zoomZ 增量系数，克制）。 */
export const WHEEL_SENSITIVITY = 0.005;
/** 悬停命中半径（NDC 单位，0..1；卡片屏幕投影到此半径内视为命中）。 */
export const HOVER_HIT_RADIUS = 0.12;
/** 点击阈值（NDC 单位）：down→up 位移 < 此值视为点击。 */
export const CLICK_THRESHOLD_NDC = 0.02;
/** 拖拽释放时计算角速度的假定帧时长（秒）；避免 wall-clock 抖动导致速度爆炸。 */
export const ASSUMED_FRAME_DT = 0.016;
/** 角速度上限（rad/s，防止极端拖拽产生爆炸性惯性）。 */
export const ANGULAR_VELOCITY_MAX = 8.0;

export interface ViewportInfo {
  readonly width: number;
  readonly height: number;
  readonly cameraZ: number;
  readonly fovDeg: number;
}

export interface ShelfControlsState {
  /** 当前 Y 轴旋转角（弧度）。 */
  rotationY: number;
  /** 当前角速度（弧度/s，惯性用）。 */
  angularVelocity: number;
  /** 当前相机 z 偏移（正=后退，负=前进）。 */
  zoomZ: number;
  /** 是否正在拖拽。 */
  isDragging: boolean;
}

export interface ShelfControlsOptions {
  /** reducedMotion=true 时惯性瞬停（拖拽 / 滚轮仍生效）。 */
  readonly reducedMotion?: boolean;
  /** 点击命中卡片回调（携带 index）。 */
  readonly onClick?: (index: number) => void;
}

export interface ShelfControls {
  /** 当前状态快照。 */
  getState(): ShelfControlsState;
  /** 指针按下（NDC 坐标）。 */
  onPointerDown(ndcX: number, ndcY: number): void;
  /** 拖拽移动（NDC 坐标 + 视口宽度，用于灵敏度归一化）。 */
  onDragMove(ndcX: number, ndcY: number, viewportWidth: number): void;
  /** 拖拽结束（NDC 坐标 + 视口宽度，计算释放角速度）。 */
  onDragEnd(ndcX: number, ndcY: number, viewportWidth: number): void;
  /** 滚轮（deltaY 像素）。 */
  onWheel(deltaY: number): void;
  /** 指针抬起：返回是否触发点击（true=点击命中，false=拖拽或未命中）。 */
  onPointerUp(
    ndcX: number,
    ndcY: number,
    layout: readonly CardPosition[],
    viewport: ViewportInfo,
  ): boolean;
  /** 推进一帧（惯性衰减 + rotationY 积分）。 */
  step(dt: number): void;
  /** 重置到初始状态。 */
  reset(): void;
}

const clamp = (value: number, min: number, max: number): number =>
  Math.min(max, Math.max(min, value));

/**
 * 把卡片世界坐标投影到 NDC（简化透视投影，与 three.PerspectiveCamera 一致）。
 * 用于悬停命中测试：NDC 指针与卡片 NDC 投影距离 < HOVER_HIT_RADIUS 视为命中。
 */
function projectWorldToNdc(
  worldX: number,
  worldY: number,
  worldZ: number,
  viewport: ViewportInfo,
): { x: number; y: number } {
  // 相机在 (0, 0, cameraZ)，朝 -z 方向；卡片在 z=worldZ（worldZ < cameraZ）
  // 透视：ndc.x = worldX / (cameraZ - worldZ) / tan(fov/2) / aspect
  const fovRad = (viewport.fovDeg * Math.PI) / 180;
  const tanHalfFov = Math.tan(fovRad / 2);
  const aspect = viewport.width / viewport.height;
  const distance = viewport.cameraZ - worldZ;
  if (distance <= 0) return { x: 0, y: 0 };
  const ndcX = worldX / (distance * tanHalfFov * aspect);
  const ndcY = worldY / (distance * tanHalfFov);
  return { x: ndcX, y: ndcY };
}

/**
 * 悬停命中测试：返回指针命中的卡片 index，未命中返回 null。
 * 多卡在命中半径内时取最近的（按距离排序）。
 */
export function computeHoverHit(
  ndcX: number,
  ndcY: number,
  layout: readonly CardPosition[],
  viewport: ViewportInfo,
): number | null {
  if (layout.length === 0) return null;
  let bestIndex: number | null = null;
  let bestDist = HOVER_HIT_RADIUS;
  for (let i = 0; i < layout.length; i++) {
    const pos = layout[i]!;
    const proj = projectWorldToNdc(pos.position.x, pos.position.y, pos.position.z, viewport);
    const dist = Math.hypot(proj.x - ndcX, proj.y - ndcY);
    if (dist < bestDist) {
      bestDist = dist;
      bestIndex = i;
    }
  }
  return bestIndex;
}

export function createShelfControls(options: ShelfControlsOptions = {}): ShelfControls {
  const reducedMotion = options.reducedMotion ?? false;
  const onClick = options.onClick;

  let state: ShelfControlsState = {
    rotationY: 0,
    angularVelocity: 0,
    zoomZ: 0,
    isDragging: false,
  };
  // 拖拽起点（NDC）+ 上次位置（NDC，用于计算释放角速度）
  let downX = 0;
  let downY = 0;
  let lastX = 0;
  // 上一次 drag move 的 dRotation（弧度），用于 onDragEnd 计算释放角速度
  let lastDRotation = 0;

  return {
    getState: () => state,

    onPointerDown(ndcX: number, ndcY: number): void {
      downX = ndcX;
      downY = ndcY;
      lastX = ndcX;
      lastDRotation = 0;
      state = { ...state, isDragging: false, angularVelocity: 0 };
    },

    onDragMove(ndcX: number, _ndcY: number, _viewportWidth: number): void {
      const dxNdc = ndcX - lastX;
      // NDC dx → 弧度：1 视口宽 = DRAG_SENSITIVITY 弧度
      const dRotation = dxNdc * DRAG_SENSITIVITY;
      state = {
        ...state,
        rotationY: clamp(state.rotationY + dRotation, DRAG_ROTATION_MIN, DRAG_ROTATION_MAX),
        isDragging: true,
      };
      lastDRotation = dRotation;
      lastX = ndcX;
    },

    onDragEnd(_ndcX: number, _ndcY: number, _viewportWidth: number): void {
      if (reducedMotion) {
        state.angularVelocity = 0;
      } else {
        // 释放角速度 = 上一次 drag move 的 dRotation / 假定帧时长
        // （避免 wall-clock 抖动导致速度爆炸；假定 60fps 是合理均值）
        const v = lastDRotation / ASSUMED_FRAME_DT;
        state.angularVelocity = clamp(v, -ANGULAR_VELOCITY_MAX, ANGULAR_VELOCITY_MAX);
      }
      state = { ...state, isDragging: false };
    },

    onWheel(deltaY: number): void {
      const dz = deltaY * WHEEL_SENSITIVITY;
      state = {
        ...state,
        zoomZ: clamp(state.zoomZ + dz, ZOOM_MIN, ZOOM_MAX),
      };
    },

    onPointerUp(ndcX, ndcY, layout, viewport): boolean {
      // 判断是否为点击：down→up 位移 < CLICK_THRESHOLD_NDC 且未发生拖拽
      const moved = Math.hypot(ndcX - downX, ndcY - downY);
      const wasDragging = state.isDragging;
      state = { ...state, isDragging: false };
      if (wasDragging || moved > CLICK_THRESHOLD_NDC) {
        return false;
      }
      const hit = computeHoverHit(ndcX, ndcY, layout, viewport);
      if (hit === null) return false;
      onClick?.(hit);
      return true;
    },

    step(dt: number): void {
      if (Math.abs(state.angularVelocity) < ANGULAR_VELOCITY_EPSILON) {
        if (state.angularVelocity !== 0) state.angularVelocity = 0;
        return;
      }
      // rotationY 积分
      const dRot = state.angularVelocity * dt;
      state = {
        ...state,
        rotationY: clamp(state.rotationY + dRot, DRAG_ROTATION_MIN, DRAG_ROTATION_MAX),
      };
      // 角速度衰减（指数衰减，spring ease-out 感）
      const decay = Math.exp(-ROTATION_DAMPING * dt);
      state.angularVelocity *= decay;
      if (Math.abs(state.angularVelocity) < ANGULAR_VELOCITY_EPSILON) {
        state.angularVelocity = 0;
      }
    },

    reset(): void {
      state = { rotationY: 0, angularVelocity: 0, zoomZ: 0, isDragging: false };
      downX = 0;
      downY = 0;
      lastX = 0;
      lastDRotation = 0;
    },
  };
}
