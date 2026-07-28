# AI-Omni 转型计划：M12-M26（eIsland + Mineradio 能力融合）

> 基于 `/Users/wangzhenyu/Desktop/ALLProject/AI-Omni/ai-omni-prompts.md` 的 15 个参考提示词，
> 将 eIsland（灵动岛/插件SDK/系统辅助）与 Mineradio（音乐源/3D歌单架/视觉舞台）的优秀能力融入 AI-Omni。
> 本计划为自治执行设计，含决策点、升级流程、风险缓解与成功标准。

---

## 一、执行摘要

### 转型目标

将 AI-Omni 从「语音助手 + 智能家居 + 桌面HUD」升级为「全能桌面 AI 伴侣」：
- **系统控制**：维纳斯可语音操控音量/亮度/电源/进程/截图等 13 项系统能力
- **音乐生态**：网易云/QQ/酷狗/Spotify 四大源 + 本地音乐 + 歌词同步 + 3D歌单架
- **视觉进化**：灵动岛双形态 + 节奏粒子 + 电影镜头 + 桌面壁纸模式
- **架构成熟**：插件 SDK 正式化 + 多 Agent 协作规范 + 自动更新 + i18n 国际化

### 规模估算

| 维度 | 数值 |
|------|------|
| 里程碑数 | 15（M12-M26） |
| 预计工期 | 45-60 工作日（5 个阶段） |
| 新增插件 | ~20 个（omni_sdk + 13 系统插件 + omni_music + omni_lyrics + omni_weather + 本地音乐） |
| 新增前端组件 | ~30 个 |
| 测试用例增量 | 预计 +800-1200（Python +400, 前端 +400, Rust +200） |

### 阶段总览

| 阶段 | 里程碑 | 主题 | 工期 | 依赖 |
|------|--------|------|------|------|
| 一 | M12→M14 | 体验基础（灵动岛 + Agent面板 + 协作规范） | 6-8 天 | 无 |
| 二 | M15→M16 | 架构基础（插件SDK + 系统辅助矩阵） | 9-12 天 | 无 |
| 三 | M17→M19 | 核心音乐（音乐源 + 歌词 + 本地音乐） | 10-14 天 | M15（SDK） |
| 四 | M20→M22 | 视觉增强（节奏粒子 + 3D歌单架 + 壁纸模式） | 10-13 天 | M17（音乐） |
| 五 | M23-M26 | 生态完善（天气 + i18n + 自动更新 + 增量补丁） | 9-12 天 | M15（SDK）, M17（音乐） |

---

## 二、现状分析（Pre-Implementation）

### 已有能力（M0-M11）

| 能力域 | 现状 | 转型起点 |
|--------|------|----------|
| 语音管道 | VAD唤醒→ASR→LLM→TTS→续听，8态状态机，Function Calling | ✅ 可直接接入新工具 |
| 智能家居 | omni_home 插件，6个工具，HA REST+WS | ✅ 可作为插件迁移范本 |
| 桌面HUD | Tauri透明窗口+Three.js粒子空间+字幕层+声井 | ⚠️ 需增加灵动岛双形态 |
| 本地推理 | Qwen3.6-35B GGUF + Piper TTS + faster-whisper | ✅ 完全离线 |
| 插件机制 | register(ctx) 契约，非正式SDK | ⚠️ 需抽取为 omni_sdk |
| 工具注册 | ToolRegistry + ConversationAgent 工具循环 | ✅ 新插件可直接注册 |
| 状态文件 | 原子写JSON + Rust watcher | ✅ 可扩展新字段 |

### 关键约束（不可违反）

1. **不修改 WeBrain 核心代码** — 所有能力以 omni_* 插件新增
2. **不修改 OpenClaw 网关** — 集群共享资产只读
3. **覆盖率 ≥ 80%** — 每个里程碑 pyproject fail_under=80
4. **TDD 纪律** — 先写失败测试再实现
5. **五件产出** — 代码+TDD测试+全量回归+STATE.json+TEST_LOG.md
6. **图标统一** — Lucide React 唯一，禁止 emoji/SVG
7. **不主动 commit** — 用户不要求时不执行 git 操作

---

## 三、依赖关系分析

### 依赖图

```
M14(协作规范) ──────────────────────────────────── 独立，可并行
M12(灵动岛)   ──────────── M20(3D歌单架需窗口交互)
                          
M15(插件SDK) ─┬─ M16(系统插件矩阵，每个插件继承OmniPlugin)
              ├─ M17(音乐源插件)
              ├─ M19(本地音乐插件)
              └─ M23(天气插件)

M17(音乐源)  ─┬─ M18(歌词，需播放触发)
              ├─ M20(3D歌单架，需歌单数据)
              └─ M21(节奏粒子，需WebAudio源)

M13(Agent面板) ─────────── 独立（基于现有tool_registry）

M22(壁纸模式) ─────────── 依赖 M12(窗口管理基础)
M24(i18n)     ─────────── 独立，可并行
M25(自动更新) ─────────── 独立
M26(增量补丁) ─────────── 依赖 M25(更新框架)
```

### 关键路径

```
M15(SDK) → M17(音乐) → M21(视觉) → 完成   [最长路径，~25天]
```

### 可并行项

- M14（协作规范）可在任何阶段并行
- M24（i18n）可在任何阶段并行
- M13（Agent面板）可与阶段二并行
- M12（灵动岛）可与阶段二并行

---

## 四、分阶段实施计划

### 阶段一：体验基础（M12-M14）

> 目标：建立用户可感知的交互体验基础。灵动岛双形态让待机不抢眼，Agent面板让工具调用可见，协作规范保障后续开发质量。

---

#### M12：灵动岛浮窗双形态（提示词 1）

