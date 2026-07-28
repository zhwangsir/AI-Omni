/**
 * shelf/animation 卡片架动画状态机（M20.5）。
 *
 * 设计决策 D20.5：
 * - stagger 入场：每张卡片延迟 STAGGER_MS（50ms）启动入场动画；
 *   入场时长 ENTER_DURATION_MS（750ms），缓动 easeOutSmoothstep（Film Atelier 风格克制有物理感）。
 * - 收缩消散：触发 exit 后所有卡片同步淡出（无 stagger），时长 EXIT_DURATION_MS（600ms）；
 *   退场独立计时，不重置入场进度（卡片仍「已入场」，只是淡出）。
 * - reducedMotion：stagger 归零（所有卡片同步直挂），easing 退化为阶跃；
 *   入场瞬时 progress=1，退场瞬时 progress=0。
 * - setCardCount 扩展时新卡片 enterStartedAt=null（未入场），需再次调用 enter 才启动；
 *   缩减时截断保留前 N 张状态。
 *
 * 纯逻辑模块：不依赖 three / React / DOM，可独立单测。时序经 step(dtMs) 推进。
 */

/** 入场动画时长（ms，Film Atelier 风格克制，~0.75s 收敛）。 */
export const ENTER_DURATION_MS = 750;
/** 退场动画时长（ms，~0.6s 收缩消散）。 */
export const EXIT_DURATION_MS = 600;
/** 入场 stagger 间隔（ms，每张卡片相对前一张延迟启动）。 */
export const STAGGER_MS = 50;

/**
 * ease-out smoothstep 缓动函数（Film Atelier 风格克制有物理感）。
 *
 * smoothstep 公式 3x² - 2x³ 在 t=0/0.5/1 处对称且单调递增；
 * 起步快、收敛慢，符合「物理感与呼吸感」的暗房风格约束（CLAUDE.md §六）。
 * 输入越界钳制到 [0, 1]。
 */
export function easeOutSmoothstep(t: number): number {
  const x = Math.min(1, Math.max(0, t));
  return x * x * (3 - 2 * x);
}

/** 单张卡片动画状态快照。 */
export interface CardAnimationState {
  /** 入场进度 0..1（0=未入场，1=完全入场）。 */
  readonly enterProgress: number;
  /** 退场进度 0..1（1=完全可见，0=完全消散）。 */
  readonly exitProgress: number;
}

export interface ShelfAnimationOptions {
  /** reducedMotion=true 时所有动画瞬时完成（无 stagger，无缓动）。 */
  readonly reducedMotion?: boolean;
}

export interface ShelfAnimation {
  /** 触发入场（now 为当前绝对时间 ms；卡片 i 的入场开始时间 = now + i*STAGGER_MS）。 */
  enter(now: number): void;
  /** 触发退场（now 为当前绝对时间 ms；所有卡片同步退场，无 stagger）。 */
  exit(now: number): void;
  /** 重置：所有卡片 enterStartedAt=null / exitStartedAt=null（enterProgress=0 / exitProgress=1）。 */
  reset(): void;
  /** 推进时间（dtMs 毫秒，可为 0）。 */
  step(dtMs: number): void;
  /** 调整卡片数（扩展新卡片 enterStartedAt=null；缩减截断保留前 N 张状态）。 */
  setCardCount(count: number): void;
  /** 读取单张卡片动画状态（越界抛 RangeError）。 */
  getState(index: number): CardAnimationState;
}

/**
 * 创建卡片架动画状态机。
 *
 * @param cardCount 初始卡片数（非负整数）
 * @param options 见 ShelfAnimationOptions
 * @throws RangeError cardCount 非非负整数
 */
