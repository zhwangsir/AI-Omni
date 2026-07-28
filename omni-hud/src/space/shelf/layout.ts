/**
 * shelf/layout 弧形卡片排列几何（M20.1）。
 *
 * 设计决策 D20.1：
 * - 卡片以 XZ 平面圆周分布（圆心在原点），每张卡片落在「圆心向外射线」上，
 *   半径恒定，正面经 Y 轴旋转朝向圆心（视角即相机在原点正前方 z=+radius 处）。
 * - 张角跨度有界（≤120°），卡片过密时角度跨度不拉伸（视觉约束：克制不爆炸）。
 * - 垂直抬升可选：沿 index 线性变化，中间张 y=0、两端对称（中间高 / 两端低或反之）。
 * - 入场偏移：默认在卡片正前方 z 方向偏移 ENTER_OFFSET_Z（从远处推进），
 *   reducedMotion=true 时归零（静态直挂，禁动画）。
 *
 * 纯逻辑模块：不依赖 three / WebGL，可独立单测。
 */

/** 弧形排列半径下限（世界单位，与 FieldStage 相机 z=8 同量级）。 */
export const ARC_RADIUS_MIN = 2.0;
/** 弧形排列半径上限（避免卡片溢出视锥远端）。 */
export const ARC_RADIUS_MAX = 8.0;
/** 弧形排列半径缺省值（与 FieldStage 相机距离协调，卡片在相机前方）。 */
export const ARC_RADIUS_DEFAULT = 4.0;
/** 张角跨度上限（度，视觉约束：克制不爆炸；CLAUDE.md §六 红线）。 */
export const ARC_MAX_SPAN_DEG = 120;
/** 张角跨度缺省值（中等弧度，单屏可见全部卡片）。 */
export const ARC_DEFAULT_SPAN_DEG = 90;
/** 入场动画 z 方向偏移（卡片从远处推进；reducedMotion 归零）。 */
export const ENTER_OFFSET_Z = 2.0;

export interface CardPosition {
  /** 卡片 index（0..count-1）。 */
  readonly index: number;
  /** 世界坐标。 */
  readonly position: { readonly x: number; readonly y: number; readonly z: number };
  /** Y 轴旋转角（弧度），使卡片正面朝向圆心。 */
  readonly rotationY: number;
  /** 张角位置（度，相对正前方中分线，左负右正）。 */
  readonly angleDeg: number;
  /** 入场动画起始偏移（叠加到 position 上的初始位移）。 */
  readonly enterOffset: { readonly x: number; readonly y: number; readonly z: number };
}

export interface ArcLayoutOptions {
  /** 弧半径（世界单位）；缺省 ARC_RADIUS_DEFAULT。 */
  readonly radius?: number;
  /** 张角跨度（度）；缺省 ARC_DEFAULT_SPAN_DEG。 */
  readonly spanDeg?: number;
  /** 垂直抬升幅度（世界单位，沿 index 线性，中间为 0）；缺省 0（共面）。 */
  readonly liftY?: number;
  /** 入场动画偏移反转方向：true=从相机方向推进（z+），false=从远处推进（z-）。 */
  readonly enterFromFront?: boolean;
  /** reducedMotion=true 时入场偏移归零（静态直挂）。 */
  readonly reducedMotion?: boolean;
}

const DEG2RAD = Math.PI / 180;

/**
 * 计算弧形卡片排列。
 *
 * @param count 卡片数；0 返回空数组；负数 / 非整数抛 RangeError
 * @param options 见 ArcLayoutOptions；半径 / 张角越界抛 RangeError
 */
export function computeArcLayout(count: number, options: ArcLayoutOptions = {}): readonly CardPosition[] {
  if (!Number.isInteger(count) || count < 0) {
    throw new RangeError(`卡片数必须为非负整数: ${count}`);
  }
  if (count === 0) return [];

  const radius = options.radius ?? ARC_RADIUS_DEFAULT;
  if (!Number.isFinite(radius) || radius < ARC_RADIUS_MIN || radius > ARC_RADIUS_MAX) {
    throw new RangeError(`弧半径越界 [${ARC_RADIUS_MIN}, ${ARC_RADIUS_MAX}]: ${radius}`);
  }

  const spanDeg = options.spanDeg ?? ARC_DEFAULT_SPAN_DEG;
  if (!Number.isFinite(spanDeg) || spanDeg <= 0 || spanDeg > ARC_MAX_SPAN_DEG) {
    throw new RangeError(`张角跨度越界 (0, ${ARC_MAX_SPAN_DEG}]: ${spanDeg}`);
  }

  const liftY = options.liftY ?? 0;
  const reducedMotion = options.reducedMotion ?? false;
  const enterFromFront = options.enterFromFront ?? false;
  const enterSign = enterFromFront ? 1 : -1;
  const enterZ = reducedMotion ? 0 : enterSign * ENTER_OFFSET_Z;

  // 单卡：角度为 0（正前方）。多卡：从 -span/2 到 +span/2 等角分布。
  const halfSpan = spanDeg / 2;
  const positions: CardPosition[] = [];
  for (let i = 0; i < count; i++) {
    let angleDeg: number;
    if (count === 1) {
      angleDeg = 0;
    } else {
      // 等角分布：i 从 0 到 count-1，映射到 [-halfSpan, +halfSpan]
      angleDeg = -halfSpan + (i / (count - 1)) * spanDeg;
    }
    const angleRad = angleDeg * DEG2RAD;
    const x = radius * Math.sin(angleRad);
    const z = radius * Math.cos(angleRad);
    // Y 旋转：卡片正面朝向圆心（原点）。
    // 相机在 +z 方向看 -z；卡片在 (x,0,z)，正面朝向原点 = 朝向 -z 方向旋转 angleDeg。
    // 三角函数推导：正面法向量从 (0,0,1) 旋转到 (-sin(angle), 0, -cos(angle))，
    // 等价于绕 Y 轴旋转 (angle + π)，但为了与角度方向一致取 -angle。
    const rotationY = -angleRad;
    // 垂直抬升：沿 index 线性，中间为 0（count 为奇数时正中张 y=0；偶数时中间两张对称）
    const liftIndex = count === 1 ? 0 : i - (count - 1) / 2;
    // +0 归一化：避免 0 * 负数 = -0 导致序列化 / 断言不一致
    const y = liftY * liftIndex + 0;
    positions.push({
      index: i,
      position: { x, y, z },
      rotationY,
      angleDeg,
      enterOffset: { x: 0, y: 0, z: enterZ },
    });
  }
  return positions;
}