**来源**：eIsland 灵动岛设计
**工期**：3-4 天
**复杂度**：中
**依赖**：无（基于现有 Tauri 窗口 + FieldStage）

##### 前置分析

当前 cover-display 全屏透明窗口待机时存在感过强。需增加 mini/full 双形态：
- mini：240x48px 顶部浮窗，鼠标穿透，显示状态文字
- full：当前 FieldStage 3D 空间 + CaptionLayer

##### 执行步骤

| # | 步骤 | 负责层 | 预估 |
|---|------|--------|------|
| 1 | Rust: `window_mode` 状态 + `set_window_mode(mini/full)` | src-tauri/src/lib.rs | 0.5天 |
| 2 | Rust: zones.rs 扩展，形态切换时重设交互分区 | src-tauri/src/zones.rs | 0.3天 |
| 3 | Python: pipeline.py 派生 `window_mode` 跟随 voice 状态 | omni_voice/pipeline.py | 0.3天 |
| 4 | Python: state_file.py 写入 `window_mode` 字段 | omni_voice/state_file.py | 0.2天 |
| 5 | 前端: `<MiniBar />` 组件（Lucide图标+状态文字+tooltip） | src/components/MiniBar.tsx | 0.5天 |
| 6 | 前端: FieldStage 包装层监听 window_mode 做展开/收缩动画 | src/components/FieldStage.tsx | 0.5天 |
| 7 | 前端: 状态联动（wake_listening→full, idle→mini） | src/store/hudStore.ts | 0.3天 |
| 8 | 动画规范落地（弹性展开300ms / 收缩200ms） | CSS/Framer Motion | 0.3天 |

##### 决策点

- **D12.1**：动画库选择 → **CSS transition 优先**（不引入 Framer Motion 新依赖，除非弹性曲线 CSS 无法实现）
- **D12.2**：迷你态位置 → **顶部居中**（符合 eIsland 惯例，不遮挡 Dock）
- **D12.3**：形态切换触发 → **自动跟随 voice 状态**（idle→mini, active→full），手动点击/ESC 作为补充

##### 升级流程

- Rust set_window_mode 在 macOS 失败 → 记录日志降级为固定全屏，不阻断
- 粒子过渡动画卡顿 → 降低粒子数到 medium 档

##### 成功标准

- [ ] cargo test 覆盖 set_window_mode + 交互分区切换
- [ ] vitest 覆盖 MiniBar 渲染 + 形态切换动画
- [ ] 唤醒→展开→对话→收缩 完整链路手动验证
- [ ] pytest 全量回归通过

---

#### M13：Agent 可视化工作台（提示词 5）

**来源**：eIsland Agent Screen
**工期**：3-4 天
**复杂度**：中
**依赖**：无（基于现有 ToolRegistry + 事件总线）

##### 前置分析

当前 Function Calling 过程隐式（状态机 tool_using），用户看不到工具调用细节。需在 FieldStage 全显态下半区增加 Agent 面板。

##### 执行步骤

| # | 步骤 | 文件 | 预估 |
|---|------|------|------|
| 1 | 数据模型：ToolCallRecord（name/params/result/status/timestamp） | src/components/agent/types.ts | 0.3天 |
| 2 | AgentPanel 主面板容器（上下分区布局） | src/components/agent/AgentPanel.tsx | 0.5天 |
| 3 | MessageBubble 对话气泡（用户/维纳斯） | src/components/agent/MessageBubble.tsx | 0.3天 |
| 4 | ToolCallCard 工具调用卡片（参数/结果/加载/成功/失败） | src/components/agent/ToolCallCard.tsx | 0.5天 |
| 5 | ToolCallFlow 多轮调用流程（垂直排列） | src/components/agent/ToolCallFlow.tsx | 0.3天 |
| 6 | 数据来源：Rust 监听 STATE.json tool_start/tool_end → Tauri event | src-tauri/src/ + src/data/tauriSource.ts | 0.5天 |
| 7 | 状态联动：tool_using 高亮 + 自动滚动 + 错误红色闪烁 | AgentPanel + ToolCallCard | 0.3天 |
| 8 | EventStream 事件流实时展示（可选，P1） | src/components/agent/EventStream.tsx | 0.3天 |

##### 决策点

- **D13.1**：面板位置 → **全显态下半区**（上半区视觉，下半区 Agent 面板）
- **D13.2**：对话历史 → **侧边可展开**（默认收起，不抢主视觉）
- **D13.3**：数据来源 → **Rust watcher STATE.json → Tauri event**（复用 M5.4 通道，不新增轮询）

##### 成功标准

- [ ] 工具调用可视化（参数/结果/状态）正确展示
- [ ] 多轮工具调用垂直排列
- [ ] vitest 覆盖 AgentPanel + ToolCallCard 渲染
- [ ] tool_using 状态联动高亮

---

#### M14：多 Agent 协作规范（提示词 6）

**来源**：eIsland AGENTS.md/CLAUDE.md/GEMINI.md
**工期**：0.5-1 天
**复杂度**：低
**依赖**：无

##### 前置分析

项目已有 AGENTS.md 和 CLAUDE.md，需更新以反映 omni_sdk 插件规范，并补充 GEMINI.md。

##### 执行步骤

| # | 步骤 | 文件 | 预估 |
|---|------|------|------|
| 1 | 更新 AGENTS.md：新增插件开发规范（OmniPlugin 基类/manifest/权限） | AGENTS.md | 0.2天 |
| 2 | 更新 CLAUDE.md：插件开发流程 + 常见任务模板 | CLAUDE.md | 0.2天 |
| 3 | 新增 GEMINI.md：Gemini 协作配置 + MCP 集成 | GEMINI.md | 0.2天 |
| 4 | 新增 .cursor/.kiro MCP 配置（可选） | .cursor/ | 0.2天 |

