# AI-Omni 参考提示词合集（eIsland + Mineradio）

> 共 15 个独立提示词，每个对应一个可参考的优秀能力。按模块分类，可单独投喂给 AI 编码助手。

---

## 目录

**eIsland 参考（8 个）**
1. 灵动岛浮窗双形态
2. 插件 SDK 正式化
3. 系统辅助插件矩阵
4. i18n 国际化
5. Agent 可视化工作台
6. 多 Agent 协作规范
7. 自动更新机制
8. 多源歌词匹配

**Mineradio 参考（7 个）**
9. 音乐源接入（网易云/QQ/酷狗/Spotify）
10. 3D 歌单架
11. 粒子视觉舞台 + 节奏电影镜头
12. 桌面壁纸模式
13. 天气情绪电台
14. 增量补丁更新
15. 音频解密与本地音乐

---

## 提示词 1：灵动岛浮窗双形态（参考 eIsland）

```
# 任务：为 AI-Omni 增加浮窗双形态切换

## 背景
当前 AI-Omni 使用 Tauri 透明 cover-display 全屏窗口，待机时视觉存在感过强。
参考 eIsland（github.com/JNTMTMTM/eIsland）的灵动岛设计，增加"迷你态"和"全显态"双形态。

## 需求

### 形态定义
- 迷你态（待机时）：
  - 屏幕顶部居中浮窗，尺寸约 240x48px
  - 显示：状态图标 + 一行文字（"待命"/"我在听…"/"思考中…"/"正在调用工具…"）
  - 鼠标穿透，不干扰操作
  - 鼠标悬停时微展开显示更多信息
  
- 全显态（唤醒/对话时）：
  - 展开为当前 FieldStage 3D 粒子空间 + CaptionLayer 字幕层
  - 尺寸约 480x320px（可配置）
  - 显示完整交互界面

### 切换逻辑
- 唤醒词触发：迷你态 → 全显态（弹性展开动画，300ms）
- 对话结束 5 秒后：全显态 → 迷你态（收缩淡出动画，200ms）
- 手动点击迷你态：展开为全显态
- ESC 键：全显态 → 迷你态

### Rust 侧改动（src-tauri/src/）
1. 窗口管理：
   - 新增 `window_mode` 状态：mini / full
   - `set_window_mode(mode)` 函数：动态调整窗口尺寸 + 位置
   - 迷你态：set_size(240,48) + set_position(居中顶部) + set_always_on_top(true)
   - 全显态：set_size(480,320) + set_position(居中顶部偏下) + set_always_on_top(true)

2. 交互分区（zones.rs 扩展）：
   - 迷你态：整个浮窗区域为交互区
   - 全显态：复用现有 set_interactive_zones 逻辑
   - 形态切换时重新设置交互分区

3. 状态文件扩展（status.rs）：
   - STATE.json 新增字段：`window_mode: "mini" | "full"`
   - Python 侧状态机变更时同步写入

### 前端改动（src/）
1. 新增 `<MiniBar />` 组件：
   - 固定在顶部
   - 显示状态图标（Lucide React）+ 状态文字
   - hover 时展开 tooltip 显示最近一条回复摘要
   - 点击触发 `expand_to_full` 事件

2. FieldStage 包装层：
   - 监听 `window_mode` 变化
   - mini → full：scale + opacity 动画展开
   - full → mini：反向收缩
   - 使用 Framer Motion 或 CSS transition

3. 状态联动：
   - 监听 voice 状态机的 wake_listening/recording/thinking/speaking/tool_using → 自动展开
   - 监听 idle/follow_up_listening 超时 → 自动收缩

### 状态机扩展（Python 侧）
pipeline.py 状态机新增：
- `window_mode` 作为派生状态，跟随 voice 状态变化
- idle → mini
- wake_listening/recording/thinking/speaking/tool_using → full
- follow_up_listening → full（续听窗口内保持展开）
- 超时回 idle → mini

### 动画规范
- 展开：cubic-bezier(0.34, 1.56, 0.64, 1)（弹性），300ms
- 收缩：cubic-bezier(0.4, 0, 0.6, 1)，200ms
- 粒子过渡：迷你态时粒子聚集为小球，全显态时散开为空间

### 测试要求
- Rust：cargo test 覆盖 set_window_mode、交互分区切换
- 前端：vitest 覆盖 MiniBar 渲染、形态切换动画
- 集成：手动验证唤醒→展开→对话→收缩完整链路

请先输出详细设计文档，再逐文件实现。
```

---

## 提示词 2：插件 SDK 正式化（参考 eIsland）

```
# 任务：抽取 omni_sdk 插件开发框架

## 背景
当前 AI-Omni 有 omni_voice、omni_home 两个插件，但缺乏统一的插件 SDK。
参考 eIsland（github.com/JNTMTMTM/eIsland）的 sdk/ 目录和插件 runtime 生命周期 host 设计，
抽取标准化的 omni_sdk，使第三方可开发 omni_* 插件。

## eIsland 插件 SDK 参考
eIsland 的 sdk/ 包含：
- src/：SDK 核心源码
- templates/：插件模板
- package.json：独立 npm 包
其插件 runtime 支持生命周期 host 控制（on_load/on_unload 等钩子）。

## 需求

### 1. omni_sdk 包结构
```
omni_sdk/
  __init__.py
  plugin.py          # 插件基类
  lifecycle.py       # 生命周期 host
  event_bus.py       # 事件总线（统一 voice.*/home.*/system.* 事件）
  manifest.py        # 插件 manifest 解析
  permissions.py     # 权限声明与校验
  registry.py        # 插件注册与发现
  context.py         # 插件运行上下文（注入配置、事件、工具注册器）
  exceptions.py      # 异常定义
  templates/
    plugin_template/  # 插件脚手架模板
```

### 2. 插件基类设计
```python
class OmniPlugin:
    # 元数据
    name: str
    version: str
    description: str
    permissions: list[str]  # ["voice.listen", "home.control", "network"]
    
    # 生命周期钩子
    async def on_load(self, ctx: PluginContext): ...
    async def on_unload(self): ...
    
    # 事件钩子
    async def on_wake(self, event): ...
    async def on_transcript(self, event): ...
    async def on_reply(self, event): ...
    async def on_tool_call(self, event): ...
    async def on_error(self, event): ...
    
    # 工具注册
    def register_tools(self, registrar: ToolRegistrar): ...
