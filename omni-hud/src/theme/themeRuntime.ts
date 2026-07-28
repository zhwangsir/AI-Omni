/**
 * 配色 store 运行时单例（M4.4）：真实 localStorage + document.documentElement。
 * 独立成模块便于组件测试注入 fake store，与 statusRuntime 同款模式。
 */
import { createThemeStore, type StorageLike, type ThemeStore } from "./themeStore";

function safeLocalStorage(): StorageLike | null {
  try {
    if (typeof window === "undefined" || !window.localStorage) return null;
    return window.localStorage;
  } catch {
    return null; // 隐私模式下访问 localStorage 本身就可能抛 SecurityError
  }
}

let singleton: ThemeStore | null = null;

export function getThemeStore(): ThemeStore {
  singleton ??= createThemeStore({
    storage: safeLocalStorage(),
    root: typeof document !== "undefined" ? document.documentElement : null,
  });
  return singleton;
}