##### 成功标准

- [ ] 三份规范文件内容针对 AI-Omni 实际定制
- [ ] 插件开发流程文档化（omni_sdk create → 实现 → 测试 → 注册）

---

### 阶段二：架构基础（M15-M16）

> 目标：抽取正式插件 SDK，让第三方可开发 omni_* 插件；开发系统辅助插件矩阵让维纳斯能控制系统。

---

#### M15：插件 SDK 正式化（提示词 2）

**来源**：eIsland sdk/ 目录 + 插件 runtime 生命周期 host
**工期**：4-5 天
**复杂度**：高
**依赖**：无（但 M16/M17/M19/M23 依赖此里程碑）

##### 前置分析

当前 omni_voice/omni_home 使用 register(ctx) 契约，缺乏统一 SDK。需抽取 omni_sdk 包，含生命周期/事件总线/权限/注册发现。

##### 执行步骤

| # | 步骤 | 文件 | 预估 |
|---|------|------|------|
| 1 | omni_sdk 包结构创建 | omni-brain/plugins/omni_sdk/ | 0.3天 |
| 2 | OmniPlugin 基类（元数据+生命周期钩子+事件钩子+工具注册） | omni_sdk/plugin.py | 0.5天 |
| 3 | PluginContext 上下文（注入配置/事件总线/工具注册器） | omni_sdk/context.py | 0.3天 |
| 4 | LifecycleHost 生命周期管理（扫描/加载/依赖注入/热加载/错误隔离） | omni_sdk/lifecycle.py | 0.8天 |
| 5 | EventBus 统一事件总线（voice.*/home.*/system.*） | omni_sdk/event_bus.py | 0.3天 |
| 6 | Manifest 解析器（manifest.json 格式校验） | omni_sdk/manifest.py | 0.3天 |
| 7 | 权限系统（network/voice.listen/home.control/fs.*/tools.register + 运行时检查） | omni_sdk/permissions.py | 0.5天 |
| 8 | Registry 插件注册与发现 | omni_sdk/registry.py | 0.3天 |
| 9 | 迁移 omni_voice → 继承 OmniPlugin | omni_voice/__init__.py | 0.5天 |
| 10 | 迁移 omni_home → 继承 OmniPlugin | omni_home/__init__.py | 0.5天 |
| 11 | 插件模板脚手架 `omni_sdk create` 命令 | omni_sdk/cli.py + templates/ | 0.3天 |

##### 决策点

- **D15.1**：生命周期异步 vs 同步 → **async**（on_load/on_unload 为 async def，匹配事件总线异步模型）
- **D15.2**：热加载 → **M15 实现 API 但默认不启用**（运行时热加载有风险，先提供能力，后续按需开启）
- **D15.3**：现有插件迁移 → **保持功能不变**，仅重构为继承 OmniPlugin，register(ctx) 适配层保留向后兼容

##### 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 迁移 omni_voice/omni_home 破坏现有功能 | 中 | 高 | 保留 register(ctx) 适配层，渐进迁移，全量回归验证 |
| 热加载导致状态不一致 | 低 | 中 | M15 默认不启用热加载，仅提供 API |
| 权限系统过严阻断正常调用 | 中 | 中 | 权限白名单宽松起步，运行时日志告警而非直接拒绝 |

##### 成功标准

- [ ] omni_sdk 包覆盖率 ≥ 90%
- [ ] 测试插件完整生命周期（加载/卸载/权限/事件/工具注册）
- [ ] omni_voice/omni_home 迁移后全量回归 537 passed
- [ ] `omni_sdk create omni_xxx` 可生成插件骨架

---

#### M16：系统辅助插件矩阵（提示词 3）

**来源**：eIsland 13 个 Windows 系统插件
**工期**：5-7 天（P0+P1 优先，P2/P3 后续）
**复杂度**：高
**依赖**：M15（SDK）

##### 前置分析

eIsland 有 13 个 Windows 系统插件。AI-Omni 需跨平台（macOS 优先，Windows/Linux 兼容）。按优先级分批实现。

##### 执行步骤（P0 — 与语音助手强相关）

| # | 插件 | 工具 | macOS 实现 | 工期 |
|---|------|------|-----------|------|
| 1 | omni_volume | set_volume/get_volume/mute/unmute | `osascript -e 'set volume X'` | 0.5天 |
| 2 | omni_brightness | set_brightness/get_brightness | `osascript -e 'tell app "SystemPrefs"'` 或 brightness.c | 0.5天 |
| 3 | omni_power | lock_screen/sleep/shutdown/restart | `pmset` / `osascript` | 0.5天 |
| 4 | omni_screenshot | screenshot(region)/screenshot_full | `screencapture` 命令 | 0.5天 |

##### 执行步骤（P1 — 系统感知）

| # | 插件 | 工具 | macOS 实现 | 工期 |
|---|------|------|-----------|------|
| 5 | omni_process | list_processes/kill_process/start_process | `ps`/`kill`/`open` | 0.8天 |
| 6 | omni_performance | get_cpu_usage/get_memory_usage/get_disk_usage | `psutil` 库 | 0.5天 |
| 7 | omni_fullscreen_detect | 检测全屏应用 | macOS AXUIElement API | 0.8天 |

##### 执行步骤（P2/P3 — 生态扩展，后续阶段）

| # | 插件 | 说明 | 工期 |
|---|------|------|------|
| 8-10 | omni_smtc/omni_bluetooth/omni_wifi | 系统媒体/蓝牙/WiFi | 2-3天 |
| 11-13 | omni_hardware_info/omni_toast_listener/omni_app_icon | 信息增强 | 1-2天 |