```

### 3. 生命周期 host
- 插件加载：扫描 plugins/ 目录，解析 manifest.json，实例化插件
- 依赖注入：通过 PluginContext 注入配置、事件总线、工具注册器
- 热加载：支持运行时加载/卸载插件（不重启主进程）
- 错误隔离：单个插件异常不影响其他插件

### 4. 插件 manifest 格式
```json
{
  "name": "omni_weather",
  "version": "1.0.0",
  "description": "天气感知插件",
  "entry": "plugin.py",
  "permissions": ["network", "voice.reply"],
  "dependencies": ["omni_home>=1.0.0"],
  "config_schema": {
    "api_key": {"type": "string", "required": false}
  }
}
```

### 5. 权限系统
- 网络访问权限：network
- 语音事件订阅：voice.listen / voice.reply
- 智能家居控制：home.control
- 文件系统访问：fs.read / fs.write
- 工具注册：tools.register
- 运行时检查：插件调用超出权限的操作时抛 PermissionDenied

### 6. 迁移现有插件
- omni_voice → 继承 OmniPlugin，注册 voice.* 工具
- omni_home → 继承 OmniPlugin，注册 home_* 工具
- 保持现有功能不变，仅重构为插件标准结构

### 7. 插件模板脚手架
- `omni_sdk create omni_xxx` 命令生成插件骨架
- 包含 manifest.json + plugin.py + test/ + README.md

### 测试要求
- 覆盖率 ≥ 90%
- 测试插件加载/卸载/热加载/权限校验/事件订阅/工具注册
- 集成测试：模拟第三方插件完整生命周期

请先输出 SDK API 设计文档，再实现核心模块。
```

---

## 提示词 3：系统辅助插件矩阵（参考 eIsland 13 个插件）

```
# 任务：为 AI-Omni 开发系统辅助插件矩阵

## 背景
eIsland 有 13 个 Windows 系统辅助插件，覆盖了系统控制的方方面面。
AI-Omni 作为桌面助手，应具备类似的系统感知与控制能力，让维纳斯能语音操控系统。

## eIsland 插件矩阵参考
1. eisland-windows-application-icon-helper    # 应用图标获取
2. eisland-windows-bluetooth-helper           # 蓝牙设备管理
3. eisland-windows-brightness-helper          # 屏幕亮度控制
4. eisland-windows-fullscreen-detector        # 全屏检测
5. eisland-windows-hardware-info-helper       # 硬件信息
6. eisland-windows-performance-monitor        # 性能监控
7. eisland-windows-power-helper               # 电源管理
8. eisland-windows-processes-attacker         # 进程管理
9. eisland-windows-screenshot-helper          # 截图
10. eisland-windows-smtc-helper               # 系统媒体控制（SMTC）
11. eisland-windows-toast-listener            # Toast 通知监听
12. eisland-windows-volume-helper             # 音量控制
13. eisland-windows-wifi-helper               # WiFi 管理

## 需求

### 优先级 P0（与语音助手强相关）
开发以下 omni_system 插件，每个注册为 Function Calling 工具：

1. **omni_volume**：音量控制
   - 工具：set_volume(level)、get_volume、mute、unmute
   - 语音："维纳斯，音量调到 50%" / "静音"
   
2. **omni_brightness**：屏幕亮度
   - 工具：set_brightness(level)、get_brightness
   - 语音："维纳斯，屏幕调暗一点"
   
3. **omni_power**：电源管理
   - 工具：lock_screen、sleep、shutdown、restart
   - 语音："维纳斯，锁屏" / "半小时后休眠"
   
4. **omni_screenshot**：截图
   - 工具：screenshot(region)、screenshot_full
   - 语音："维纳斯，截个屏" / "截取选区"

### 优先级 P1（系统感知）
5. **omni_process**：进程管理
   - 工具：list_processes、kill_process(name)、start_process(path)
   - 语音："维纳斯，关掉 Chrome" / "打开记事本"
   
6. **omni_performance**：性能监控
   - 工具：get_cpu_usage、get_memory_usage、get_disk_usage
   - 定时推送：CPU > 80% 时主动通知
   - 语音："维纳斯，电脑卡不卡？" → 报告资源占用
   
7. **omni_fullscreen_detect**：全屏检测
   - 检测当前是否有全屏应用（游戏/视频）
   - 全屏时自动降低 HUD 透明度或切换迷你态
   - 全屏时维纳斯回复改为纯语音（不显示字幕）

### 优先级 P2（生态扩展）
8. **omni_smtc**：系统媒体控制
   - 接入 Windows SMTC，控制第三方播放器（网易云/QQ/Spotify 桌面版）
   - 工具：media_play、media_pause、media_next、media_prev、media_info
   - 语音："维纳斯，下一首" / "暂停音乐"
   
9. **omni_bluetooth**：蓝牙管理
   - 工具：list_bt_devices、connect_bt(name)、disconnect_bt
   - 语音："维纳斯，连接我的耳机"
   
10. **omni_wifi**：WiFi 管理
    - 工具：list_wifi、connect_wifi(ssid)、wifi_status
    - 语音："维纳斯，WiFi 状态怎么样"

### 优先级 P3（信息增强）
11. **omni_hardware_info**：硬件信息
    - 工具：get_gpu_info、get_cpu_info、get_battery_info
    - 语音："维纳斯，电池还有多少"
    
12. **omni_toast_listener**：Toast 通知监听
    - 监听 Windows 通知，转发给维纳斯
    - 收到重要通知时主动播报："收到微信消息：xxx"
    
13. **omni_app_icon**：应用图标获取
    - 为进程管理/快捷启动提供应用图标
    - 缓存图标到本地

### 技术实现
- 每个插件独立目录，遵循 omni_sdk 规范
- Windows API 调用优先用 Python 库（pywin32 / wmi / ctypes）
- 不可用库时用 PowerShell 子进程（subprocess.run）
- 所有工具注册到 ConversationAgent 的 tool_registry
- 权限声明：每个插件 manifest 声明所需权限

### 跨平台考虑
- macOS/Linux 对应实现用对应系统命令
- 不可跨平台时插件 manifest 声明 platform: ["windows"]

请按 P0 → P1 → P2 → P3 顺序实现，每个插件完成后立即可被维纳斯语音调用。
```

---

## 提示词 4：i18n 国际化（参考 eIsland）

```
# 任务：为 AI-Omni 引入 i18n 国际化支持

## 背景
AI-Omni 当前纯中文，参考 eIsland 的 i18n/ 目录结构，引入完整国际化支持，
为未来英文/日文等语言扩展做准备。

## eIsland i18n 参考
eIsland 有独立的 i18n/ 目录，支持多语言切换，CI 中有 i18n-check 工作流。

## 需求

### 1. 前端 i18n（React）
- 库选型：i18next + react-i18next
- 目录结构：
```
src/
  i18n/
    index.ts          # i18n 初始化
    locales/
      zh-CN.json      # 中文（默认）
      en-US.json      # 英文
    types.ts          # 类型定义（key 校验）
```

- 覆盖范围：
  - HUD 所有状态文案（待命/我在听/思考中/正在调用工具…）
  - CaptionLayer 字幕系统语言
  - 设置面板（未来）
  - 错误提示

### 2. 后端 i18n（Python）
- 库选型：Python gettext 或自定义 i18n 模块
- 目录结构：
```
omni_voice/
  i18n/
    messages-zh-CN.po
    messages-en-US.po
    __init__.py
