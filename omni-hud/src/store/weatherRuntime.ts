/**
 * weatherStore 运行时单例 + Space 桥接（M23 前端接线）。
 *
 * 职责：
 * 1. 暴露 ``getWeatherStore`` 进程内单例（与 lyricsRuntime / musicRuntime 同款），
 *    供 App.tsx / MiniBar / FieldStage 共享同一份 weatherStore 实例；
 * 2. ``bindWeatherToSpace(space, weatherStore)`` 把 weatherStore.mood 变化同步到
 *    FieldStage 的 setWeatherMood：
 *    - mood 变化（非 null）→ ``space.setWeatherMood(mood)`` 应用视觉联动；
 *    - mood 变 null（拉取失败 / 清除）→ ``space.setWeatherMood(null)`` 恢复默认；
 *    - 相同 mood（值相等）不重复推送（去重，避免 refresh 重复 IPC 触发场景重建）。
 *
 * 单向同步：weatherStore 只读，不反向写。退订在组件卸载 / 测试 teardown
 * 时由返回的清理函数执行。
 */
import type { WeatherMood } from "../data/sources";
import { createWeatherStore, type WeatherStore } from "./weatherStore";

let singleton: WeatherStore | null = null;

/** 获取进程内 weatherStore 单例（首次调用懒构造）。 */
export function getWeatherStore(): WeatherStore {
  singleton ??= createWeatherStore();
  return singleton;
}

/**
 * ``space.setWeatherMood`` 最小契约（真实 Space 与测试 fake 均满足）。
 * 仅声明被本模块调用的方法，避免引入完整 Space 类型耦合。
 */
export interface WeatherSpaceTarget {
  /** 应用 / 清除天气情绪（null = 恢复默认 AmbientLight + 粒子参数）。 */
  setWeatherMood(mood: WeatherMood | null): void;
}

/**
 * 深度值比较两个 WeatherMood（null 与非 null 不等）。
 *
 * normalizeWeatherMood 每次 refresh 都会创建新对象，引用比较无意义；
 * 改用 JSON.stringify 做值比较——mood 对象小（≤7 字段），序列化成本可忽略。
 */
function moodEqual(a: WeatherMood | null, b: WeatherMood | null): boolean {
  if (a === b) return true;
  if (a === null || b === null) return false;
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * 把 weatherStore.mood 变化同步到 Space.setWeatherMood。
 *
 * 返回解绑函数（组件卸载 / 测试 teardown 调用）。幂等：多次绑定同一对 store
 * 会产生多个独立订阅，生产环境只绑定一次（App.tsx 挂载时）。
 *
 * 首次绑定即推送当前 mood（若 store 已有缓存 mood，立即应用到场景）。
 * 后续 mood 值未变（refresh 拉到相同数据）不重复推送，避免场景重建抖动。
 */
export function bindWeatherToSpace(
  space: WeatherSpaceTarget,
  weatherStore: WeatherStore = getWeatherStore(),
): () => void {
  let lastMood: WeatherMood | null = weatherStore.getState().mood;
  let lastError: string | null = weatherStore.getState().error;

  const push = (): void => {
    const state = weatherStore.getState();
    const moodChanged = !moodEqual(state.mood, lastMood);
    const errorRecovered = lastError !== null && state.error === null;
    lastMood = state.mood;
    lastError = state.error;
    if (moodChanged || errorRecovered) {
      space.setWeatherMood(state.mood);
    }
  };

  // 首次推送：把当前 mood 应用到场景（若已有缓存）
  space.setWeatherMood(lastMood);
  const unsubscribe = weatherStore.subscribe(push);
  return () => {
    unsubscribe();
    lastMood = null;
    lastError = null;
  };
}