##### 决策点

- **D16.1**：跨平台策略 → **macOS 优先实现**，Windows/Linux 通过 manifest `platform` 字段声明
- **D16.2**：全屏检测 → **macOS 用 Accessibility API**（AXUIElement），不可用时降级为窗口标题检测
- **D16.3**：P2/P3 时机 → **P0+P1 完成后即标记 M16 completed**，P2/P3 作为独立小里程碑后续追加

##### 成功标准

- [ ] P0 四个插件可被维纳斯语音调用（"音量调到50%"等）
- [ ] P1 三个插件功能正常（进程管理/性能监控/全屏检测）
- [ ] 每个插件覆盖率 ≥ 80%（fake 后端测试）
- [ ] 全量回归通过

---

### 阶段三：核心音乐功能（M17-M19）

> 目标：让维纳斯能播放音乐、显示歌词、管理本地音乐库。这是用户明确需要的核心功能。

---

#### M17：音乐源接入（提示词 9）⭐ 重点

**来源**：Mineradio server.js（网易云/QQ/酷狗/Spotify）
**工期**：5-7 天
**复杂度**：非常高
**依赖**：M15（SDK）

##### 前置分析

参考 Mineradio 的四大音乐平台集成。AI-Omni 需实现 omni_music 插件，含多源/扫码登录/Cookie持久化/播放控制。**合规要求**：仅个人学习用途，不破解付费内容。

##### 执行步骤

| # | 步骤 | 文件 | 预估 |
|---|------|------|------|
| 1 | omni_music 包结构 + 数据模型（Song/Playlist/Artist） | omni_music/models.py | 0.3天 |
| 2 | MusicSource 抽象基类（search/get_song_url/get_lyrics/get_song_detail/login_qr） | omni_music/sources/base.py | 0.3天 |
| 3 | Cookie 加密存储（AES-256，~/.ai-omni/cookies/） | omni_music/auth/cookie_store.py | 0.5天 |
| 4 | 扫码登录通用流程（key→二维码→轮询→保存Cookie） | omni_music/auth/qr_login.py | 0.8天 |
| 5 | 网易云音乐源（cloudsearch/song_url_v1/lyric/user_playlist） | omni_music/sources/netease.py | 1.5天 |
| 6 | 本地音乐源（扫描/元数据/内嵌歌词封面） | omni_music/sources/local.py | 0.8天 |
| 7 | QQ音乐源（搜索+Cookie+音质探测） | omni_music/sources/qqmusic.py | 1.0天 |
| 8 | MusicPlayer 播放控制（play/pause/next/prev/seek/queue/模式） | omni_music/player.py | 0.8天 |
| 9 | Function Calling 工具注册（12个工具） | omni_music/tools.py | 0.5天 |
| 10 | 前端：播放控制条 + 登录二维码弹窗 + 当前播放信息 | src/components/music/ | 1.0天 |

##### 决策点

- **D17.1**：播放引擎 → **前端 WebAudio 优先**（前端 `<audio>` 元素 + AnalyserNode，为 M21 节奏分析铺路）；Python 侧仅管理元数据和 URL
- **D17.2**：网易云库选型 → **直接 HTTP 请求**（参考 NeteaseCloudMusicApi 接口，不引入 Node.js 依赖）
- **D17.3**：Spotify → **P3 后续实现**（OAuth 流程复杂，先完成网易云+QQ+本地）
- **D17.4**：合规边界 → **仅免费/试听曲目**，VIP 曲目提示需登录，不提供破解

##### 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 网易云 API 变更导致接口失效 | 高 | 高 | 接口层抽象，mock 测试不依赖真实 API；运行时错误优雅降级 |
| Cookie 泄露 | 低 | 高 | AES-256 加密存储，仅本地，不上传 |
| 音频播放跨域问题 | 中 | 中 | Tauri origin 白名单 CORS |
| API 限流 | 中 | 低 | 请求限流器 + 缓存 |

##### 成功标准

- [ ] 网易云扫码登录全流程通过
- [ ] 搜索→播放→暂停→下一首 完整链路
- [ ] 本地音乐扫描+元数据读取正确
- [ ] 12个 Function Calling 工具可被维纳斯调用
- [ ] Cookie 加密存储验证
- [ ] 覆盖率 ≥ 85%（mock 各平台 API）

---

#### M18：多源歌词匹配（提示词 8）

**来源**：eIsland 多源歌词 + Mineradio 本地LRC
**工期**：2-3 天
**复杂度**：中
**依赖**：M17（音乐播放触发歌词）

##### 执行步骤

| # | 步骤 | 预估 |
|---|------|------|
| 1 | LRC 格式解析器（时间轴+逐字+翻译） | 0.5天 |
| 2 | 歌词来源优先级链（本地LRC→内嵌→在线API→纯文本） | 0.5天 |
| 3 | 歌词同步（基于 currentTime 精确同步+当前行高亮+逐字渐变） | 0.5天 |
| 4 | CaptionLayer 集成（歌词模式 vs 语音回复模式优先级） | 0.3天 |
| 5 | omni_lyrics 插件工具（get_lyrics/search/set_offset/upload） | 0.5天 |

##### 成功标准

- [ ] LRC 解析支持多时间轴+逐字格式
- [ ] 歌词同步误差 < 100ms
- [ ] CaptionLayer 歌词/语音模式正确切换
- [ ] vitest 覆盖 LRC 解析 + 同步逻辑

---

#### M19：本地音乐管理 + 音频解密（提示词 15）

**来源**：Mineradio qishui-audio-decryptor + 本地音乐管理
**工期**：3-4 天
**复杂度**：中高
**依赖**：M15（SDK）, M17（播放器集成）

