# E2E 测试基础设施（TEST_INFRA 里程碑）

> 本目录承载 AI-Omni 全量 E2E 测试，覆盖 M0-M23 里程碑的 UI 功能。运行在 Vite dev server (1420) + 注入 fake Tauri IPC，不依赖 Tauri 本身 / Python 后端 / 音频硬件。

## 快速开始

```bash
# 1. 安装依赖（首次）
pnpm install

# 2. 安装浏览器（首次）
pnpm exec playwright install chromium webkit firefox

# 3. 启动 vite dev server（后台）
pnpm dev &

# 4. 跑全部 E2E 用例（三引擎并行，约 5-10 分钟）
pnpm test:e2e

# 5. 查看 HTML 报告
pnpm test:e2e:report
```

## 常用命令

| 命令 | 说明 |
|------|------|
| `pnpm test:e2e` | 全量 E2E（三引擎并行） |
| `pnpm test:e2e:chromium` | 仅 chromium |
| `pnpm test:e2e:webkit` | 仅 webkit（macOS WKWebView 同源） |
| `pnpm test:e2e:firefox` | 仅 firefox |
| `pnpm test:e2e:visual` | 视觉回归（仅 chromium + Retina） |
| `pnpm test:e2e:headed` | 有头模式（调试用） |
| `pnpm test:e2e:ui` | UI 模式（推荐开发新用例） |
| `pnpm test:e2e:debug` | 调试模式（步进 + Inspector） |
| `pnpm test:e2e:report` | 打开上次报告 |
| `pnpm test:all` | vitest + E2E 全跑 |

## 目录结构

```
e2e/
├── playwright.config.ts          # 配置入口
├── tsconfig.json                 # E2E 独立 tsconfig
├── support/                      # 通用支撑层
│   ├── fakeTauri.ts              # 注入 window.__TAURI_INTERNALS__
│   ├── ipcRouter.ts              # IPC dispatcher（集中式）
│   ├── fixture.ts                # Playwright fixture 扩展
│   ├── debugBridge.ts            # window.__omniDebug 调用桥
│   ├── visualRegression.ts       # 截图对比 + 粒子种子固定
│   ├── perfMetrics.ts            # RAF 帧率 / PerformanceObserver
│   ├── waiters.ts                # waitForVoiceState / waitForWindowMode
│   └── env.ts                    # DEV_SERVER_URL / 常量
├── fixtures/                     # fake IPC 响应数据
├── pages/                        # Page Object Model
├── tests/                        # 14 个 spec
└── __screenshots__/              # 视觉回归基线（git track）
```

## 关键设计决策

### D1：集中式 IPC Router
单一 dispatcher + `register/override/reset` API。11 个 Tauri command 路由表受 `invoke_handler!` 宏约束固定，分散式在 100+ 用例后维护成本爆炸。

### D2：视觉回归非确定性处理
- 粒子种子固定：`page.addInitScript` 重写 `Math.random` 为 LCG（种子 42）
- 截图时机稳定：`page.waitForFunction(() => window.__omniReady)` 等首帧
- mask canvas：`expect(page).toHaveScreenshot("idle.png", { mask: [page.locator("canvas")], maxDiffPixelRatio: 0.01, animations: "disabled" })`

### D3：性能基线
- LCP：`PerformanceObserver` 监听 `largest-contentful-paint`，Chromium < 2500ms / WebKit+Firefox < 4000ms
- 帧率：`requestAnimationFrame` 计数 60s，idle ≥ 55fps / speaking ≥ 30fps
- 粒子数：`page.evaluate(() => window.space?.quality?.particleCount)` 直接读 Space 句柄

### D4：浏览器引擎差异
- 视觉回归仅 Chromium（避免三套基线）
- WebKit/Firefox 仅 DOM 结构断言

### D5：不分离 vite.config.ts
- vitest 的 `test` 段不影响 Playwright
- 既有 72 个 vitest 文件 / 1264 测试零回归

## 与既有 vitest 的隔离

- E2E fixture 独立维护，不与 vitest fake 数据共享
- 仅类型定义（`VoiceStatus` / `Song` / `WeatherMood`）从 `src/data/sources.ts` import（类型 import 不触发运行时，安全）
- 共享会引入跨测试框架耦合，违反项目隔离纪律

## reviewer 审计项

1. 测试真实性：fakeTauri 是否真注入 `__TAURI_INTERNALS__`（page.evaluate 验证）
2. 项目隔离：E2E 代码未修改 `src/` / `src-tauri/` / WeBrain
3. 既有功能零回归：`pnpm test`（vitest）必须保持 1264 passed
4. CLAUDE.md 合规：类型注解 + 中文 docstring；无 emoji 图标
