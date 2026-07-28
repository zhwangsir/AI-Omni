/**
 * 暗房配色 registry 测试（M4.4）。
 * 验证点：≥ 3 套配色、id 唯一、每套粒子内容色 ≤ 5、token 完整且为合法色值、
 * 近黑非纯黑底色（禁止纯黑 #000 / 纯白 #fff）、getTheme 查表与未知 id 抛错。
 */
import { describe, expect, it } from "vitest";

import { MAX_COLORS } from "../particles/constraints";
import {
  DEFAULT_THEME_ID,
  THEMES,
  getTheme,
  validateTheme,
  type DarkroomTheme,
} from "./themes";

const HEX_OR_RGBA = /^(#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6}|rgba\([\d\s.,%]+\))$/;

describe("暗房配色 registry", () => {
  it("至少提供 3 套配色", () => {
    expect(THEMES.length).toBeGreaterThanOrEqual(3);
  });

  it("id 全局唯一且非空", () => {
    const ids = THEMES.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) expect(id.trim()).not.toBe("");
  });

  it("每套配色都有中文展示名", () => {
    for (const theme of THEMES) expect(theme.label.trim()).not.toBe("");
  });

  it("每套配色的粒子内容色 ≤ 5 且无重复", () => {
    for (const theme of THEMES) {
      expect(theme.particles.length).toBeGreaterThan(0);
      expect(theme.particles.length).toBeLessThanOrEqual(MAX_COLORS);
      expect(new Set(theme.particles).size).toBe(theme.particles.length);
    }
  });

  it("每套配色 token 完整且为合法色值", () => {
    for (const theme of THEMES) {
      for (const [key, value] of Object.entries(theme.tokens)) {
        expect(value, `${theme.id}.${key}`).toMatch(HEX_OR_RGBA);
      }
      for (const color of theme.particles) {
        expect(color, `${theme.id} particle ${color}`).toMatch(HEX_OR_RGBA);
      }
    }
  });

  it("底色近黑但非纯黑，且禁止纯白背景（暗房红线）", () => {
    for (const theme of THEMES) {
      const abyss = theme.tokens.abyss.toLowerCase();
      expect(abyss).not.toBe("#000");
      expect(abyss).not.toBe("#000000");
      expect(abyss).not.toBe("#fff");
      expect(abyss).not.toBe("#ffffff");
      // 近黑：hex 底色的 RGB 三通道都应很低
      const rgb = parseInt(abyss.slice(1), 16);
      expect((rgb >> 16) & 0xff).toBeLessThanOrEqual(0x24);
      expect((rgb >> 8) & 0xff).toBeLessThanOrEqual(0x24);
      expect(rgb & 0xff).toBeLessThanOrEqual(0x24);
    }
  });

  it("registry 内置主题全部通过 validateTheme 硬校验", () => {
    for (const theme of THEMES) expect(() => validateTheme(theme)).not.toThrow();
  });

  it("默认主题存在", () => {
    expect(THEMES.some((t) => t.id === DEFAULT_THEME_ID)).toBe(true);
  });

  it("getTheme 按 id 查表；未知 id 抛 RangeError", () => {
    expect(getTheme(DEFAULT_THEME_ID).id).toBe(DEFAULT_THEME_ID);
    expect(() => getTheme("no-such-theme")).toThrow(RangeError);
  });
});

describe("validateTheme 硬校验", () => {
  const base: DarkroomTheme = {
    id: "t",
    label: "测试",
    tokens: {
      abyss: "#0b0c0e",
      panel: "rgba(18, 20, 24, 0.88)",
      hairline: "rgba(216, 217, 220, 0.08)",
      fog: "#d8d9dc",
      dim: "#83878f",
      accent: "#c9a86a",
    },
    particles: ["#c9a86a", "#8b93a7"],
  };

  it("粒子调色板超过 5 色抛 RangeError", () => {
    expect(() =>
      validateTheme({ ...base, particles: ["#1", "#2", "#3", "#4", "#5", "#6"] }),
    ).toThrow(RangeError);
  });

  it("粒子调色板为空抛 RangeError", () => {
    expect(() => validateTheme({ ...base, particles: [] })).toThrow(RangeError);
  });

  it("缺少必需 token 抛 RangeError", () => {
    const tokens = { ...base.tokens } as Record<string, string>;
    delete tokens["accent"];
    expect(() =>
      validateTheme({ ...base, tokens: tokens as unknown as DarkroomTheme["tokens"] }),
    ).toThrow(RangeError);
  });

  it("非法色值抛 RangeError", () => {
    expect(() =>
      validateTheme({ ...base, tokens: { ...base.tokens, fog: "not-a-color" } }),
    ).toThrow(RangeError);
  });
});