##### 执行步骤

| # | 步骤 | 预估 |
|---|------|------|
| 1 | LocalMusicLibrary（扫描/元数据/封面/歌词提取） | 0.5天 |
| 2 | 多格式支持（MP3 ID3v2/FLAC Vorbis/M4A/OGG，mutagen 库） | 0.5天 |
| 3 | SQLite 音乐库索引（songs/playlists/play_history + FTS5全文搜索） | 0.8天 |
| 4 | watchdog 文件监听（自动入库/移除/更新） | 0.5天 |
| 5 | 加密音频解密（.qmc/.mflac → 标准 FLAC，仅已购买内容） | 0.8天 |
| 6 | 播客/DJ 内容分析（长音频检测→视觉模式） | 0.5天 |

##### 决策点

- **D19.1**：音频解密 → **仅支持已购买内容的格式转换**，不提供破解付费内容能力
- **D19.2**：SQLite vs JSON → **SQLite + FTS5**（音乐库可能上千首，需高效搜索）

##### 成功标准

- [ ] 本地音乐扫描+元数据正确读取（MP3/FLAC/M4A）
- [ ] SQLite 索引+全文搜索可用
- [ ] 文件监听自动入库/移除
- [ ] 覆盖率 ≥ 85%

---

### 阶段四：视觉增强（M20-M22）

> 目标：让音乐播放时视觉表现力达到 Mineradio 水准。节奏粒子+电影镜头+3D歌单架+壁纸模式。

---

#### M20：3D 歌单架（提示词 10）

**来源**：Mineradio cuefield/ 3D 歌单架
**工期**：3-4 天
**复杂度**：中高
**依赖**：M17（歌单数据）, M12（窗口交互）

##### 执行步骤

| # | 步骤 | 预估 |
|---|------|------|
| 1 | ShelfStage 3D 卡片架（复用 FieldStage renderer，弧形排列） | 0.8天 |
| 2 | Card3D 单张卡片（封面+标题+副标题，纹理映射） | 0.5天 |
| 3 | 交互控制（拖拽旋转/滚轮缩放/悬停放大/点击触发） | 0.8天 |
| 4 | 内容类型（歌单/对话历史/工具结果/推荐卡片） | 0.5天 |
| 5 | 动画（展开 stagger 50ms / 收缩 / 惯性旋转阻尼） | 0.5天 |
| 6 | FieldStage 集成（子场景切换，粒子背景淡化） | 0.3天 |

##### 成功标准

- [ ] 右键唤起 3D 卡片架，弧形排列展示
- [ ] 拖拽旋转+滚轮缩放+点击触发操作
- [ ] 卡片架状态写入 STATE.json（field_mode: space/shelf）
- [ ] vitest 覆盖交互逻辑

---

#### M21：粒子视觉增强 + 节奏电影镜头（提示词 11）

**来源**：Mineradio 粒子视觉舞台 + 节奏电影镜头
**工期**：4-5 天
**复杂度**：高
**依赖**：M17（WebAudio 音频源）

##### 执行步骤

| # | 步骤 | 预估 |
|---|------|------|
| 1 | WebAudio 频谱分析（AudioContext + AnalyserNode + FFT 2048） | 0.5天 |
| 2 | BPM 节拍检测算法 | 0.8天 |
| 3 | 粒子节奏同步（低频大粒子脉冲/中频流动/高频闪烁/强拍爆发） | 1.0天 |
| 4 | 节奏电影镜头系统（推拉/环绕/震动/景深变化） | 1.0天 |
| 5 | 音乐状态视觉（music_playing/music_paused/music_idle） | 0.3天 |
| 6 | beatmap 缓存（~/.ai-omni/cache/beatmaps/） | 0.3天 |
| 7 | 画质分档扩展（cinematic_high/medium/low） | 0.3天 |
| 8 | 后处理增强（bloom强拍增强/色差/暗角呼吸） | 0.5天 |

##### 决策点

- **D21.1**：BPM 检测算法 → **能量峰值法**（简单可靠，复杂算法后续优化）
- **D21.2**：电影镜头 → **预设模式**（安静/标准/激情），用户可切换
- **D21.3**：粒子数 → **音乐模式放宽到 8000**（cinematic_high），但壁纸模式降至 2000

##### 成功标准

- [ ] WebAudio 频谱分析正确提取
- [ ] 粒子跟随低/中/高频节奏
- [ ] 电影镜头系统激活（推拉/环绕/震动）
- [ ] beatmap 缓存避免重复分析
- [ ] prefers-reduced-motion 时禁用节奏效果

---

#### M22：桌面壁纸模式（提示词 12）

**来源**：Mineradio 桌面壁纸模式
**工期**：3-4 天
**复杂度**：中高
**依赖**：M12（窗口管理基础）

##### 执行步骤

| # | 步骤 | 预估 |
|---|------|------|
| 1 | Rust 窗口层级管理（macOS: NSWindow levelbelow；Windows: SetParent Progman） | 0.8天 |
| 2 | 三种模式切换（normal/wallpaper/mini）+ STATE.json 字段 | 0.3天 |
| 3 | 壁纸模式交互区域（右下角控制条/左边缘歌单架/右边缘历史/双击唤醒） | 0.8天 |
| 4 | FieldStage 壁纸适配（粒子降密/降亮/30fps/后处理简化） | 0.5天 |
| 5 | 唤醒浮出（壁纸层→顶层 + 亮度提升） | 0.3天 |
| 6 | 性能优化（GPU < 15%） | 0.3天 |

##### 决策点