```

- 覆盖范围：
  - 维纳斯回复模板（"我在" / "好的" / "正在为您查询"）
  - 错误消息
  - 工具调用结果模板

### 3. TTS 多语言
- TTS 统一走 OpenClaw 网关 `/v1/audio/speech`（OpenAI 兼容），本地不加载 TTS 模型
- 配置语言切换时切换 `tts_voice`，由网关侧映射到对应语言的音色/模型
- 多语言音色清单以网关可用模型为准（OMNI_VOICE_TTS_VOICE 覆盖）

### 4. ASR 多语言
- ASR 统一走 OpenClaw 网关 `/v1/audio/transcriptions`（OpenAI 兼容，whisper 风格），本地不加载 ASR 模型
- 配置语言时透传 `language` 参数（`OpenAIASR.transcribe(language=...)`）
- 中英混合识别：language="zh" + initial_prompt 含英文

### 5. 语言切换机制
- 配置项：config.toml 中 `language = "zh-CN"` 或 `"en-US"`
- 运行时切换：语音命令"切换英文" / "Switch to Chinese"
- 切换时同步：前端 i18n + 后端模板 + TTS 模型 + ASR 参数

### 6. CI 检查
- GitHub Actions 工作流：i18n-check
  - 检查所有 locale 文件 key 一致性
  - 检查是否有未翻译的 key
  - 检查代码中是否有硬编码文案

### 7. LLM prompt 语言适配
- ConversationAgent 的 system prompt 根据语言切换
- 中文：维纳斯人格用中文描述
- 英文：Venus 人格用英文描述

请先实现前端 i18n 框架，再逐步迁移现有硬编码文案。
```

---

## 提示词 5：Agent 可视化工作台（参考 eIsland Agent Screen）

```
# 任务：为 AI-Omni 增加 Agent 可视化工作台

## 背景
当前 AI-Omni 的 Function Calling 过程是隐式的（状态机 tool_using），
用户看不到工具调用细节。参考 eIsland 的 Agent Screen，增加可视化面板。

## eIsland Agent Screen 参考
eIsland 有独立的 Agent Screen，展示 AI agent 的工作空间和生产力工作流。

## 需求

### 1. Agent Panel 布局（全显态下半区）
```
┌─────────────────────────────────┐
│        FieldStage 3D 粒子空间      │  ← 上半区：视觉
├─────────────────────────────────┤
│ 💬 用户：把客厅灯打开              │  ← 下半区：Agent 面板
│ 🔧 调用 home_control_light       │
│    ↳ 参数：{room:"客厅", action:"on"} │
│    ↳ 结果：客厅灯已开启 ✅          │
│ 💬 维纳斯：好的，客厅灯已经打开了    │
└─────────────────────────────────┘
```

### 2. 工具调用可视化
- 工具名 + 参数 + 结果以卡片形式展示
- 调用中：显示加载动画（Lucide Loader2 旋转）
- 成功：绿色对勾
- 失败：红色叉 + 错误信息
- 支持多轮工具调用（垂直排列）

### 3. 对话历史时间线
- 侧边可展开对话历史
- 每条记录：时间戳 + 角色 + 内容 + 工具调用
- 支持搜索和过滤

### 4. 工具注册表浏览
- 设置面板展示所有已注册工具
- 每个工具：名称、描述、参数 schema、来源插件
- 可启用/禁用单个工具

### 5. 事件流实时展示
- 监听事件总线 voice.* / home.* / system.* 事件
- 以日志流形式实时滚动展示
- 不同事件类型用不同颜色

### 6. 前端组件
```
src/
  components/
    agent/
      AgentPanel.tsx        # 主面板容器
      MessageBubble.tsx     # 对话气泡
      ToolCallCard.tsx      # 工具调用卡片
      ToolCallFlow.tsx      # 多轮调用流程
      EventStream.tsx       # 事件流
      ToolRegistry.tsx      # 工具注册表浏览
      ConversationHistory.tsx # 历史时间线
```

### 7. 状态联动
- tool_using 状态：Agent Panel 高亮当前调用
- 工具完成：自动滚动到结果
- 错误时：面板边框红色闪烁

### 8. 数据来源
- Rust 侧监听 STATE.json 的 tool_start/tool_end 事件
- 前端通过 Tauri event 或轮询获取
- 对话历史从 ConversationAgent 的 memory 序列化

请先设计 Agent Panel 的组件结构和数据流，再实现。
```

---

## 提示词 6：多 Agent 协作规范（参考 eIsland）

```
# 任务：为 AI-Omni 建立多 AI Agent 协作规范

## 背景
eIsland 维护了 AGENTS.md / CLAUDE.md / GEMINI.md 三个文件，
分别针对不同 AI 编码助手（Codex / Claude Code / Gemini）定义协作规范。
AI-Omni 应建立类似规范，确保多个 AI 工具协作开发时风格一致。

## eIsland 参考文件
- AGENTS.md：通用 Agent 协作规范
- CLAUDE.md：Claude Code 专属指南（插件开发指南等）
- GEMINI.md：Gemini 专属配置

## 需求

### 1. AGENTS.md（项目根目录）
内容包含：
```markdown
# AI-Omni Agent 协作规范

## 项目概览
- 五层架构：插件层 / 事件总线 / 本地推理 / 语音管道 / 桌面 HUD
- 技术栈：Python 后端 + Tauri/Rust + React/TypeScript 前端
- 测试要求：覆盖率 ≥ 80%，Python pytest + 前端 vitest + Rust cargo test

## 代码规范
- Python：black + ruff，类型注解必填
- TypeScript：严格模式，ESLint + Prettier
- Rust：rustfmt + clippy
- 图标：统一用 Lucide React，禁止 emoji 和自定义 SVG

## 提交规范
- 不主动 git commit（除非用户明确要求）
- PR 模板包含：变更说明、验证说明、前端规范核对清单
- commit message：conventional commits（feat/fix/docs/refactor/test/chore）

## 插件开发规范
- 所有新能力以 omni_* 插件形式新增
- 插件必须继承 OmniPlugin 基类
- 必须包含 manifest.json
- 必须有对应测试目录

## 禁止事项
- 不修改 WeBrain 核心代码
- 不修改 OpenClaw 网关共享资产
- 不引入 emoji 作为 UI 元素
- 不硬编码文案（使用 i18n）
- 不在代码中存储密钥（使用环境变量）
```

### 2. CLAUDE.md（Claude Code 专属）
```markdown
# Claude Code 协作指南

## 上下文优先级
1. AGENTS.md（项目级规范）
2. 本文件（Claude 专属）
3. 用户当前指令

## 插件开发流程
1. 使用 omni_sdk create 生成骨架
2. 实现 OmniPlugin 子类
3. 注册工具到 tool_registry
4. 编写测试（覆盖率 ≥ 90%）
5. 更新 manifest.json
6. 运行全量测试验证

## 常见任务模板
- 新增工具：[模板]
- 新增插件：[模板]
- 修复 bug：[模板]
```

### 3. GEMINI.md（Gemini 专属）
```markdown
# Gemini 协作配置

## MCP 集成
- CodeGraph 配置
- 文件系统访问范围

## 任务路由
- 复杂重构 → 使用 Plan 模式
- 单文件修改 → 直接执行
```

### 4. .cursor / .kiro / .gemine MCP 配置
参考 eIsland 的 MCP 配置文件，为各 AI 工具配置 CodeGraph 集成。

请生成这三个文件，内容针对 AI-Omni 项目实际情况定制。
```

---

## 提示词 7：自动更新机制（参考 eIsland + Mineradio）

