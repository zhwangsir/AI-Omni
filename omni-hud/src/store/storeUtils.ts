/**
 * 轻量订阅式 store 工具函数。
 *
 * 统一各 store 的 getState / subscribe / setState 模式，
 * 与现有 hudStore / musicStore / statusStore 等的手写实现兼容。
 */
export interface Store<T> {
  getState: () => T;
  subscribe: (listener: () => void) => () => void;
  setState: (partial: Partial<T> | ((prev: T) => T)) => void;
}

export function createStore<T>(initialState: T): Store<T> {
  let state: T = initialState;
  const listeners = new Set<() => void>();

  const emit = (): void => {
    for (const listener of listeners) listener();
  };

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    setState(partial) {
      if (typeof partial === "function") {
        state = (partial as (prev: T) => T)(state);
      } else {
        state = { ...state, ...partial };
      }
      emit();
    },
  };
}