- **D22.1**：macOS 壁纸层级 → **NSWindow level = CGWindowLevelForKey(.desktopIconWindowLevel)**（沉到图标下方）
- **D22.2**：多显示器 → **M22 仅支持主屏**，多屏后续
- **D22.3**：开机自启 → **支持**，配置项 `auto_start_wallpaper = true`

##### 成功标准

- [ ] 壁纸模式窗口沉到桌面图标下方
- [ ] 鼠标穿透 + 指定区域可交互
- [ ] 唤醒时窗口浮到顶层
- [ ] 壁纸模式 GPU < 15%
- [ ] cargo test 覆盖窗口层级切换

---

### 阶段五：生态完善（M23-M26）

> 目标：天气情绪感知、国际化、自动更新、增量补丁。让 AI-Omni 成为成熟产品。

---

#### M23：天气情绪电台（提示词 13）

**来源**：Mineradio Open-Meteo 天气电台
**工期**：2-3 天
**复杂度**：中
**依赖**：M15（SDK）; 可选 M17（情绪歌单联动）

##### 执行步骤

| # | 步骤 | 预估 |
|---|------|------|
| 1 | omni_weather 插件（Open-Meteo API + Geocoding + IP定位） | 0.5天 |
| 2 | 天气情绪映射表（clear→sunny/cloudy→calm/rain→melancholy...） | 0.3天 |
| 3 | FieldStage 视觉联动（天气颜色→AmbientLight + 粒子参数） | 0.5天 |
| 4 | 情绪歌单推荐（天气mood→omni_music 推荐） | 0.3天 |
| 5 | 智能家居联动（下雨→关窗帘/天热→开空调） | 0.3天 |
| 6 | 缓存与刷新（30分钟缓存 + 启动刷新） | 0.2天 |

##### 成功标准

- [ ] 天气获取正确（Open-Meteo 免费 API）
- [ ] 天气影响粒子视觉（颜色/速度/形态）
- [ ] 维纳斯语音查询天气正常
- [ ] 智能家居联动建议正确

---

#### M24：i18n 国际化（提示词 4）

**来源**：eIsland i18n/ 目录
**工期**：2-3 天
**复杂度**：中
**依赖**：无

##### 执行步骤

| # | 步骤 | 预估 |
|---|------|------|
| 1 | 前端 i18next + react-i18next 集成 | 0.3天 |
| 2 | zh-CN.json（默认）+ en-US.json 翻译 | 0.5天 |
| 3 | 后端 Python i18n 模块（gettext 或自定义） | 0.5天 |
| 4 | TTS/ASR 多语言模型切换 | 0.3天 |
| 5 | 运行时语言切换（语音命令"切换英文"） | 0.5天 |
| 6 | CI i18n-check 工作流（key一致性 + 未翻译检测） | 0.3天 |

##### 成功标准

- [ ] 前端所有文案通过 i18n key 引用
- [ ] 中/英文切换正常
- [ ] TTS/ASR 跟随语言切换模型
- [ ] CI i18n-check 通过

---

#### M25：自动更新机制（提示词 7）

**来源**：eIsland electron-updater + Mineradio manifest 模拟
**工期**：3-4 天
**复杂度**：中高
**依赖**：无

##### 执行步骤

| # | 步骤 | 预估 |
|---|------|------|
| 1 | tauri-updater 插件集成 + 签名密钥对 | 0.5天 |
| 2 | GitHub Releases 检查（启动延迟30s + 每6h定时 + 手动） | 0.5天 |
| 3 | 多镜像下载支持 | 0.3天 |
| 4 | SHA256 校验 | 0.3天 |
| 5 | 前端更新 UI（版本号+ReleaseNotes+下载进度+重启） | 0.8天 |
| 6 | 本地测试支持（AI_OMNI_UPDATE_MANIFEST 环境变量） | 0.5天 |
| 7 | 维纳斯语音更新播报 | 0.3天 |

##### 成功标准

- [ ] 自动检查更新正常
- [ ] 下载+SHA256校验+安装+重启 全链路
- [ ] 本地 manifest 模拟测试通过
- [ ] 维纳斯可语音检查更新

---

#### M26：增量补丁更新（提示词 14）

**来源**：Mineradio 增量补丁机制
**工期**：2-3 天
**复杂度**：中
**依赖**：M25（更新框架）

##### 执行步骤

| # | 步骤 | 预估 |
|---|------|------|
| 1 | 补丁应用器（update/create/delete + 白名单校验 + 备份） | 0.8天 |
| 2 | 回滚机制（失败自动恢复 + 用户手动回滚） | 0.5天 |
| 3 | 补丁验证（应用后 vite build + import 检查） | 0.3天 |
| 4 | 前端补丁 UI（变更文件列表 + 逐文件进度 + 回滚按钮） | 0.5天 |
| 5 | CI 补丁生成（GitHub Actions 对比 release 差异） | 0.5天 |

##### 决策点

- **D26.1**：补丁大小限制 → **≤ 15MB**，超过回退全量
- **D26.2**：白名单 → **src/ + plugins/ + resources/ + 根 package.json**，禁止 src-tauri/
- **D26.3**：回滚 → **应用前完整备份**，启动失败/测试失败/手动 三种触发方式

##### 成功标准

- [ ] 补丁应用 update/create/delete 全覆盖
- [ ] 回滚机制有效
- [ ] 白名单校验拒绝越界文件
- [ ] 超限回退全量更新

---

## 五、资源需求

### 开发资源

| 资源 | 需求 | 备注 |
|------|------|------|
| 主 Agent（编排） | 1 | 任务拆解/下发/验收 |
| 执行 subagent | 按需 | 编码/测试/文档 |
| Reviewer subagent | 独立 | 审计不通过退回 |
| Python 3.14 环境 | ✅ 已有 | .venv |
| Node.js + pnpm | ✅ 已有 | omni-hud |
| Rust + cargo | ✅ 已有 | src-tauri |
| Tauri CLI | ✅ 已有 | tauri dev |

