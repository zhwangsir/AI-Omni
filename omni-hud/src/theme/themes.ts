/**
 * Film Atelier 暗房配色 registry（M4.4）。
 * ≥ 3 套暗房配色：显影琥珀 / 银盐冷灰 / 暗房安全灯红。
 * 每套配色 = 6 个界面 token + 粒子内容色板（≤ 5 色，硬约束）。
 * 模块加载即对全部内置主题过硬校验，非法配色直接拒绝启动。
 */
import { MAX_COLORS } from "../particles/constraints";

export interface ThemeTokens {
  /** 底色：近黑非纯黑的显影液底。 */
  readonly abyss: string;
  /** 面板背景（高不透明度，禁磨砂玻璃）。 */
  readonly panel: string;
  /** 发丝描边。 */
  readonly hairline: string;
  /** 主前景（文字）。 */
  readonly fog: string;
  /** 次前景（弱信息）。 */
  readonly dim: string;
  /** 强调色（安全灯）。 */
  readonly accent: string;
}

export interface DarkroomTheme {
  readonly id: string;
  /** 中文展示名。 */
  readonly label: string;
  readonly tokens: ThemeTokens;
  /** 粒子内容色板（≤ 5 色）。 */
  readonly particles: readonly string[];
}

const REQUIRED_TOKENS = ["abyss", "panel", "hairline", "fog", "dim", "accent"] as const;
const COLOR_RE = /^(#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6}|rgba\([\d\s.,%]+\))$/;

/** 单主题硬校验：token 完整合法 + 粒子色板 1..5 色。 */
export function validateTheme(theme: DarkroomTheme): void {
  for (const key of REQUIRED_TOKENS) {
    const value = theme.tokens[key];
    if (typeof value !== "string" || !COLOR_RE.test(value)) {
      throw new RangeError(`主题 ${theme.id} 的 token ${key} 非法: ${String(value)}`);
    }
  }
  if (theme.particles.length === 0 || theme.particles.length > MAX_COLORS) {
    throw new RangeError(
      `主题 ${theme.id} 粒子色板 ${theme.particles.length} 色，违反 1..${MAX_COLORS} 色约束`,
    );
  }
  for (const color of theme.particles) {
    if (!COLOR_RE.test(color)) {
      throw new RangeError(`主题 ${theme.id} 粒子颜色非法: ${color}`);
    }
  }
}

/** 显影琥珀（默认）：经典暗房安全灯，克制的琥珀暖调。 */
const DEVELOPER_AMBER: DarkroomTheme = {
  id: "developer-amber",
  label: "显影琥珀",
  tokens: {
    abyss: "#0b0c0e",
    panel: "rgba(18, 20, 24, 0.88)",
    hairline: "rgba(216, 217, 220, 0.08)",
    fog: "#d8d9dc",
    dim: "#83878f",
    accent: "#c9a86a",
  },
  particles: ["#c9a86a", "#8b93a7", "#d8d9dc", "#5d6678", "#b04a3a"],
};

/** 银盐冷灰：黑白相纸的冷银影调。 */
const SILVER_GRAY: DarkroomTheme = {
  id: "silver-gray",
  label: "银盐冷灰",
  tokens: {
    abyss: "#0a0c0e",
    panel: "rgba(15, 18, 22, 0.88)",
    hairline: "rgba(200, 208, 220, 0.08)",
    fog: "#cfd4db",
    dim: "#7d8590",
    accent: "#a8b8c8",
  },
  particles: ["#a8b8c8", "#7d8590", "#cfd4db", "#55606e"],
};

/** 暗房安全灯红：相纸冲洗时的安全灯红晕。 */
const SAFELIGHT_RED: DarkroomTheme = {
  id: "safelight-red",
  label: "安全灯红",
  tokens: {
    abyss: "#0d0a09",
    panel: "rgba(22, 15, 13, 0.88)",
    hairline: "rgba(220, 200, 190, 0.08)",
    fog: "#ddd2cc",
    dim: "#8f8078",
    accent: "#b04a3a",
  },
  particles: ["#b04a3a", "#8f8078", "#ddd2cc", "#5d4a42"],
};

export const THEMES: readonly DarkroomTheme[] = [DEVELOPER_AMBER, SILVER_GRAY, SAFELIGHT_RED];

// 模块加载即硬校验：任何内置主题违反约束直接拒绝启动。
for (const theme of THEMES) validateTheme(theme);

export const DEFAULT_THEME_ID = DEVELOPER_AMBER.id;

/** 按 id 查表；未知 id 抛 RangeError。 */
export function getTheme(id: string): DarkroomTheme {
  const theme = THEMES.find((t) => t.id === id);
  if (!theme) throw new RangeError(`未知配色主题: ${id}`);
  return theme;
}