```
# 任务：为 AI-Omni 实现自动更新机制

## 背景
参考 eIsland 的 electron-updater + GitHub Releases 方案，
以及 Mineradio 的增量补丁更新 + manifest 模拟机制，
为 AI-Omni 实现完整的自动更新能力。

## 参考实现

### eIsland 方案
- electron-updater + GitHub Releases
- 多更新源：COS（腾讯云）+ OSS（阿里云）+ GitHub
- 更新源配置：normalizeUpdateSource()

### Mineradio 方案（server.js）
- GitHub Releases latest 检测
- 增量补丁：PATCH_MAX_BYTES = 12MB，限制更新范围
- 补丁白名单：PATCH_ALLOWED_ROOTS = ['public', 'desktop', 'build']
- manifest 模拟：MINERADIO_UPDATE_MANIFEST 环境变量指向本地 JSON
- 多镜像下载：MINERADIO_UPDATE_MIRRORS 支持国内加速
- SHA256 校验
- 版本比较：compareVersions() 语义化版本

## 需求

### 1. Tauri 自动更新
- 使用 tauri-updater（Tauri 官方更新插件）
- 配置 endpoints 指向 GitHub Releases
- 签名验证：生成签名密钥对，签名每个发布包

### 2. 更新检查
- 启动时检查（延迟 30 秒，避免影响启动）
- 每 6 小时定时检查
- 手动检查：设置面板"检查更新"按钮
- 维纳斯语音："维纳斯，检查更新"

### 3. 更新流程
1. 检测到新版本 → 推送通知（前端 + Toast）
2. 展示 Release Notes（从 GitHub Releases body 提取）
3. 用户确认下载
4. 下载安装包（支持多镜像）
5. SHA256 校验
6. 安装并重启

### 4. 增量补丁（参考 Mineradio）
- 小版本更新支持增量补丁
- 补丁格式：JSON diff（仅变更的文件）
- 补丁大小限制：≤ 15MB
- 补丁白名单：仅允许更新 src/、plugins/、resources/
- 应用前自动备份原文件

### 5. 更新源配置
```toml
# config.toml
[update]
provider = "github"
owner = "your-username"
repo = "AI-Omni"
check_interval_hours = 6
mirrors = [
  "https://mirror.example.com/{url}",
  "https://ghproxy.com/{url}"
]
```

### 6. 本地测试支持（参考 Mineradio）
- 环境变量 `AI_OMNI_UPDATE_MANIFEST` 指向本地 manifest JSON
- 模拟线上 Release 进行更新链路测试
- manifest 格式：
```json
{
  "version": "0.1.1",
  "releaseNotes": ["修复了 xxx", "新增了 yyy"],
  "asset": {
    "url": "http://localhost:8080/AI-Omni-0.1.1.msi",
    "sha256": "abc123..."
  }
}
```

### 7. 前端更新 UI
- 设置面板 → 关于 → 检查更新
- 更新对话框：版本号 + Release Notes + 下载进度条
- 下载完成提示重启
- 维纳斯语音播报更新进度

### 测试要求
- 单元测试：版本比较、manifest 解析、SHA256 校验
- 集成测试：本地 manifest 模拟完整更新链路
- 补丁测试：增量补丁应用与回滚

请先实现核心更新检查与全量更新流程，增量补丁作为 P1。
```

---

## 提示词 8：多源歌词匹配（参考 eIsland + Mineradio）

```
# 任务：为 AI-Omni 实现多源歌词匹配系统

## 背景
eIsland 支持多源歌词自动匹配，Mineradio 支持本地 LRC + 内嵌歌词。
AI-Omni 作为语音助手，可在播放音乐时同步显示歌词。

## 参考实现
- eIsland：多在线歌词源自动匹配
- Mineradio：本地 .lrc/.txt + FLAC 内嵌 LYRICS 标签（含时间轴 LRC）

## 需求

### 1. 歌词来源优先级
1. 本地同名 .lrc 文件（与音频同目录）
2. 音频文件内嵌歌词（FLAC LYRICS 标签 / MP3 USLT 帧）
3. 在线 API（网易云 lyric / lyric_new 接口）
4. 在线 API（QQ 音乐歌词接口）
5. 纯文本歌词（无时间轴，按行滚动）

### 2. 歌词解析
- LRC 格式解析：[mm:ss.xx] 时间轴 + 歌词文本
- 多时间轴支持：一行多时间戳
- 逐字歌词：[mm:ss.xx]<mm:ss.xx>字<mm:ss.xx>字（参考网易云逐字格式）
- 翻译歌词：网易云 lyric_new 返回 tlyric

### 3. 歌词同步
- 基于 WebAudio currentTime 精确同步
- 当前行高亮 + 滚动居中
- 逐字模式：当前字高亮渐变
- 打断处理：拖动进度条时立即跳转

### 4. CaptionLayer 集成
- 歌词模式：复用现有 CaptionLayer 组件
- 播放音乐时：CaptionLayer 切换为歌词显示
- 语音对话时：CaptionLayer 显示维纳斯回复
- 优先级：语音回复 > 歌词显示

### 5. 自定义歌词（参考 Mineradio）
- 上传 .lrc 文件覆盖自动匹配
- 手动编辑歌词文本
- 歌词偏移调整（±ms）
- 歌词位置控制（上/中/下）

### 6. omni_lyrics 插件
```python
class LyricsPlugin(OmniPlugin):
    tools = [
        get_lyrics(song_id, source),     # 获取歌词
        search_lyrics(title, artist),    # 搜索歌词
        set_lyric_offset(ms),            # 设置偏移
        upload_lyrics(file_path),        # 上传自定义歌词
    ]
```

### 7. 与音乐播放联动
- omni_music 播放歌曲时自动触发歌词获取
- 维纳斯语音："维纳斯，这首歌歌词是什么" → 显示歌词
- "维纳斯，歌词滚快一点" → 调整滚动速度

请先实现本地歌词解析 + LRC 同步，再接入在线源。
```

---

## 提示词 9：音乐源接入（参考 Mineradio）⭐ 重点

```
# 任务：为 AI-Omni 开发 omni_music 音乐源接入插件

## 背景
用户明确需要音乐源接入。参考 Mineradio（github.com/XxHuberrr/Mineradio）的 server.js，
其集成了网易云、QQ 音乐、酷狗、Spotify 四大平台，包含扫码登录、Cookie 持久化、
试听检测、多音质探测等完整能力。

## Mineradio 音乐源实现分析

### 网易云音乐（server.js 核心部分）
- 库：NeteaseCloudMusicApi（Node.js）
- 功能：cloudsearch / song_detail / song_url / lyric / login_qr_* / user_playlist
- Cookie 持久化：./.cookie 文件，normalizeCookieHeader() 处理
- 扫码登录：login_qr_key → login_qr_create → login_qr_check 轮询
- 试听检测：freeTrialInfo 字段判断
- 音质探测：standard / higher / exhigh / lossless / hires

### QQ 音乐（qq-vip-api.js）
- Cookie 持久化：./.qq-cookie
- 搜索 + 登录态 + 音源补充

### 酷狗（kugou-api.js）
- 独立 API 模块

### Spotify（spotify-api.js）
- OAuth 授权流程

## 需求

### 1. omni_music 插件架构
```
omni_music/
  __init__.py
  plugin.py              # 插件主类
  sources/
    __init__.py
    base.py              # 音乐源基类
    netease.py           # 网易云音乐
    qqmusic.py           # QQ 音乐
    kugou.py             # 酷狗音乐
    spotify.py           # Spotify
    local.py             # 本地音乐
  auth/
    __init__.py
    cookie_store.py      # Cookie 加密存储
    qr_login.py          # 扫码登录通用流程
  player.py              # 播放控制
  playlist.py            # 歌单管理
  models.py              # 数据模型（Song/Playlist/Artist）
  config.py              # 配置
