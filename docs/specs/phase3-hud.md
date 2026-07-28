# Phase 3 设计文档：桌面 HUD + 数字人（omni-hud）

> 里程碑 M4。目标：在 macOS 桌面上提供常驻透明 HUD——系统状态一眼可见、语音管道状态实时反馈、Live2D 数字人伴随交互。风格基调 Film Atelier 暗房。

## 一、定位与边界

- 新应用 `omni-hud/`（AI-Omni 仓库内，与 `omni-brain/` 平级），Tauri 2 + React 18 + TypeScript + Vite。
- **复用资产只读**：flipped（/Users/wangzhenyu/Desktop/ALLProject/flipped/）与 QieZiOS（/Users/wangzhenyu/Desktop/ALLProject/QieZiOS/）只读参考，代码按需拷贝进 omni-hud 后改造，**不跨仓库 import、不改原仓库**。
- 后端数据源 = omni-brain 插件（omni_voice / omni_home）与系统状态；M4.1 阶段先用 mock 数据 + IPC stub，真实桥接在 M4.3 落地。

## 二、复用结论（侦察报告摘要）

### flipped → HUD 壳
- 可复用：`console/src/components/FactoryPanel.tsx`、`Conversation.tsx` 中的 Canvas 粒子动画思路；`console/src/lib/native.ts` 的 Tauri API 封装方式；Launcher/Sidebar/TopBar 组件结构参考。
- 不可复用（需新写）：透明窗口、无边框、置顶、点击穿透——flipped 未实现。

### QieZiOS → Live2D 数字人
- SDK：`pixi-live2d-display` + `pixi.js`（Cubism 4），运行时需加载 `live2dcubismcore.min.js`。
- 核心移植对象：`src/lib/live2d.ts` 的 `createPet(canvas, container, modelUrl)`——透明背景 PIXI.Application、`setMouth(0..1)` 口型驱动。
- 交互参考：`src/shell/DesktopPet.svelte`（拖拽、播报时 `setMouth(Math.random()*0.8)` 口型同步）。
- 移植目标：React 组件 `Live2DAvatar.tsx`（canvas ref + useEffect 初始化），模型文件放 `omni-hud/public/models/`（先用 haru 测试模型下载到本地，不走 CDN）。

## 三、窗口行为契约（M4.1 核心）

| 行为 | 实现 | 验收 |
|------|------|------|
| 透明背景 | `tauri.conf.json` → `windows[].transparent: true`；前端 `html,body { background: transparent }` | 构建通过；配置项存在 |
| 无边框 | `decorations: false` | 同上 |
| 置顶 | `alwaysOnTop: true`（运行时可经 Rust command 切换） | command 单测 |
| 点击穿透 | Rust command `set_click_through(bool)` → macOS `setIgnoresMouseEvents`；前端默认穿透，hover 进入交互区时关闭穿透、离开恢复 | command 存在 + 前端调用逻辑有测试 |
| 位置/尺寸 | 默认右下角停靠，可拖拽移动（drag region） | 配置项存在 |

## 四、设计约束（全 Phase 适用，M4.4 全面落实）

1. **Film Atelier 暗房**：深色背景（近黑但非纯黑）、低亮度环境光、胶片颗粒/显影意象；UI 退后、内容为主；克制、安静、专业。
2. **粒子硬约束**：同屏 ≤ 300 个、速度 ≤ 1.2、颜色 ≤ 5 种；**不得覆盖文字与可交互控件**；粒子层 z-index 永远低于内容层。
3. **动画**：spring / ease-out 缓动，短时长；禁止高饱和彩虹、大面积闪烁、粒子爆炸、快速频闪；尊重 `prefers-reduced-motion`。
4. **图标**：Lucide React 唯一来源，统一经 `src/components/ui/Icon.tsx` 封装，业务代码不直接 import lucide-react；禁止 emoji 当图标。
5. 文字与背景对比度满足可读标准。

## 五、子任务拆解与验收

### M4.1 Tauri 透明窗口 HUD 壳（本里程碑先做）
- omni-hud 脚手架（package.json / vite / tsconfig / src-tauri）。
- 窗口契约五项（上表）全部落地。
- 基础布局骨架：状态条占位（M4.3 填数据）、数字人区占位（M4.2 填 Live2D）、粒子背景层（参数满足硬约束，粒子数量/速度/颜色做成受测常量）。
- `Icon.tsx` 封装就位。
- **验收**：`pnpm vitest run` 全绿 + `pnpm build` 成功 + `cargo build`（src-tauri）成功；测试覆盖粒子约束常量、点击穿透切换逻辑、窗口配置 JSON、store 状态机。

### M4.2 Live2D 数字人
- 移植 `live2d.ts` → `src/live2d/createAvatar.ts`；`Live2DAvatar.tsx` 组件；模型入 `public/models/`。
- API：`speak()` 口型随机动画（供 M4.3 语音事件驱动）、拖拽、待机呼吸动作。
- **验收**：组件单测（mock pixi-live2d-display，不加载真实模型/WebGL）+ build 成功。

### M4.3 系统状态实时展示
- 数据源：omni_voice 管道状态（voice_status）、omni_home 摘要、CPU/内存/网络（Tauri 侧 sysinfo 或 shell）。
- 通道：轮询 + 事件（预留 WebSocket/SSE 接口形状，先 IPC 轮询）。
- **验收**：store 更新逻辑测试（fake 数据源）+ 组件渲染测试。

### M4.4 Film Atelier 完整 UI
- 完整视觉：暗房配色 token、胶片颗粒质感、微粒子聚集成交互元素、水波纹扩散反馈（慢速、大范围）、鼠标跟随优化、多套配色切换按钮。
- **验收**：样式 token 测试 + 配色切换测试 + build；人工目检。

## 六、测试策略

- 前端：`vitest` + `@testing-library/react`；**禁止**测试依赖 WebGL/真实 Tauri 运行时/真实模型——Tauri API 与 pixi 一律 mock。
- Rust：`cargo test`（command 参数校验逻辑）。
- 全量回归：`python3 -m pytest`（后端不受影响，仍须全绿）+ `pnpm vitest run` + `pnpm build`。
