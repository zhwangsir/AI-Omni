/**
 * 水波纹参数（M4.4）：用户明确要求——扩散慢、范围大、多层同心圆渐隐。
 * 与粒子约束同款纪律：参数做成导出常量 + 模块加载即硬校验，
 * 防止后续迭代把波纹调回快而小。
 */

/** 单层波纹扩散时长（慢速）。 */
export const RIPPLE_DURATION_MS = 1500;
/** 波纹最大半径 px（大范围，覆盖大半个 HUD）。 */
export const RIPPLE_MAX_RADIUS = 460;
/** 同心圆层数（多层渐隐）。 */
export const RIPPLE_LAYERS = 3;
/** 层间错峰启动间隔。 */
export const RIPPLE_LAYER_STAGGER_MS = 140;

/** 慢速下限：低于此时长视为"过快"，违反设计目标。 */
export const RIPPLE_MIN_DURATION_MS = 900;
/** 大范围下限：低于此半径视为"过小"，违反设计目标。 */
export const RIPPLE_MIN_RADIUS = 240;

// 模块加载即硬校验：参数违反慢速/大范围/多层约束时直接拒绝启动。
if (RIPPLE_DURATION_MS < RIPPLE_MIN_DURATION_MS) {
  throw new Error(`波纹时长 ${RIPPLE_DURATION_MS}ms 低于慢速下限 ${RIPPLE_MIN_DURATION_MS}ms`);
}
if (RIPPLE_MAX_RADIUS < RIPPLE_MIN_RADIUS) {
  throw new Error(`波纹半径 ${RIPPLE_MAX_RADIUS}px 低于大范围下限 ${RIPPLE_MIN_RADIUS}px`);
}
if (RIPPLE_LAYERS < 2 || RIPPLE_LAYERS > 4) {
  throw new Error(`波纹层数 ${RIPPLE_LAYERS} 不在 2..4 多层约束内`);
}
if (RIPPLE_LAYER_STAGGER_MS < 0 || RIPPLE_LAYER_STAGGER_MS * (RIPPLE_LAYERS - 1) >= RIPPLE_DURATION_MS) {
  throw new Error("波纹层间错峰非法：末层必须在主波纹结束前启动");
}

/** 逐层启动延迟（ms），长度 = RIPPLE_LAYERS，首层为 0 并严格递增。 */
export function rippleLayerDelays(): number[] {
  return Array.from({ length: RIPPLE_LAYERS }, (_, i) => i * RIPPLE_LAYER_STAGGER_MS);
}