```

### 2. 音乐源基类
```python
class MusicSource(ABC):
    name: str
    
    @abstractmethod
    async def search(self, keyword: str, limit: int = 20) -> list[Song]: ...
    
    @abstractmethod
    async def get_song_url(self, song_id: str, quality: str = "exhigh") -> str: ...
    
    @abstractmethod
    async def get_lyrics(self, song_id: str) -> Lyrics: ...
    
    @abstractmethod
    async def get_song_detail(self, song_id: str) -> Song: ...
    
    async def login_qr(self) -> QrLoginSession: ...
    async def login_status(self) -> LoginStatus: ...
    async def get_user_playlists(self) -> list[Playlist]: ...
```

### 3. 网易云音乐源（Python 实现）
- 库选型：pcopyright 库或直接 HTTP 请求（参考 NeteaseCloudMusicApi 的接口）
- 扫码登录：
  1. 调用 /login/qr/key 获取 key
  2. 生成二维码（前端展示）
  3. 轮询 /login/qr/check（每 2 秒）
  4. 登录成功保存 Cookie
- Cookie 存储：加密存储到 ~/.ai-omni/cookies/netease.json
- 搜索：cloudsearch 接口
- 歌曲URL：song_url_v1 接口（带 Cookie）
- 歌词：lyric_new 接口（含逐字歌词）
- 歌单：user_playlist + playlist_detail

### 4. QQ 音乐源
- 参考 Mineradio 的 qq-vip-api.js
- 搜索接口 + Cookie 登录态
- 音源补充（多音质探测）

### 5. 本地音乐源
- 扫描本地文件夹（MP3/FLAC/WAV/M4A）
- 读取元数据（mutagen 库）
- 内嵌歌词提取（FLAC LYRICS 标签 / MP3 USLT 帧）
- 内嵌封面提取

### 6. 播放控制
```python
class MusicPlayer:
    # 基于 WebAudio（前端）或 just_playback（Python）
    async def play(self, song: Song): ...
    async def pause(self): ...
    async def resume(self): ...
    async def next(self): ...
    async def prev(self): ...
    async def seek(self, position: float): ...
    async def set_volume(self, volume: float): ...
    
    # 播放模式
    mode: Literal["order", "repeat_one", "shuffle", "repeat_all"]
    
    # 队列管理
    async def add_to_queue(self, song: Song): ...
    async def get_queue(self) -> list[Song]: ...
```

### 7. Function Calling 工具注册
```python
tools = [
    # 搜索
    {"name": "music_search", "desc": "搜索歌曲", "params": {"keyword": str, "source": str}},
    # 播放
    {"name": "music_play", "desc": "播放歌曲", "params": {"song_id": str, "source": str}},
    {"name": "music_pause", "desc": "暂停"},
    {"name": "music_resume", "desc": "继续播放"},
    {"name": "music_next", "desc": "下一首"},
    {"name": "music_prev", "desc": "上一首"},
    # 歌单
    {"name": "music_get_playlists", "desc": "获取用户歌单"},
    {"name": "music_play_playlist", "desc": "播放歌单", "params": {"playlist_id": str}},
    # 信息
    {"name": "music_now_playing", "desc": "当前播放信息"},
    {"name": "music_get_lyrics", "desc": "获取当前歌词"},
    # 登录
    {"name": "music_login_qr", "desc": "生成登录二维码", "params": {"source": str}},
    {"name": "music_login_status", "desc": "检查登录状态"},
]
```

### 8. 语音交互示例
- "维纳斯，播放周杰伦的晴天" → music_search + music_play
- "维纳斯，下一首" → music_next
- "维纳斯，暂停音乐" → music_pause
- "维纳斯，这首歌叫什么" → music_now_playing
- "维纳斯，登录网易云" → music_login_qr（前端显示二维码）
- "维纳斯，播放我的喜欢歌单" → music_get_playlists + music_play_playlist

### 9. 前端集成
- 播放控制条（迷你态底部或全显态底部）
- 歌单浏览界面
- 登录二维码弹窗
- 当前播放信息（封面 + 标题 + 艺术家）
- 与 CaptionLayer 歌词联动

### 10. 合规要求
- 仅个人学习与本地体验用途
- 不提供绕过付费/破解音质能力
- Cookie 仅本地加密存储，不上传
- 遵守各平台用户协议
- 免费/试听曲目优先，VIP 曲目提示用户需登录

### 11. 安全要求（参考 Mineradio）
- Cookie 加密存储（AES-256）
- API 请求限流
- 本地服务仅监听 127.0.0.1
- CORS 仅允许 Tauri origin

### 测试要求
- Mock 各平台 API 响应
- Cookie 存储加密/解密测试
- 扫码登录流程测试（mock 轮询）
- 播放控制状态机测试
- 覆盖率 ≥ 85%

请先实现网易云源 + 本地音乐源 + 播放控制，再扩展其他源。
```

---

## 提示词 10：3D 歌单架（参考 Mineradio）

```
# 任务：为 AI-Omni 实现 3D 歌单架浏览

## 背景
参考 Mineradio 的 3D 歌单架（cuefield/ 目录），在 AI-Omni 的 FieldStage 中
增加 3D 内容浏览能力，让用户可通过鼠标浏览歌单、对话历史、工具结果。

## Mineradio 参考
- 右键唤起 3D 歌单架
- 支持歌单队列浏览
- 3D 卡片排列 + 旋转交互
- 桌面壁纸模式下可点击歌单卡片播放

## 需求

### 1. 3D 卡片架组件
- 基于 Three.js（复用 FieldStage 的 renderer）
- 卡片以弧形排列在 3D 空间中
- 每张卡片：封面图 + 标题 + 副标题
- 鼠标拖拽旋转视角
- 滚轮缩放
- 点击卡片触发对应操作

### 2. 内容类型
- **歌单卡片**：封面 + 歌单名 + 歌曲数 → 点击播放
- **对话历史卡片**：时间 + 摘要 → 点击恢复对话上下文
- **工具结果卡片**：工具名 + 结果摘要 → 点击展开详情
- **推荐卡片**：每日推荐歌曲/操作

### 3. 交互设计
- 右键唤起：FieldStage 右键 → 卡片架从中心展开
- ESC / 点击空白：卡片架收缩消失
- 鼠标悬停卡片：卡片放大 + 高亮
- 点击卡片：触发操作 + 卡片架消失
- 拖拽旋转：水平拖拽改变视角
- 滚轮：缩放卡片架距离

### 4. 动画
- 展开：卡片从中心点飞出，呈弧形排列（stagger 50ms）
- 收缩：卡片飞回中心点消失
- 悬停：卡片 scale 1.1 + z 轴前移
- 旋转：惯性旋转 + 阻尼衰减

### 5. 与 FieldStage 集成
- 卡片架作为 FieldStage 的子场景
- 激活时：粒子背景淡化为暗色
- 退出时：粒子恢复
- 卡片架状态写入 STATE.json：`field_mode: "space" | "shelf"`

### 6. 前端组件
```
src/
  components/
    field/
      ShelfStage.tsx        # 3D 卡片架主场景
      Card3D.tsx            # 单张 3D 卡片
      ShelfController.tsx   # 交互控制（旋转/缩放/点击）