### 外部依赖（需新增）

| 依赖 | 用途 | 引入时机 |
|------|------|----------|
| `i18next` + `react-i18next` | 前端 i18n | M24 |
| `mutagen` | 音频元数据读取 | M19 |
| `psutil` | 系统性能监控 | M16 |
| `watchdog` | 文件监听 | M19 |
| SQLite (stdlib `sqlite3`) | 音乐库索引 | M19 |
| tauri-updater 插件 | 自动更新 | M25 |
| WebAudio API（浏览器内置） | 频谱分析 | M21 |

### 模型/数据资产（需新增）

| 资产 | 用途 | 位置 |
|------|------|------|
| Piper en_US-lessac-medium | 英文 TTS | models/piper/ |
| 网易云 Cookie | 音乐源登录 | ~/.ai-omni/cookies/（加密） |
| beatmap 缓存 | 节拍分析缓存 | ~/.ai-omni/cache/beatmaps/ |
| 音乐库 SQLite | 本地音乐索引 | ~/.ai-omni/music/library.db |

---

## 六、风险评估与缓解

### 高风险项

| # | 风险 | 概率 | 影响 | 缓解策略 | 升级条件 |
|---|------|------|------|----------|----------|
| R1 | 网易云 API 变更导致音乐源失效 | 高 | 高 | 接口层抽象 + mock 测试 + 运行时降级 | 连续3次API失败→暂停音乐源插件 |
| R2 | 插件 SDK 迁移破坏现有功能 | 中 | 高 | 保留 register(ctx) 适配层 + 全量回归 | 任一回归失败→退回修复 |
| R3 | Tauri 窗口层级在 macOS 异常 | 中 | 中 | NSWindow API 降级 + 日志 | 窗口不可见→升级用户手动确认 |
| R4 | 音频解密法律风险 | 低 | 高 | 仅已购买内容 + 不提供破解 | 用户要求破解→拒绝并说明 |
| R5 | WebAudio 频谱分析性能瓶颈 | 中 | 中 | 画质分档 + 30fps 降级 | FPS < 30→自动降档 |
| R6 | Cookie 泄露 | 低 | 高 | AES-256 加密 + 仅本地 | 检测到泄露→立即清除并告警 |

### 中风险项

| # | 风险 | 概率 | 影响 | 缓解 |
|---|------|------|------|------|
| R7 | 增量补丁应用失败导致应用损坏 | 中 | 中 | 完整备份 + 自动回滚 |
| R8 | 跨平台系统插件兼容性 | 中 | 中 | macOS 优先 + platform 声明 |
| R9 | 3D 歌单架 GPU 占用过高 | 中 | 中 | 限制卡片数 + LOD 降级 |
| R10 | i18n 翻译不完整 | 低 | 低 | CI i18n-check 检测 |

### 升级流程

```
执行 subagent 遇到问题：
├─ 测试失败 → 自行修复（≤3次重试）
├─ 依赖缺失 → 安装（沙箱内）/ 报告主 Agent
├─ 架构决策 → 记录备选方案，升级主 Agent 决策
├─ 法律/合规风险 → 立即停止，升级用户
├─ 跨仓库依赖 → 不修改，记录绕开方案
└─ 连续3次同类失败 → 升级用户

主 Agent 决策点：
├─ 技术选型（库/算法/方案）→ 按 D{M}.{N} 决策点执行
├─ 里程碑完成 → reviewer 审计通过后标记 completed
├─ 回归失败 → 退回执行 subagent 修复
└─ 超出本计划范围 → 升级用户确认
```

---

## 七、质量保障（QA）

### 测试策略

| 层 | 工具 | 覆盖率门槛 | 执行时机 |
|----|------|-----------|----------|
| Python 单元 | pytest + fake 后端 | ≥ 80% | 每个里程碑 |
| 前端单元 | vitest + Testing Library | ≥ 80% | 每个里程碑 |
| Rust 单元 | cargo test | — | 涉及 Rust 改动时 |
| 集成 | pytest integration/ | — | 每个里程碑 |
| E2E | 手动 + Playwright（可选） | — | 阶段结束 |
| 回归 | 全量 pytest + vitest + build | 100% pass | 每个里程碑关闭前 |

### 里程碑关闭清单（五件产出）

每个里程碑 M{N} 关闭前必须齐备：

1. [ ] **代码实现**：符合 CLAUDE.md 规范，只新增 omni_* 插件与本仓库代码
2. [ ] **TDD 测试**：先写失败测试再实现，覆盖率 ≥ 80%
3. [ ] **全量回归**：pytest 全绿 + vitest 全绿 + build 成功，记录实际输出
4. [ ] **STATE.json 更新**：M{N} 条目及子任务状态机更新
5. [ ] **TEST_LOG.md 记录**：含关键代码片段与真实测试结果输出

### Reviewer 审计清单

- [ ] 需求覆盖度（对照提示词需求逐项核对）
- [ ] 代码规范（CLAUDE.md：类型注解/中文docstring/import顺序/惰性导入）
- [ ] 测试真实有效（非空断言/非自我实现/fake后端）
- [ ] 既有功能回归（omni_voice/omni_home/omni-hud 不破坏）
- [ ] 合规检查（不破解付费/不硬编码密钥/Cookie加密）

---

## 八、成功标准

### 阶段级成功标准

