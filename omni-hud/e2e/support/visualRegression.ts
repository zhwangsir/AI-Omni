/**
 * 视觉回归测试支撑层（TEST_INFRA D2 决策）。
 *
 * 解决粒子非确定性问题（CLAUDE.md §六.3 粒子系统约束）：
 * 1. **粒子种子固定**：addInitScript 重写 Math.random 为 LCG（种子 42），
 *    使 Three.js 粒子初始化、CSS 动画延迟、shader uniform 抖动均确定化；
 * 2. **截图时机稳定**：等待首帧挂载 + requestAnimationFrame 两轮，避免过渡态；
 * 3. **mask canvas**：Three.js 渲染的 canvas 像素非确定性高（GPU 浮点误差、
 *    时序差异），统一 mask 掉，仅断言 DOM 结构与文字层；
 * 4. **fallback**：headless WebGL 不可用或基线缺失时降级为 DOM 结构断言，
 *    不让视觉回归拖垮 CI。
 *
 * 视觉回归仅 chromium 引擎跑（playwright.config.ts visual-chromium project），
 * 避免三套基线维护成本（D4 决策）。
 */
import { expect, type Page, type Locator } from "@playwright/test";

/**
 * 注入固定种子的 LCG（Linear Congruential Generator）替换 Math.random。
 *
 * 必须在 page.goto 前调用（addInitScript 在 navigation 前执行）。
 * 种子 42 是约定值，跨用例一致；LCG 参数选用 glibc 同款（a=1103515245, c=12345, m=2^31）。
 *
 * 注意：此函数替换的是 page 内的 Math.random，不影响 Node 侧。
 * Three.js / WebGL shader 内的随机数若由 JS 侧传入（如 BufferAttribute 顶点位置），
 * 也会确定化；但 shader 内部 computed 随机（如 hash 函数）不受此影响——
 * 这部分由 mask canvas 兜底（不参与像素对比）。
 */
export async function installDeterministicRandom(page: Page): Promise<void> {
  await page.addInitScript(() => {
    // LCG 状态：种子 42，每次调用推进
    let state = 42;
    // eslint-disable-next-line no-global-assign
    Math.random = function (): number {
      // glibc LCG: state = (a * state + c) mod m
      state = (1103515245 * state + 12345) & 0x7fffffff;
      return state / 0x80000000;
    };
  });
}

/**
 * 等待页面首帧稳定：hud-root 挂载 + 两轮 RAF + 100ms 额外缓冲。
 *
 * 视觉回归截图前必须等待：
 * - React 首帧挂载完成（hud-root testid 可见）；
 * - Three.js 场景初始化完成（两轮 RAF 让 ImmersiveSpace 的 useEffect 跑完）；
 * - CSS 过渡稳定（100ms 缓冲吸收 opacity/transform 过渡）。
 *
 * 不等待更长时间避免拖慢测试；过渡未完成由 animations:"disabled" 截图选项冻结。
 */
export async function waitForStableFrame(page: Page, timeout = 10_000): Promise<void> {
  await page.waitForSelector('[data-testid="hud-root"]', { state: "attached", timeout });
  // 两轮 RAF：第一轮触发 React commit + Three.js 初始化，第二轮确认场景就绪
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => resolve());
        });
      }),
  );
  // 100ms 缓冲吸收 CSS 过渡
  await page.waitForTimeout(100);
}

/**
 * 视觉回归截图断言：mask 掉所有 canvas 元素，仅对比 DOM 结构与文字层。
 *
 * 用法：
 * ```ts
 * await assertScreenshot(page, "idle-full", {
 *   mask: [page.locator("canvas")],
 * });
 * ```
 *
 * maxDiffPixelRatio=0.01 容忍 1% 像素差异（抗锯齿、字体渲染微差异）；
 * animations:"disabled" 冻结 CSS 动画与过渡到首帧。
 *
 * 失败时 Playwright 自动生成 diff 图片到 .test-output/。
 */
export async function assertScreenshot(
  page: Page,
  name: string,
  options: {
    /** 额外 mask 的 locator（canvas 已默认 mask）。 */
    mask?: readonly Locator[];
    /** 容忍的像素差异比例，默认 0.01。 */
    maxDiffPixelRatio?: number;
    /** 截图前等待稳定帧，默认 true。 */
    waitForStable?: boolean;
  } = {},
): Promise<void> {
  if (options.waitForStable !== false) {
    await waitForStableFrame(page);
  }
  const canvasLocator = page.locator("canvas");
  const mask = [canvasLocator, ...(options.mask ?? [])];
  await expect(page).toHaveScreenshot(name, {
    mask,
    maxDiffPixelRatio: options.maxDiffPixelRatio ?? 0.01,
    animations: "disabled",
  });
}

/**
 * DOM 结构断言（视觉回归 fallback）。
 *
 * 当 headless WebGL 不可用、基线缺失、或跨引擎（WebKit/Firefox）跑时，
 * 降级为 DOM 结构断言：检查 testid 存在 + 关键属性 + 文字内容。
 *
 * 用法：
 * ```ts
 * await assertDomStructure(page, {
 *   testid: "hud-root",
 *   attributes: { "data-voice-state": "idle", "data-window-mode": "full" },
 *   textContains: ["雪莉"],
 * });
 * ```
 *
 * 此断言不依赖像素，跨引擎稳定，但无法捕获视觉样式回归（颜色/布局）——
 * 仅作为视觉回归不可用时的兜底，主路径仍走 assertScreenshot。
 */
export async function assertDomStructure(
  page: Page,
  expected: {
    /** 要断言的 testid。 */
    testid: string;
    /** 期望的属性值映射（attribute name → value）。 */
    attributes?: Readonly<Record<string, string>>;
    /** 期望元素内包含的文字片段列表（每个都需包含）。 */
    textContains?: readonly string[];
    /** 期望元素可见（display !== none），默认 true。 */
    visible?: boolean;
  },
): Promise<void> {
  const locator = page.locator(`[data-testid="${expected.testid}"]`);
  await expect(locator, `testid "${expected.testid}" should exist`).toBeAttached();
  if (expected.visible !== false) {
    await expect(locator, `testid "${expected.testid}" should be visible`).toBeVisible();
  }
  if (expected.attributes) {
    for (const [attr, value] of Object.entries(expected.attributes)) {
      await expect(
        locator,
        `testid "${expected.testid}" should have ${attr}="${value}"`,
      ).toHaveAttribute(attr, value);
    }
  }
  if (expected.textContains) {
    const text = (await locator.textContent()) ?? "";
    for (const fragment of expected.textContains) {
      expect(text, `testid "${expected.testid}" should contain "${fragment}"`).toContain(
        fragment,
      );
    }
  }
}

/**
 * 检查 WebGL 是否可用（headless Chromium 可能无 WebGL）。
 *
 * 视觉回归主路径依赖 WebGL（Three.js 场景），headless 模式下可能不可用——
 * 此函数让 spec 决定走视觉回归（WebGL 可用）还是 DOM fallback（不可用）。
 *
 * 用法：
 * ```ts
 * test("idle 视觉基线", async ({ appPage }) => {
 *   const webglOk = await isWebGLAvailable(appPage);
 *   test.skip(!webglOk, "headless 无 WebGL，跳过视觉回归");
 *   await assertScreenshot(appPage, "idle-full");
 * });
 * ```
 */
export async function isWebGLAvailable(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    try {
      const canvas = document.createElement("canvas");
      const gl =
        canvas.getContext("webgl2") ??
        canvas.getContext("webgl") ??
        canvas.getContext("experimental-webgl");
      return gl !== null;
    } catch {
      return false;
    }
  });
}