```

### 7. 数据来源
- 歌单：omni_music 插件提供
- 对话历史：ConversationAgent.memory 序列化
- 工具结果：事件总线 tool_end 事件缓存
- 推荐：omni_music personalized 接口

请先实现 3D 卡片架基础交互（弧形排列 + 旋转 + 点击），再接入数据源。
```

---

## 提示词 11：粒子视觉增强 + 节奏电影镜头（参考 Mineradio）

```
# 任务：增强 AI-Omni 粒子视觉系统，引入节奏电影镜头

## 背景
AI-Omni 已有六态粒子空间（FieldStage），但视觉表现力不如 Mineradio。
参考 Mineradio 的粒子视觉舞台 + 节奏电影镜头系统，增强音乐播放时的视觉表现。

## Mineradio 视觉系统参考
- WebAudio 频谱分析
- 粒子系统跟随节奏
- 电影镜头系统：基于节奏的相机运动
- 播客/DJ 专属视觉模式
- beatmap 缓存（BEATMAP_CACHE_DIR）

## 需求

### 1. WebAudio 频谱分析
- 前端创建 AudioContext + AnalyserNode
- 连接音频播放源（omni_music 的音频元素）
- 提取频域数据（FFT size 2048）
- 提取时域数据（波形）
- 计算 BPM（节拍检测）

### 2. 粒子节奏同步
当前 FieldStage 粒子是自由漂移，增强为：
- **低频粒子**：大粒子，随低频鼓点脉冲
- **中频粒子**：中等粒子，随中频旋律流动
- **高频粒子**：小粒子，随高频闪烁
- **节拍爆发**：检测到强拍时，粒子向外爆发后回收

### 3. 节奏电影镜头系统（参考 Mineradio）
新增 `cinematic_mode`，音乐播放时激活：
- **推拉镜头**：副歌段落相机推进，主歌段落拉远
- **环绕镜头**：缓慢围绕粒子空间旋转
- **震动镜头**：强拍时轻微震动
- **景深变化**：副歌时景深变浅（bloom 增强）

镜头参数：
```typescript
interface CinematicConfig {
  beatSensitivity: number;    // 节拍灵敏度
  cameraMoveSpeed: number;    // 镜头移动速度
  cameraShakeIntensity: number; // 震动强度
  bloomBoostOnBeat: number;   // 强拍 bloom 增强
  dofApertureOnChorus: number; // 副歌景深
}
```

### 4. 音乐状态视觉
在现有六态基础上，增加音乐相关状态：
- `music_playing`：粒子跟随节奏，电影镜头激活
- `music_paused`：粒子缓慢漂浮，镜头静止
- `music_idle`：当前六态的 idle

### 5. 播客/DJ 专属视觉（参考 Mineradio）
- 检测长音频（>10 分钟）→ 播客模式
  - 视觉变缓慢、冷色调
  - 粒子稀疏
- 检测 DJ 混音 → DJ 模式
  - 视觉激烈、暖色调
  - 粒子密集 + 快速变换

### 6. beatmap 缓存（参考 Mineradio）
- 分析完成的 BPM + 节拍点缓存到本地
- 缓存路径：~/.ai-omni/cache/beatmaps/{song_id}.json
- 避免重复分析

### 7. 画质分档扩展
当前：high≤4000 / medium≤2000 / low≤800
音乐模式增加：
- cinematic_high：8000 粒子 + 后处理全开
- cinematic_medium：4000 粒子 + 后处理简化
- cinematic_low：2000 粒子 + 无后处理

### 8. 后处理增强
- bloom：强拍时增强（参考 Mineradio）
- 色差：副歌时轻微色差
- 暗角：节奏变化时暗角呼吸
- 颗粒：保持现有 film grain

### 9. 可视化参数控制
- 设置面板：节奏灵敏度、镜头速度、粒子密度等滑块
- 维纳斯语音："维纳斯，视觉效果强烈一点" → 调高参数
- 预设模式：安静/标准/激情

请先实现 WebAudio 分析 + 粒子节奏同步，再实现电影镜头系统。
```

---

## 提示词 12：桌面壁纸模式（参考 Mineradio）

```
# 任务：为 AI-Omni 实现桌面壁纸模式

## 背景
参考 Mineradio 的桌面壁纸模式（窗口沉到桌面图标下方，可视化器当背景，
仍可交互），让 AI-Omni 的 FieldStage 可作为动态桌面背景常驻。

## Mineradio 壁纸模式参考
- 窗口层级：沉到桌面图标下方
- 可视化器作为动态背景
- 可交互：点歌单卡片播放、滚轮缩放、3D 歌架
- 鼠标移到屏幕左/右边缘唤起控制

## 需求

### 1. 窗口层级管理（Rust 侧）
- 新增 `wallpaper_mode` 状态
- Windows 实现：
  - 使用 SetWindowPos 将窗口置于 HWND_DESKTOP 下方
  - 或使用 SetParent 将窗口父级设为 Progman/WorkerW
  - 参考动态壁纸软件的通用做法
- 激活时：
  - 窗口全屏覆盖
  - 置于桌面图标下方
  - 鼠标穿透（但指定区域可交互）

### 2. 交互区域
- 壁纸模式下鼠标穿透，但以下区域可交互：
  - 屏幕右下角：唤起迷你控制条（播放/暂停/下一首）
  - 屏幕左侧边缘滑动：唤起歌单卡片架
  - 屏幕右侧边缘滑动：唤起对话历史
  - 双击空白：唤起维纳斯（语音唤醒替代方案）

### 3. FieldStage 壁纸适配
- 粒子密度降低（避免影响性能和图标可见性）
- 亮度降低（不抢眼）
- 音乐播放时：粒子跟随节奏但不爆发
- 唤醒时：从壁纸"浮现"到前景（z-order 切换 + 亮度提升）

### 4. 模式切换
- 三种模式：
  - `normal`：当前全屏 cover-display（默认）
  - `wallpaper`：壁纸模式（沉底）
  - `mini`：迷你浮窗（提示词 1）
- 切换方式：
  - 设置面板切换
  - 维纳斯语音："维纳斯，变成壁纸" / "维纳斯，恢复正常"
  - 系统托盘菜单

### 5. 壁纸模式下的维纳斯
- 语音唤醒正常工作
- 唤醒时：窗口从壁纸层浮到顶层
- 对话结束：窗口沉回壁纸层
- TTS 语音正常播放
- CaptionLayer 在壁纸模式下也可显示（半透明）

### 6. 性能优化
- 壁纸模式帧率降至 30fps（节省 GPU）
- 粒子数减半
- 后处理关闭或简化
- 仅在音乐播放时激活节奏分析

### 7. 多显示器支持
- 选择目标显示器（主屏/副屏）
- 仅在指定显示器壁纸化

### 8. 开机自启
- 壁纸模式支持开机自启
- 自启后直接进入壁纸模式

### 测试要求
- Windows 10/11 兼容性测试
- 与其他动态壁纸软件共存测试
- 性能测试：壁纸模式 GPU 占用 < 15%

请先实现 Windows 窗口层级管理 + 基础壁纸模式，再优化交互。
```