| 阶段 | 成功标准 |
|------|----------|
| 一 | 灵动岛双形态可用 + Agent面板展示工具调用 + 协作规范更新 |
| 二 | omni_sdk 可创建第三方插件 + 维纳斯可语音控制音量/亮度/电源/截图/进程 |
| 三 | 维纳斯可播放网易云音乐 + 歌词同步显示 + 本地音乐库管理 |
| 四 | 音乐播放时粒子跟随节奏 + 3D歌单架浏览 + 壁纸模式可用 |
| 五 | 天气影响视觉 + 中英文切换 + 自动更新 + 增量补丁 |

### 项目级成功标准（M26 完成后）

- [ ] **语音体验**：唤醒"维纳斯"→说话→回复全链路 < 2s（本地推理）
- [ ] **系统控制**：13项系统能力可语音调用
- [ ] **音乐生态**：4大音乐源 + 本地音乐 + 歌词同步 + 3D歌单架
- [ ] **视觉表现**：灵动岛双形态 + 节奏粒子 + 电影镜头 + 壁纸模式
- [ ] **架构成熟**：omni_sdk 插件 SDK + 多 Agent 协作规范
- [ ] **国际化**：中英文双语支持
- [ ] **自动更新**：全量 + 增量补丁
- [ ] **测试资产**：Python 1300+ / 前端 850+ / Rust 200+ 用例全绿
- [ ] **覆盖率**：全项目 ≥ 80%

---

## 九、自治执行框架

### 执行循环

```
主 Agent 对每个里程碑 M{N}：
1. 读取本计划 M{N} 章节 + 对应提示词
2. 派发执行 subagent（一次性给足上下文）
   - 实现前：先写失败测试（TDD red）
   - 实现：最小代码使测试通过（TDD green）
   - 重构：优化代码质量（TDD refactor）
3. 执行 subagent 自验：python -m pytest + vitest run + build
4. 派发 reviewer subagent 审计
5. 审计通过 → 更新 STATE.json + TEST_LOG.md → 标记 completed
6. 审计不通过 → 退回执行 subagent 修复 → 重复 3-5
```

### 决策点汇总

| 决策点 | 主题 | 默认决策 | 升级条件 |
|--------|------|----------|----------|
| D12.1 | 动画库 | CSS transition | 弹性曲线无法实现→Framer Motion |
| D12.2 | 迷你态位置 | 顶部居中 | 用户指定其他位置 |
| D15.1 | 生命周期异步 | async | — |
| D15.2 | 热加载 | 提供API默认不启用 | — |
| D16.1 | 跨平台 | macOS优先 | 用户要求Windows优先 |
| D16.3 | P2/P3时机 | P0+P1完成即关闭M16 | — |
| D17.1 | 播放引擎 | 前端WebAudio | — |
| D17.3 | Spotify | P3后续 | 用户要求提前 |
| D19.1 | 音频解密 | 仅已购买内容 | 用户要求破解→拒绝 |
| D21.2 | 电影镜头 | 预设模式 | — |
| D22.1 | macOS壁纸层级 | desktopIconWindowLevel | API不可用→降级 |
| D26.1 | 补丁大小 | ≤15MB | — |

### 升级矩阵

| 问题类型 | 自治处理 | 升级用户 |
|----------|----------|----------|
| 测试失败 | ≤3次重试 | 连续3次同类失败 |
| 依赖缺失 | 沙箱内安装 | 跨仓库依赖 |
| 架构决策 | 按D{M.N}默认 | 超出计划范围 |
| 法律风险 | — | 立即升级 |
| API变更 | 降级运行 | 核心功能不可用 |
| 性能问题 | 自动降档 | FPS<15持续 |

---

## 十、时间线总览

```
Week 1-2:  阶段一（M12-M14）体验基础
Week 3-4:  阶段二（M15-M16）架构基础
Week 5-7:  阶段三（M17-M19）核心音乐
Week 8-10: 阶段四（M20-M22）视觉增强
Week 11-12: 阶段五（M23-M26）生态完善
```

### 关键里程碑时间点

| 里程碑 | 预计完成 | 交付物 |
|--------|----------|--------|
| M12 | 第1周末 | 灵动岛双形态 |
| M14 | 第1周末 | 协作规范 |
| M15 | 第3周末 | 插件SDK |
| M16 | 第4周末 | 系统辅助插件P0+P1 |
| M17 | 第6周末 | 音乐源接入 |
| M19 | 第7周末 | 本地音乐管理 |
| M21 | 第9周末 | 节奏粒子+电影镜头 |
| M22 | 第10周末 | 壁纸模式 |
| M26 | 第12周末 | 增量补丁更新 |

---

## 附录：里程碑与提示词映射

| 里程碑 | 提示词 | 来源 | 阶段 |
|--------|--------|------|------|
| M12 | 1 灵动岛浮窗双形态 | eIsland | 一 |
| M13 | 5 Agent可视化工作台 | eIsland | 一 |
| M14 | 6 多Agent协作规范 | eIsland | 一 |
| M15 | 2 插件SDK正式化 | eIsland | 二 |
| M16 | 3 系统辅助插件矩阵 | eIsland | 二 |
| M17 | 9 音乐源接入 | Mineradio | 三 |
| M18 | 8 多源歌词匹配 | eIsland+Mineradio | 三 |
| M19 | 15 音频解密与本地音乐 | Mineradio | 三 |
| M20 | 10 3D歌单架 | Mineradio | 四 |
| M21 | 11 粒子视觉+节奏镜头 | Mineradio | 四 |
| M22 | 12 桌面壁纸模式 | Mineradio | 四 |
| M23 | 13 天气情绪电台 | Mineradio | 五 |
| M24 | 4 i18n国际化 | eIsland | 五 |
| M25 | 7 自动更新机制 | eIsland+Mineradio | 五 |
| M26 | 14 增量补丁更新 | Mineradio | 五 |