export function createShelfAnimation(
  cardCount: number,
  options: ShelfAnimationOptions = {},
): ShelfAnimation {
  const reducedMotion = options.reducedMotion ?? false;

  if (!Number.isInteger(cardCount) || cardCount < 0) {
    throw new RangeError(`卡片数必须为非负整数: ${cardCount}`);
  }

  let count = cardCount;
  // 当前绝对时间（ms），仅经 step 推进；enter/exit 的 now 参数仅作为下限钳制
  //（避免外部时钟回退导致 elapsed 为负）。
  let currentTime = 0;
  // 每张卡片的入场开始时间（绝对时间 ms）；null = 未触发入场（如 setCardCount 扩展的新卡片）
  let enterStartedAt: Array<number | null> = new Array(cardCount).fill(null);
  // 退场开始时间（绝对时间 ms）；null = 未触发退场。退场无 stagger，所有卡片共享同一开始时间。
  let exitStartedAt: number | null = null;

  return {
    enter(now: number): void {
      if (now > currentTime) currentTime = now;
      // 每张卡片按 index 错开 STAGGER_MS 启动；stagger 烘焙到开始时间里，
      // getState 计算 elapsed = currentTime - enterStartedAt[i] 自然包含延迟。
      for (let i = 0; i < count; i++) {
        enterStartedAt[i] = currentTime + i * STAGGER_MS;
      }
      // 触发入场时清除退场状态（卡片恢复可见）
      exitStartedAt = null;
    },

    exit(now: number): void {
      if (now > currentTime) currentTime = now;
      // 退场独立计时：exitStartedAt = currentTime，不重置 enterStartedAt
      //（卡片仍「已入场」，只是淡出；enterProgress 保持）
      exitStartedAt = currentTime;
    },

    reset(): void {
      enterStartedAt = new Array(count).fill(null);
      exitStartedAt = null;
      // 不重置 currentTime：保留时序连续性，便于 reset 后立即 enter(now) 续接
    },

    step(dtMs: number): void {
      currentTime += dtMs;
    },

    setCardCount(nextCount: number): void {
      if (!Number.isInteger(nextCount) || nextCount < 0) {
        throw new RangeError(`卡片数必须为非负整数: ${nextCount}`);
      }
      if (nextCount > count) {
        // 扩展：新卡片 enterStartedAt=null（未入场），需再次 enter 才启动
        for (let i = count; i < nextCount; i++) {
          enterStartedAt[i] = null;
        }
      } else if (nextCount < count) {
        // 缩减：截断保留前 N 张状态
        enterStartedAt.length = nextCount;
      }
      count = nextCount;
    },

    getState(index: number): CardAnimationState {
      if (!Number.isInteger(index) || index < 0 || index >= count) {
        throw new RangeError(`卡片 index 越界: ${index}（count=${count}）`);
      }

      // 入场进度
      let enterProgress = 0;
      const startedAt = enterStartedAt[index];
      if (startedAt !== null) {
        if (reducedMotion) {
          // reducedMotion：触发即完成，无缓动
          enterProgress = 1;
        } else {
          const elapsed = currentTime - startedAt;
          if (elapsed >= ENTER_DURATION_MS) {
            enterProgress = 1;
          } else if (elapsed > 0) {
            enterProgress = easeOutSmoothstep(elapsed / ENTER_DURATION_MS);
          }
          // elapsed <= 0：尚未到该卡片的 stagger 延迟，progress=0
        }
      }

      // 退场进度（无 stagger，所有卡片同步）
      let exitProgress = 1;
      if (exitStartedAt !== null) {
        if (reducedMotion) {
          // reducedMotion：触发即完成
          exitProgress = 0;
        } else {
          const elapsed = currentTime - exitStartedAt;
          if (elapsed >= EXIT_DURATION_MS) {
            exitProgress = 0;
          } else if (elapsed > 0) {
            // 1 - easeOut：开始快、收尾慢，符合「收缩消散」的暗房风格
            exitProgress = 1 - easeOutSmoothstep(elapsed / EXIT_DURATION_MS);
          }
          // elapsed <= 0：退场已触发但时间未推进，exitProgress=1（仍完全可见）
        }
      }

      return { enterProgress, exitProgress };
    },
  };
}
