/**
 * themeStore 测试（M4.4）：配色切换 + CSS 变量整体换肤 + localStorage 持久化。
 * 全 fake：fake storage（内存 Map）+ fake root 元素（记录 setProperty 调用），
 * 不依赖真实 document/localStorage。
 */
import { describe, expect, it, vi } from "vitest";

import { THEME_STORAGE_KEY, createThemeStore } from "./themeStore";
import { DEFAULT_THEME_ID, THEMES, getTheme } from "./themes";

function makeStorage(initial?: Record<string, string>) {
  const map = new Map(Object.entries(initial ?? {}));
  return {
    getItem: vi.fn((key: string) => map.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      map.set(key, value);
    }),
    removeItem: vi.fn((key: string) => {
      map.delete(key);
    }),
    map,
  };
}

function makeRoot() {
  const calls: Array<[string, string]> = [];
  return {
    calls,
    style: {
      setProperty: (name: string, value: string) => {
        calls.push([name, value]);
      },
    },
  };
}

describe("themeStore 配色切换", () => {
  it("无持久化记录时落在默认主题", () => {
    const store = createThemeStore({ storage: makeStorage(), root: makeRoot() });
    expect(store.getState().themeId).toBe(DEFAULT_THEME_ID);
  });

  it("从持久化记录恢复主题", () => {
    const other = THEMES.find((t) => t.id !== DEFAULT_THEME_ID)!;
    const store = createThemeStore({
      storage: makeStorage({ [THEME_STORAGE_KEY]: other.id }),
      root: makeRoot(),
    });
    expect(store.getState().themeId).toBe(other.id);
  });

  it("持久化记录是无效 id 时回退默认主题", () => {
    const store = createThemeStore({
      storage: makeStorage({ [THEME_STORAGE_KEY]: "garbage" }),
      root: makeRoot(),
    });
    expect(store.getState().themeId).toBe(DEFAULT_THEME_ID);
  });

  it("setTheme 切换主题并写入持久化", () => {
    const storage = makeStorage();
    const store = createThemeStore({ storage, root: makeRoot() });
    const target = THEMES[1]!;
    store.setTheme(target.id);
    expect(store.getState().themeId).toBe(target.id);
    expect(storage.setItem).toHaveBeenCalledWith(THEME_STORAGE_KEY, target.id);
  });

  it("setTheme 对未知 id 抛 RangeError 且不写持久化", () => {
    const storage = makeStorage();
    const store = createThemeStore({ storage, root: makeRoot() });
    expect(() => store.setTheme("no-such-theme")).toThrow(RangeError);
    expect(storage.setItem).not.toHaveBeenCalled();
  });

  it("切换主题时把全部 token 写入 CSS 变量（整体换肤）", () => {
    const root = makeRoot();
    const store = createThemeStore({ storage: makeStorage(), root });
    const target = THEMES[1]!;
    store.setTheme(target.id);
    const applied = new Map(root.calls);
    expect(applied.get("--omni-abyss")).toBe(target.tokens.abyss);
    expect(applied.get("--omni-panel")).toBe(target.tokens.panel);
    expect(applied.get("--omni-fog")).toBe(target.tokens.fog);
    expect(applied.get("--omni-dim")).toBe(target.tokens.dim);
    expect(applied.get("--omni-accent")).toBe(target.tokens.accent);
    expect(applied.get("--omni-hairline")).toBe(target.tokens.hairline);
  });

  it("切换主题时同步粒子调色板 CSS 变量（--omni-particle-1..5）", () => {
    const root = makeRoot();
    const store = createThemeStore({ storage: makeStorage(), root });
    const target = THEMES[2]!;
    store.setTheme(target.id);
    const applied = new Map(root.calls);
    target.particles.forEach((color, i) => {
      expect(applied.get(`--omni-particle-${i + 1}`)).toBe(color);
    });
  });

  it("订阅者在切换时收到通知，重复切同一主题不重复通知", () => {
    const store = createThemeStore({ storage: makeStorage(), root: makeRoot() });
    const listener = vi.fn();
    const un = store.subscribe(listener);
    store.setTheme(THEMES[1]!.id);
    store.setTheme(THEMES[1]!.id);
    expect(listener).toHaveBeenCalledTimes(1);
    un();
    store.setTheme(THEMES[2]!.id);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("storage 不可用（抛异常）时仍能切换主题，只是不持久化", () => {
    const broken = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
    };
    const store = createThemeStore({ storage: broken, root: makeRoot() });
    expect(store.getState().themeId).toBe(DEFAULT_THEME_ID);
    store.setTheme(THEMES[1]!.id);
    expect(store.getState().themeId).toBe(THEMES[1]!.id);
  });

  it("cycleTheme 按 registry 顺序循环切换并回绕", () => {
    const store = createThemeStore({ storage: makeStorage(), root: makeRoot() });
    expect(store.getState().themeId).toBe(THEMES[0]!.id);
    store.cycleTheme();
    expect(store.getState().themeId).toBe(THEMES[1]!.id);
    for (let i = 0; i < THEMES.length; i++) store.cycleTheme();
    expect(store.getState().themeId).toBe(THEMES[1]!.id);
  });

  it("getState 返回的 theme 与 registry 对象一致", () => {
    const store = createThemeStore({ storage: makeStorage(), root: makeRoot() });
    expect(store.getState().theme).toBe(getTheme(DEFAULT_THEME_ID));
  });
});
