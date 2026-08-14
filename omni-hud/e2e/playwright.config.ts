/**
 * Playwright E2E 测试配置入口（TEST_INFRA 里程碑）。
 *
 * 设计要点：
 * - webServer 复用 Vite dev server（端口 1420，strictPort）——本地开发可 reuseExistingServer
 * - 三引擎并行：chromium（主路径）/ webkit（macOS WKWebView 同源）/ firefox（兼容性）
 * - 视觉回归仅 chromium（避免三套基线维护成本）
 * - 失败用例自动归档 trace / screenshot / video 到 e2e/.test-output/
 *
 * 与既有 vitest 配置零冲突：vitest 读 vite.config.ts 的 test 段，Playwright 读本文件。
 */
import { defineConfig, devices } from "@playwright/test";

const DEV_SERVER_URL = "http://localhost:1420";

export default defineConfig({
  testDir: "./tests",
  testMatch: /.*\.spec\.ts$/,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [
    ["html", { outputFolder: ".report/html" }],
    ["list"],
    ["junit", { outputFile: ".report/junit.xml" }],
  ],
  outputDir: ".test-output",
  timeout: 30_000,
  expect: { timeout: 5_000 },

  use: {
    baseURL: DEV_SERVER_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
  },

  webServer: {
    command: "pnpm dev",
    url: DEV_SERVER_URL,
    reuseExistingServer: true,
    timeout: 60_000,
    stdout: "pipe",
    stderr: "pipe",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "webkit",
      use: { ...devices["Desktop Safari"] },
      testIgnore: ["cross-perf.spec.ts"],
    },
    {
      name: "firefox",
      use: { ...devices["Desktop Firefox"] },
      testIgnore: ["cross-perf.spec.ts"],
    },
    {
      name: "visual-chromium",
      testMatch: "cross-visual.spec.ts",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        deviceScaleFactor: 2,
      },
      snapshotPathTemplate: "{snapshotDir}/{projectName}/{testFilePath}/{arg}{ext}",
    },
  ],
});
