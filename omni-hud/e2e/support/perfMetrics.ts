/**
 * 性能指标采集支撑层（TEST_INFRA D3 决策）。
 *
 * 三类指标：
 * 1. **LCP（Largest Contentful Paint）**：经 PerformanceObserver 监听
 *    largest-contentful-paint 事件，反映首屏渲染速度；
 * 2. **帧率**：requestAnimationFrame 计数，反映动画流畅度（idle ≥ 55fps / speaking ≥ 30fps）；
 * 3. **粒子数**：经 page.evaluate 读 Space 句柄的 quality.particleCount，
 *    反映 CLAUDE.md §六.3 粒子上限约束（high≤4000/medium≤2000/low≤800）。
 *
 * 性能基线（D3 决策）：
 * - LCP：Chromium < 2500ms / WebKit+Firefox < 4000ms（放宽 60%）
 * - 帧率：idle ≥ 55fps / speaking ≥ 30fps（60s 采样）
 * - 粒子数：直接读 space.quality.particleCount 断言
 *
 * 仅 chromium 引擎跑性能测试（playwright.config.ts cross-perf.spec.ts，
 * webkit/firefox testIgnore），避免引擎差异导致基线漂移。
 */
import type { Page } from "@playwright/test";

/**
 * 测量 Largest Contentful Paint（LCP）。
 *
 * 经 PerformanceObserver 监听 largest-contentful-paint 事件，
 * 返回最后一次记录的 LCP 时间（ms）。
 *
 * 注意：必须在 page.goto 前安装 observer（navigation 会清空旧 entries）。
 * 用法：
 * ```ts
 * const lcp = await measureLCP(appPage);
 * expect(lcp).toBeLessThan(2500);
 * ```
 *
 * 若浏览器不支持 PerformanceObserver 或无 LCP 记录，返回 Number.POSITIVE_INFINITY
 * （让断言失败而非假绿）。
 */
export async function measureLCP(page: Page): Promise<number> {
  return page.evaluate(() => {
    return new Promise<number>((resolve) => {
      if (typeof PerformanceObserver === "undefined") {
        resolve(Number.POSITIVE_INFINITY);
        return;
      }
      let resolved = false;
      const observer = new PerformanceObserver((entryList) => {
        const entries = entryList.getEntries();
        if (entries.length > 0 && !resolved) {
          resolved = true;
          const lastEntry = entries[entries.length - 1];
          resolve(lastEntry.startTime);
          observer.disconnect();
        }
      });
      observer.observe({ type: "largest-contentful-paint", buffered: true });
      // 超时兜底：5s 内无 LCP 记录返回 Infinity（页面无有意义内容）
      setTimeout(() => {
        if (!resolved) {
          resolved = true;
          resolve(Number.POSITIVE_INFINITY);
          observer.disconnect();
        }
      }, 5000);
    });
  });
}

/**
 * 测量指定时长内的帧率（fps）。
 *
 * 经 requestAnimationFrame 计数：在 durationMs 内统计 RAF 回调次数，
 * 换算为 fps = (callbackCount / durationMs) * 1000。
 *
 * 用法：
 * ```ts
 * const fps = await measureFrameRate(appPage, 60_000); // 60s 采样
 * expect(fps).toBeGreaterThanOrEqual(55);
 * ```
 *
 * 注意：durationMs 越长采样越准但测试越慢；60s 是 D3 决策约定值。
 * 若页面隐藏（document.hidden），RAF 会暂停，fps 会偏低——
 * 调用前应确保 page.bringToFront()。
 */