---

## 提示词 13：天气情绪电台（参考 Mineradio）

```
# 任务：为 AI-Omni 开发 omni_weather 天气情绪感知插件

## 背景
参考 Mineradio 的 Open-Meteo 天气电台和情绪化播放队列，
让 AI-Omni 具备天气感知能力，影响视觉和音乐推荐。

## Mineradio 天气实现参考（server.js）
- Open-Meteo Forecast API：https://api.open-meteo.com/v1/forecast
- Open-Meteo Geocoding API：https://geocoding-api.open-meteo.com/v1/search
- IP 定位：http://ip-api.com/json/
- 默认位置：上海（WEATHER_DEFAULT_LOCATION）
- 基于天气/位置/城市生成情绪化播放队列

## 需求

### 1. omni_weather 插件
```python
class WeatherPlugin(OmniPlugin):
    name = "omni_weather"
    permissions = ["network"]
    
    tools = [
        get_weather(),              # 获取当前天气
        get_forecast(days=7),       # 获取预报
        get_mood_playlist(),        # 基于天气的情绪歌单
    ]
```

### 2. 数据源
- 天气：Open-Meteo（免费、无需 key、开源）
  - 当前天气：temperature, weather_code, wind_speed, humidity
  - 逐时预报：24 小时
  - 逐日预报：7 天
- 位置：
  - 优先 IP 定位（ip-api.com）
  - 手动配置城市
  - Open-Meteo Geocoding 搜索城市

### 3. 天气情绪映射
```python
WEATHER_MOOD_MAP = {
    "clear": {"mood": "sunny", "color": "#FFD700", "energy": 0.8},
    "cloudy": {"mood": "calm", "color": "#B0C4DE", "energy": 0.4},
    "rain": {"mood": "melancholy", "color": "#4682B4", "energy": 0.3},
    "snow": {"mood": "pure", "color": "#F0F8FF", "energy": 0.2},
    "thunderstorm": {"mood": "intense", "color": "#4B0082", "energy": 0.9},
    "fog": {"mood": "mysterious", "color": "#708090", "energy": 0.3},
}
```

### 4. 视觉联动（FieldStage）
- 天气状态影响粒子参数：
  - 晴天：暖色粒子（金黄）+ 稀疏上飘
  - 雨天：冷色粒子（蓝）+ 垂直下落
  - 雪天：白色粒子 + 缓慢飘落
  - 雷暴：紫色粒子 + 间歇爆发
  - 雾天：灰色粒子 + 低速弥漫
- 天气颜色作为 AmbientLight 基色
- 温度影响粒子速度（高温快、低温慢）

### 5. 情绪歌单
- 基于天气 mood 推荐音乐：
  - sunny → 欢快流行、夏日电子
  - rain → 抒情、爵士、Lo-Fi
  - snow → 古典、氛围、白噪音
  - thunderstorm → 摇滚、电子
- 调用 omni_music 的推荐接口
- 维纳斯："外面在下雨，给你放点适合雨天的歌"

### 6. 智能家居联动
- 天气变化时主动建议：
  - "外面下雨了，要关窗帘吗？" → omni_home.curtain_close
  - "今天很热，要开空调吗？" → omni_home.ac_on
  - "外面风大，要关窗吗？"
- 定时检查（每小时），天气变化时主动通知

### 7. 语音交互
- "维纳斯，今天天气怎么样" → 报告天气
- "维纳斯，明天会下雨吗" → 预报
- "维纳斯，适合出门吗" → 综合建议
- 主动播报：早上第一次唤醒时报告今日天气

### 8. 前端展示
- 迷你态：显示天气图标 + 温度
- 全显态：天气信息卡片（当前 + 24h + 7d）
- 壁纸模式：天气影响背景视觉

### 9. 缓存与刷新
- 天气数据缓存 30 分钟
- 启动时刷新
- 维纳斯可强制刷新："维纳斯，刷新天气"

请先实现天气获取 + 视觉联动，再实现情绪歌单和智能家居联动。
```

---

## 提示词 14：增量补丁更新（参考 Mineradio）

```
# 任务：为 AI-Omni 实现增量补丁更新机制

## 背景
参考 Mineradio 的增量补丁更新（server.js 中的 patch 机制），
支持小版本更新时仅下载变更文件，而非完整安装包。

## Mineradio 补丁机制参考
- PATCH_MAX_BYTES = 12 * 1024 * 1024（12MB 限制）
- PATCH_ALLOWED_ROOTS = Set(['public', 'desktop', 'build'])（白名单目录）
- PATCH_ALLOWED_FILES = Set(['server.js', 'dj-analyzer.js', 'package.json', 'package-lock.json'])（白名单文件）
- 补丁格式：JSON，包含文件 diff
- 补丁前自动备份：UPDATE_PATCH_BACKUP_DIR

## 需求

### 1. 补丁生成（CI 侧）
- GitHub Actions 中，对比上个 release 与当前的文件差异
- 生成 patch.json：
```json
{
  "from_version": "0.1.0",
  "to_version": "0.1.1",
  "files": [
    {
      "path": "src/components/FieldStage.tsx",
      "action": "update",
      "content": "<base64 encoded file content>",
      "sha256": "abc123..."
    },
    {
      "path": "plugins/omni_voice/pipeline.py",
      "action": "update",
      "content": "..."
    },
    {
      "path": "src/old_component.tsx",
      "action": "delete"
    },
    {
      "path": "src/new_feature.tsx",
      "action": "create",
      "content": "..."
    }
  ],
  "total_size": 5242880
}
```

### 2. 补丁白名单
- 允许更新的目录：
  - src/（前端源码）
  - plugins/（插件）
  - resources/（资源文件）
  - omni_voice/、omni_home/ 等 Python 包
- 允许更新的根文件：
  - package.json
  - package-lock.json
  - Cargo.toml
  - requirements.txt
- 禁止更新：
  - src-tauri/（Rust 编译产物，需全量更新）
  - node_modules/
  - .git/
  - 配置文件（config.toml）

### 3. 补丁大小限制
- 单个补丁 ≤ 15MB
- 超过限制则回退为全量更新
- 压缩：补丁 JSON 使用 gzip 压缩

### 4. 补丁应用流程
1. 下载 patch.json（支持多镜像）
2. SHA256 校验补丁完整性
3. 备份当前文件到 ~/.ai-omni/patches/backup/{version}/
4. 逐文件应用：
   - update：覆盖文件（先备份原文件）
   - create：创建新文件
   - delete：删除文件（先备份）
5. 更新版本号
6. 重启应用
7. 失败回滚：从备份恢复

### 5. 回滚机制
- 应用前完整备份所有将被修改的文件
- 回滚目录：~/.ai-omni/patches/backup/{from_version}_{timestamp}/
- 回滚触发：
  - 应用后启动失败
  - 应用后测试不通过
  - 用户手动回滚："维纳斯，回滚到上个版本"
- 回滚后恢复文件 + 版本号

### 6. 补丁验证
- 应用后运行快速验证：
  - 前端：vite build 是否成功
  - Python：import 检查
  - Rust：可选（Rust 改动走全量更新）
- 验证失败自动回滚

### 7. 前端 UI
- 更新检查时：显示"增量更新可用（5MB）" vs "全量更新可用（80MB）"
- 补丁详情：变更文件列表
- 应用进度：逐文件进度
- 回滚按钮：设置 → 更新历史 → 回滚

### 8. 补丁发布
- GitHub Release 中附加 patch.json 资产
- 命名：AI-Omni-{from}-to-{to}.patch.json
- Release Notes 中标注支持增量更新

### 测试要求
- 补丁生成测试：模拟两个版本差异
- 补丁应用测试：update/create/delete 全覆盖
- 回滚测试：模拟失败场景
- 白名单校验：越界文件拒绝应用
- 大小限制：超限回退全量

请先实现补丁应用 + 回滚机制，补丁生成作为 CI 后续实现。
```

