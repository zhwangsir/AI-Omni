/**
 * themeBridge 测试（M5.1）：themeStore 主题 → 3D 场景参数映射
 * （雾色 / 色板槽位 / bloom 微调），以及主题切换的 260ms 平滑过渡插值。
 * 纯逻辑：颜色用 0..1 浮点三元组表示，不依赖 three。
 */
import { describe, expect, it } from "vitest";

import { THEMES, getTheme } from "../theme/themes";
import {
  BLOOM_MAX,
  BLOOM_MIN,
  PALETTE_SLOTS,
  THEME_TRANSITION_MS,
  createThemeTransition,
  hexToRgb,
  lerpSceneParams,
  themeToSceneParams,
  type Rgb,
  type SceneParams,
} from "./themeBridge";

/** 逐通道断言两个 rgb 接近。 */
function expectRgbClose(actual: Rgb, expected: Rgb, precision = 3): void {
  expect(actual[0]).toBeCloseTo(expected[0], precision);
  expect(actual[1]).toBeCloseTo(expected[1], precision);
  expect(actual[2]).toBeCloseTo(expected[2], precision);
}

describe("hexToRgb 颜色解析", () => {
  it("解析 #rrggbb", () => {
    expectRgbClose(hexToRgb("#c9a86a"), [201 / 255, 168 / 255, 106 / 255]);
  });

  it("解析 #rgb 短形式", () => {
    expectRgbClose(hexToRgb("#fff"), [1, 1, 1]);
    expectRgbClose(hexToRgb("#0a0"), [0, 0xaa / 255, 0]);
  });

  it("解析 rgba()（丢弃 alpha，取 rgb 通道）", () => {
    expectRgbClose(hexToRgb("rgba(18, 20, 24, 0.88)"), [18 / 255, 20 / 255, 24 / 255]);
  });

  it("非法颜色字符串抛 RangeError", () => {
    expect(() => hexToRgb("red")).toThrow(RangeError);
    expect(() => hexToRgb("#12345")).toThrow(RangeError);
    expect(() => hexToRgb("")).toThrow(RangeError);
  });
});

describe("themeToSceneParams 主题映射", () => {
  it("每套内置主题都能映射出完整场景参数", () => {
    for (const theme of THEMES) {
      const params = themeToSceneParams(theme);
      expect(params.palette).toHaveLength(PALETTE_SLOTS);
      expect(Number.isFinite(params.bloomStrength)).toBe(true);
      expect(Number.isFinite(params.vignetteStrength)).toBe(true);
      expect(Number.isFinite(params.grainOpacity)).toBe(true);
    }
  });

  it("雾色取自主题 abyss 底色", () => {
    const theme = getTheme("developer-amber");
    const params = themeToSceneParams(theme);
    expectRgbClose(params.fogColor, hexToRgb(theme.tokens.abyss));
  });

  it("色板槽位写满 6 格，主题色不足时循环复用", () => {
    // silver-gray 只有 4 个粒子色 → 第 5 格循环回第 1 色
    const theme = getTheme("silver-gray");
    expect(theme.particles).toHaveLength(4);
    const params = themeToSceneParams(theme);
    expectRgbClose(params.palette[0]!, hexToRgb(theme.particles[0]!));
    expectRgbClose(params.palette[4]!, hexToRgb(theme.particles[0]!));
    expectRgbClose(params.palette[5]!, hexToRgb(theme.particles[1]!));
  });

  it("bloom 强度克制地落在 [0.3, 0.5] 区间内，且随主题有微调", () => {
    const strengths = THEMES.map((theme) => themeToSceneParams(theme).bloomStrength);
    for (const strength of strengths) {
      expect(strength).toBeGreaterThanOrEqual(BLOOM_MIN);
      expect(strength).toBeLessThanOrEqual(BLOOM_MAX);
    }
    // 三套主题的强调色亮度不同 → bloom 微调不应全部相同
    expect(new Set(strengths).size).toBeGreaterThan(1);
  });

  it("bloom 阈值高（≥0.7），避免全屏泛光", () => {
    for (const theme of THEMES) {
      expect(themeToSceneParams(theme).bloomThreshold).toBeGreaterThanOrEqual(0.7);
    }
  });
});