export async function measureFrameRate(
  page: Page,
  durationMs = 5_000,
): Promise<number> {
  const result = await page.evaluate((dur) => {
    return new Promise<number>((resolve) => {
      let count = 0;
      let cancelled = false;
      const start = performance.now();
      const tick = (): void => {
        if (cancelled) return;
        count++;
        const elapsed = performance.now() - start;
        if (elapsed >= dur) {
          resolve((count / elapsed) * 1000);
          return;
        }
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
      // 超时兜底：dur + 1s 后强制 resolve（避免页面隐藏 RAF 暂停导致死等）
      setTimeout(() => {
        if (count === 0) {
          cancelled = true;
          resolve(0); // 0 fps：页面隐藏或 RAF 未触发
        }
      }, dur + 1000);
    });
  }, durationMs);
  return result;
}

/**
 * 测量从注入事件到 DOM 属性变化的端到端延迟（ms）。
 *
 * 用于断言「状态反映 < 200ms」（D3 决策）：emit voice-status 事件后
 * 等 data-voice-state 属性变化，测时间差。
 *
 * 用法：
 * ```ts
 * const latency = await measureEventLatency(appPage, () => {
 *   fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING);
 * }, "data-voice-state", "speaking");
 * expect(latency).toBeLessThan(200);
 * ```
 *
 * @param trigger 触发事件的函数（如 fakeTauri.emit）
 * @param attrName 要等待的属性名（如 "data-voice-state"）
 * @param attrValue 要等待的属性值（如 "speaking"）
 * @returns 延迟（ms），超时返回 Number.POSITIVE_INFINITY
 */
export async function measureEventLatency(
  page: Page,
  trigger: () => void | Promise<void>,
  attrName: string,
  attrValue: string,
  timeoutMs = 5_000,
): Promise<number> {
  // 在 page 内注入时间戳记录器
  await page.evaluate(() => {
    (window as unknown as { __latencyStart?: number }).__latencyStart = performance.now();
  });
  const start = Date.now();
  await trigger();
  // 等待属性变化
  try {
    await page.waitForFunction(
      ({ name, value }) => {
        const el = document.querySelector('[data-testid="hud-root"]');
        return el?.getAttribute(name) === value;
      },
      { name: attrName, value: attrValue },
      { timeout: timeoutMs },
    );
  } catch {
    return Number.POSITIVE_INFINITY;
  }
  return Date.now() - start;
}

/**
 * 读取 Space 句柄的 quality.particleCount（当前粒子数）。
 *
 * 经 page.evaluate 读 window.__omniSpace__ 或 spaceRef 透出的句柄。
 * ImmersiveSpace 在挂载时把 Space 句柄暴露到 window.__omniDebug.space 或
 * 经 App.tsx spaceRef 注入；此处尝试多个可能的 key。
 *
 * 用法：
 * ```ts
 * const count = await getParticleCount(appPage);
 * expect(count).toBeLessThanOrEqual(4000); // high tier
 * ```
 *
 * 若 Space 未就绪或 quality 字段缺失，返回 -1（让断言失败而非假绿）。
 */
export async function getParticleCount(page: Page): Promise<number> {
  return page.evaluate(() => {
    // 尝试多个可能的 Space 句柄暴露位置
    const w = window as unknown as {
      __omniDebug?: { space?: { quality?: { particleCount?: number } } };
      __omniSpace?: { quality?: { particleCount?: number } };
    };
    const space = w.__omniDebug?.space ?? w.__omniSpace;
    const count = space?.quality?.particleCount;
    return typeof count === "number" ? count : -1;
  });
}

/**
 * 读取当前 quality tier（high/medium/low）。
 *
 * Space 句柄的 quality.tier 字段反映当前画质档（CLAUDE.md §六.3 粒子上限）：
 * - high: ≤ 4000 粒子
 * - medium: ≤ 2000 粒子
 * - low: ≤ 800 粒子
 *
 * 用法：
 * ```ts
 * const tier = await getQualityTier(appPage);
 * expect(["high", "medium", "low"]).toContain(tier);
 * ```
 *
 * 若 Space 未就绪，返回 "unknown"（让断言失败而非假绿）。
 */
export async function getQualityTier(page: Page): Promise<string> {
  return page.evaluate(() => {
    const w = window as unknown as {
      __omniDebug?: { space?: { quality?: { tier?: string } } };
      __omniSpace?: { quality?: { tier?: string } };
    };
    const space = w.__omniDebug?.space ?? w.__omniSpace;
    const tier = space?.quality?.tier;
    return typeof tier === "string" ? tier : "unknown";
  });
}

/**
 * 性能基线阈值（D3 决策）。
 *
 * Chromium 与 WebKit/Firefox 阈值不同（D4 决策：WebKit/Firefox 放宽 60%）。
 * spec 用这些常量断言，避免硬编码。
 */
export const PERF_THRESHOLDS = {
  /** LCP 阈值（ms）：Chromium < 2500 / WebKit+Firefox < 4000。 */
  LCP_CHROMIUM_MS: 2500,
  LCP_OTHER_MS: 4000,
  /** 帧率阈值（fps）：idle ≥ 55 / speaking ≥ 30。 */
  FPS_IDLE_MIN: 55,
  FPS_SPEAKING_MIN: 30,
  /** 状态反映延迟阈值（ms）：事件驱动 < 200ms。 */
  EVENT_LATENCY_MS: 200,
  /** 3D 场景懒加载阈值（ms）：< 1500ms。 */
  SCENE_LAZY_LOAD_MS: 1500,
  /** 粒子数上限（按 quality tier）。 */
  PARTICLE_HIGH_MAX: 4000,
  PARTICLE_MEDIUM_MAX: 2000,
  PARTICLE_LOW_MAX: 800,
} as const;