---

## 提示词 15：音频解密与本地音乐管理（参考 Mineradio）

```
# 任务：为 AI-Omni 实现本地音乐管理与音频解密

## 背景
参考 Mineradio 的 qishui-audio-decryptor/ 目录（启天音乐解密）和本地音乐管理，
让 AI-Omni 支持本地音乐播放 + 加密音频解密。

## Mineradio 参考
- qishui-audio-decryptor/：启天音乐加密格式解密
- 本地音乐：MP3/FLAC 导入，内嵌歌词/封面
- dj-analyzer.js：播客/DJ 内容分析

## 需求

### 1. 本地音乐库管理
```python
class LocalMusicLibrary:
    # 扫描
    async def scan_directory(self, path: str) -> list[Song]: ...
    async def scan_file(self, file_path: str) -> Song: ...
    
    # 元数据
    async def read_metadata(self, file_path: str) -> Metadata: ...
    async def read_cover(self, file_path: str) -> bytes: ...
    async def read_lyrics(self, file_path: str) -> str: ...
    
    # 管理
    async def add_to_library(self, song: Song): ...
    async def remove_from_library(self, song_id: str): ...
    async def get_all_songs(self) -> list[Song]: ...
    async def search_local(self, keyword: str) -> list[Song]: ...
```

### 2. 支持格式
- MP3：ID3v2 标签 + USLT 歌词帧 + APIC 封面帧
- FLAC：Vorbis Comment + LYRICS 标签 + 封面
- WAV：基础播放（无元数据）
- M4A/AAC：iTunes 标签
- OGG：Vorbis Comment

### 3. 元数据读取（Python muteng 库）
```python
from mutagen import File
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.mp4 import MP4

def read_metadata(file_path):
    audio = File(file_path)
    return Metadata(
        title=audio.get('title', ['Unknown'])[0],
        artist=audio.get('artist', ['Unknown'])[0],
        album=audio.get('album', ['Unknown'])[0],
        duration=audio.info.length,
        bitrate=audio.info.bitrate,
        sample_rate=audio.info.sample_rate,
    )
```

### 4. 音频解密（参考 qishui-audio-decryptor）
- 支持加密格式：启天音乐（.qmc/.mflac/.mgg）
- 解密原理：参考 Mineradio 的 qishui-audio-decryptor 实现
- 解密后转为标准 FLAC/MP3
- 仅用于本地已购买音乐的格式转换
- 注意：不提供破解付费内容能力

```python
class AudioDecryptor:
    async def decrypt(self, input_path: str, output_path: str) -> str:
        """解密加密音频文件为标准格式"""
        # 检测格式
        # 调用对应解密器
        # 输出标准格式
```

### 5. 播客/DJ 分析（参考 dj-analyzer.js）
- 长音频检测（>10 分钟）
- 播客内容分析：语音段 vs 音乐段
- DJ 混音检测：BPM 变化曲线
- 影响 FieldStage 视觉模式选择

### 6. 音乐库索引
- SQLite 数据库（~/.ai-omni/music/library.db）
- 表结构：
  - songs: id, title, artist, album, duration, file_path, source, lyrics, cover_hash
  - playlists: id, name, song_ids, created_at
  - play_history: song_id, played_at, play_count
- 全文搜索：FTS5 索引 title/artist/album

### 7. 文件监听
- watchdog 监控本地音乐目录
- 新增文件自动入库
- 删除文件自动移除
- 文件修改更新元数据

### 8. Function Calling 工具
```python
tools = [
    {"name": "local_scan", "desc": "扫描本地音乐", "params": {"path": str}},
    {"name": "local_search", "desc": "搜索本地音乐", "params": {"keyword": str}},
    {"name": "local_play", "desc": "播放本地歌曲", "params": {"song_id": str}},
    {"name": "local_get_all", "desc": "获取全部本地音乐"},
    {"name": "local_create_playlist", "desc": "创建本地歌单", "params": {"name": str}},
    {"name": "local_add_to_playlist", "desc": "添加到歌单"},
]
```

### 9. 语音交互
- "维纳斯，扫描 D 盘音乐" → local_scan
- "维纳斯，播放本地周杰伦的歌" → local_search + local_play
- "维纳斯，创建一个歌单叫轻松" → local_create_playlist

### 10. 前端集成
- 本地音乐浏览界面（列表/网格视图）
- 文件夹选择器
- 扫描进度
- 元数据编辑

### 测试要求
- 多格式元数据读取测试
- 加密音频解密测试（如有测试样本）
- SQLite 索引测试
- 文件监听测试
- 覆盖率 ≥ 85%

请先实现本地音乐扫描 + 元数据读取 + 播放控制，再实现解密和分析功能。
```

---

## 使用建议

### 推荐实施顺序

| 阶段 | 提示词 | 说明 |
|---|---|---|
| 第一阶段 | 1 → 5 → 6 | 浮窗双态 + Agent 面板 + 协作规范（体验基础） |
| 第二阶段 | 2 → 3 | 插件 SDK + 系统辅助（架构基础） |
| 第三阶段 | 9 → 8 → 15 | 音乐源 + 歌词 + 本地音乐（核心功能） |
| 第四阶段 | 11 → 10 → 12 | 视觉增强 + 3D 歌单架 + 壁纸模式（视觉体验） |
| 第五阶段 | 13 → 4 → 7 → 14 | 天气 + i18n + 更新 + 补丁（生态完善） |

### 投喂方式
- 每次投喂一个提示词给 AI 编码助手
- 完成后再投喂下一个
- 提示词 2（插件 SDK）应在 3、9、13、15 之前完成（它们都依赖 SDK）
- 提示词 9（音乐源）应在 8、10、11 之前完成（它们依赖音乐播放）