describe("lerpSceneParams 过渡插值", () => {
  const amber = themeToSceneParams(getTheme("developer-amber"));
  const red = themeToSceneParams(getTheme("safelight-red"));

  it("t=0 取起点，t=1 取终点", () => {
    expect(lerpSceneParams(amber, red, 0)).toEqual(amber);
    expect(lerpSceneParams(amber, red, 1)).toEqual(red);
  });

  it("t=0.5 时雾色与 bloom 强度都是中点", () => {
    const mid = lerpSceneParams(amber, red, 0.5);
    expectRgbClose(mid.fogColor, [
      (amber.fogColor[0] + red.fogColor[0]) / 2,
      (amber.fogColor[1] + red.fogColor[1]) / 2,
      (amber.fogColor[2] + red.fogColor[2]) / 2,
    ]);
    expect(mid.bloomStrength).toBeCloseTo((amber.bloomStrength + red.bloomStrength) / 2, 5);
    expectRgbClose(mid.palette[0]!, [
      (amber.palette[0]![0] + red.palette[0]![0]) / 2,
      (amber.palette[0]![1] + red.palette[0]![1]) / 2,
      (amber.palette[0]![2] + red.palette[0]![2]) / 2,
    ]);
  });

  it("t 越界时被钳制到 [0, 1]", () => {
    expect(lerpSceneParams(amber, red, -0.5)).toEqual(amber);
    expect(lerpSceneParams(amber, red, 1.5)).toEqual(red);
  });
});

describe("createThemeTransition 平滑过渡", () => {
  const amber = themeToSceneParams(getTheme("developer-amber"));
  const red: SceneParams = themeToSceneParams(getTheme("safelight-red"));

  it("过渡时长为 260ms，采样点线性推进", () => {
    const transition = createThemeTransition(amber);
    transition.start(red, 1000);
    const atStart = transition.sample(1000);
    expect(atStart.done).toBe(false);
    expectRgbClose(atStart.params.fogColor, amber.fogColor);
    const atMid = transition.sample(1000 + THEME_TRANSITION_MS / 2);
    expect(atMid.done).toBe(false);
    expectRgbClose(atMid.params.fogColor, [
      (amber.fogColor[0] + red.fogColor[0]) / 2,
      (amber.fogColor[1] + red.fogColor[1]) / 2,
      (amber.fogColor[2] + red.fogColor[2]) / 2,
    ]);
    const atEnd = transition.sample(1000 + THEME_TRANSITION_MS);
    expect(atEnd.done).toBe(true);
    expectRgbClose(atEnd.params.fogColor, red.fogColor);
  });

  it("过渡结束后保持在目标参数", () => {
    const transition = createThemeTransition(amber);
    transition.start(red, 0);
    transition.sample(THEME_TRANSITION_MS);
    const later = transition.sample(99999);
    expect(later.done).toBe(true);
    expect(later.params).toEqual(red);
  });

  it("过渡中途重定向：从当前插值点出发而非跳回起点", () => {
    const silver = themeToSceneParams(getTheme("silver-gray"));
    const transition = createThemeTransition(amber);
    transition.start(red, 1000);
    const mid = transition.sample(1000 + THEME_TRANSITION_MS / 2).params;
    transition.start(silver, 2000);
    const restart = transition.sample(2000);
    // 新过渡的 t=0 采样应等于中途插值点，实现无跳变重定向
    expect(restart.params).toEqual(mid);
  });

  it("finish 立即跳到目标参数（reduced-motion 静态帧用）", () => {
    const transition = createThemeTransition(amber);
    transition.start(red, 500);
    const jumped = transition.finish();
    expect(jumped).toEqual(red);
    expect(transition.sample(500).done).toBe(true);
    expect(transition.current()).toEqual(red);
  });

  it("非法过渡时长抛 RangeError", () => {
    expect(() => createThemeTransition(amber, 0)).toThrow(RangeError);
  });
});
