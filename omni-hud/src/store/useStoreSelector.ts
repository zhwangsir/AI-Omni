/**
 * useStoreSelector：精确订阅 store 字段的 hook，避免全量重渲染。
 *
 * 与 useSyncExternalStore(store.subscribe, store.getState) 不同——
 * selector 只提取组件关心的切片，使用 Object.is 浅比较，切片未变化时不触发重渲染。
 *
 * 设计原则：
 * - selector 必须是纯函数，不应产生新引用（对象/数组返回需 memoize 或用多个 selector）；
 * - 默认 Object.is 比较；对于返回对象/数组的场景，使用第二个参数 isEqual 自定义比较；
 * - 与现有 store 契约完全兼容（getState + subscribe），无需修改 store 实现。
 */
import { useSyncExternalStore, useRef, useCallback } from "react";

/** 最小 store 契约：getState 返回全量快照，subscribe 返回取消订阅函数。 */
export interface StoreLike<TState> {
  getState: () => TState;
  subscribe: (listener: () => void) => () => void;
}

/** 默认相等比较：Object.is（与 React useSyncExternalStore 默认行为一致）。 */
function defaultIsEqual<T>(a: T, b: T): boolean {
  return Object.is(a, b);
}

/**
 * 精确订阅 store 切片。
 *
 * @param store 状态仓库（必须稳定引用，通常用 useMemo 或模块单例）
 * @param selector 从全量 state 提取组件需要的切片
 * @param isEqual 可选自定义相等比较，返回 true 时跳过重渲染
 */
export function useStoreSelector<TState, TSelected>(
  store: StoreLike<TState>,
  selector: (state: TState) => TSelected,
  isEqual: (a: TSelected, b: TSelected) => boolean = defaultIsEqual,
): TSelected {
  const selectorRef = useRef(selector);
  selectorRef.current = selector;
  const isEqualRef = useRef(isEqual);
  isEqualRef.current = isEqual;

  const getSnapshot = useCallback(() => {
    return selectorRef.current(store.getState());
  }, [store]);

  const lastSnapshotRef = useRef<TSelected | undefined>(undefined);

  const getCachedSnapshot = useCallback(() => {
    const next = getSnapshot();
    if (lastSnapshotRef.current !== undefined && isEqualRef.current(lastSnapshotRef.current, next)) {
      return lastSnapshotRef.current;
    }
    lastSnapshotRef.current = next;
    return next;
  }, [getSnapshot]);

  return useSyncExternalStore(store.subscribe, getCachedSnapshot, getCachedSnapshot);
}

/**
 * 便捷 hook：订阅多个字段，返回元组。
 * 避免 selector 返回新对象引用导致的无限重渲染。
 */
export function useStoreSelectors<TState, const TSelectors extends ReadonlyArray<(state: TState) => unknown>>(
  store: StoreLike<TState>,
  ...selectors: TSelectors
): { [K in keyof TSelectors]: TSelectors[K] extends (state: TState) => infer R ? R : never } {
  return selectors.map((selector) => useStoreSelector(store, selector)) as ReturnType<typeof useStoreSelectors<TState, TSelectors>>;
}
