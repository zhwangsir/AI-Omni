/**
 * 配色切换 store（M4.4，框架无关订阅模式，与 hudStore/statusStore 同款）。
 * setTheme/cycleTheme → 把整套 token 写入根元素 CSS 变量（整体换肤）
 * 并持久化到 storage；storage 不可用（隐私模式抛异常）时静默降级为不持久化。
 */
import { DEFAULT_THEME_ID, THEMES, getTheme, type DarkroomTheme } from "./themes";

export const THEME_STORAGE_KEY = "omni-hud.theme";

export interface StorageLike {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
}

export interface CssVarTarget {
  style: { setProperty: (name: string, value: string) => void };
}

export interface ThemeState {
  readonly themeId: string;
  readonly theme: DarkroomTheme;
}

export interface ThemeStoreDeps {
  readonly storage?: StorageLike | null;
  readonly root?: CssVarTarget | null;
}

export interface ThemeStore {
  getState: () => ThemeState;
  subscribe: (listener: () => void) => () => void;
  /** 切换主题；未知 id 抛 RangeError。 */
  setTheme: (id: string) => void;
  /** 按 registry 顺序循环切换（HUD 单按钮交互）。 */
  cycleTheme: () => void;
}

/** 主题 token → CSS 变量名映射。 */
const TOKEN_VARS: ReadonlyArray<[keyof DarkroomTheme["tokens"], string]> = [
  ["abyss", "--omni-abyss"],
  ["panel", "--omni-panel"],
  ["hairline", "--omni-hairline"],
  ["fog", "--omni-fog"],
  ["dim", "--omni-dim"],
  ["accent", "--omni-accent"],
];

/** 粒子 CSS 变量固定写满 5 个：色板不足 5 色时循环复用，避免残留上一主题的颜色。 */
const PARTICLE_VAR_COUNT = 5;

export function createThemeStore(deps: ThemeStoreDeps): ThemeStore {
  const storage = deps.storage ?? null;
  const root = deps.root ?? null;
  const listeners = new Set<() => void>();

  const readInitialId = (): string => {
    if (!storage) return DEFAULT_THEME_ID;
    try {
      const saved = storage.getItem(THEME_STORAGE_KEY);
      return saved !== null ? getTheme(saved).id : DEFAULT_THEME_ID;
    } catch {
      return DEFAULT_THEME_ID; // 无效 id 或 storage 抛异常 → 回退默认
    }
  };

  const initialTheme = getTheme(readInitialId());
  let state: ThemeState = { themeId: initialTheme.id, theme: initialTheme };

  const apply = (theme: DarkroomTheme): void => {
    if (!root) return;
    for (const [key, varName] of TOKEN_VARS) {
      root.style.setProperty(varName, theme.tokens[key]);
    }
    for (let i = 0; i < PARTICLE_VAR_COUNT; i++) {
      const color = theme.particles[i % theme.particles.length]!;
      root.style.setProperty(`--omni-particle-${i + 1}`, color);
    }
  };

  const persist = (id: string): void => {
    if (!storage) return;
    try {
      storage.setItem(THEME_STORAGE_KEY, id);
    } catch {
      // 隐私模式等场景 storage 写失败：静默降级，不影响切换。
    }
  };

  const emit = (): void => {
    for (const listener of listeners) listener();
  };

  // 启动即把当前主题写入 CSS 变量，保证首帧皮肤一致。
  apply(state.theme);

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    setTheme(id) {
      const theme = getTheme(id); // 未知 id 在此抛 RangeError，不落状态不写持久化
      if (state.themeId === theme.id) return;
      state = { themeId: theme.id, theme };
      apply(theme);
      persist(theme.id);
      emit();
    },
    cycleTheme() {
      const index = THEMES.findIndex((t) => t.id === state.themeId);
      const next = THEMES[(index + 1) % THEMES.length]!;
      const theme = getTheme(next.id);
      state = { themeId: theme.id, theme };
      apply(theme);
      persist(theme.id);
      emit();
    },
  };
}
