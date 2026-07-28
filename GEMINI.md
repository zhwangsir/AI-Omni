# GEMINI.md · AI-Omni Gemini 协作配置

> 本文件为使用 Gemini 模型作为 AI-Omni 开发 Agent 时的特化配置。通用协作规范以 [AGENTS.md](AGENTS.md) 为准，代码风格以 [CLAUDE.md](CLAUDE.md) 为准；本文件仅补充 Gemini 特有能力与限制。环境搭建见 [PROJECT_INIT.md](PROJECT_INIT.md)。

## 一、适用场景

- 使用 Gemini 2.5 Pro / Flash 作为 AI-Omni 开发 Agent（主 Agent 或子 Agent）
- 经 OpenClaw 网关（`ai.openclaw.gateway` launchd 服务，:18789）路由的 Gemini 推理请求
- 涉及大规模代码审查、多模态 UI 设计稿分析、长文档消化等 Gemini 强项任务

## 二、Gemini 特有能力利用

### 2.1 长上下文窗口（100 万 token）

- **大规模代码审查**：可一次性载入 `omni-brain/plugins/` 全部插件源码 + 测试 + `manifest.json`，做跨插件一致性审查——命名规范（见 [AGENTS.md](AGENTS.md) §7.5 / §7.6）、权限声明闭环（§7.4）、事件订阅对齐（publishs 与 subscribes 匹配）、工具返回结构（`{"ok": true, ...}`）。
- **里程碑级回归分析**：载入 M14-M26 全部 spec 文档（`docs/specs/transformation-plan-m12-m26.md` 等）+ `STATE.json` + `TEST_LOG.md`，输出里程碑依赖图与风险点（如 M17 依赖 M15 SDK、M21 依赖 M17 音乐）。
- **长对话压缩**：跨多个 subagent 会话合并上下文时，Gemini 可直接消化完整对话历史，减少主 Agent 摘要失真。但需配合 `strategic-compact` 在阶段切换时主动压缩，避免无谓占用。

### 2.2 多模态能力

- **UI 设计稿分析**：Film Atelier 暗房风格（见 [CLAUDE.md](CLAUDE.md) §六）的设计稿（Figma 导出 / 截图）可直接喂给 Gemini，输出色板合规性、粒子密度、对比度评估。
- **omni-hud 截图审查**：Tauri 前端（端口 1420，见 [AGENTS.md](AGENTS.md) §端口配置）运行时截图，Gemini 识别 Film Atelier 风格偏离、Lucide 图标误用（见 [CLAUDE.md](CLAUDE.md) §五）、emoji 残留。
- **FieldStage / ImmersiveSpace 渲染帧分析**：M5 沉浸式空间（见 [m5-immersive-space.md](docs/specs/m5-immersive-space.md)）的 WebGL 帧截图，评估粒子数（high ≤ 4000 / medium ≤ 2000 / low ≤ 800）与每主题内容色种类（≤ 6）。

## 三、MCP（Model Context Protocol）集成

AI-Omni 的 MCP 工具集成经 OpenClaw 网关路由，Gemini Agent 可通过以下 MCP server 消费 AI-Omni 能力：

| MCP server | 能力 | 实现位置 | 用途 |
|------------|------|----------|------|
| `omni_voice` 状态文件监听 | 文件变更通知 | `omni-brain/plugins/omni_voice/state_file.py` + `control_file.py` | 监听语音管道状态（IDLE/LISTENING/THINKING/SPEAKING）变化 |
| `omni_home` HA WebSocket | Home Assistant 实时事件 | `omni-brain/plugins/omni_home/ws_sync.py` + `client.py` | 订阅实体状态变化、场景应用事件 |
| `omni_music` 播放控制 | 媒体播放器控制 | `omni-brain/plugins/omni_music/`（M17 起提供） | play / pause / next / seek、当前曲目查询 |

Gemini Agent 调用 MCP 工具时：

- 工具 schema 必须显式声明（见 §四 限制），不假设未声明的参数
- 返回值遵循 AI-Omni 统一结构 `{"ok": true, ...}` / `{"ok": false, "error": {"code": "E_XXX", "message": "..."}}`（见 [CLAUDE.md](CLAUDE.md) §二）
- 长时间运行的操作（如 `voice_listen`）通过事件总线异步通知完成（事件命名见 [AGENTS.md](AGENTS.md) §7.5），不阻塞 MCP 调用本身

## 四、Gemini 限制注意事项

1. **函数调用需明确 schema**：Gemini 的 function calling 对 JSON Schema 严格性要求高于其他模型——所有参数必须有 `type` / `description`，枚举值必须用 `enum` 声明，可选参数必须标 `required` 数组。`omni_sdk` 注册工具时 schema 不完整会被 Gemini 拒绝。
2. **不假设未提供的参数**：Gemini 不会为缺失参数填充默认值——`tools.register` 时 handler 必须显式处理 `None` 入参，不能依赖模型补全。
3. **中文 prompt 优先**：AI-Omni 的 docstring、错误消息、用户交互均为中文（见 [CLAUDE.md](CLAUDE.md) §一.2），Gemini 的 system prompt 与 few-shot 示例统一用中文，避免中英混杂导致风格漂移。
4. **长上下文不代表无成本**：载入全量代码做审查时，仍需在 prompt 中明确审查清单（命名规范 / 权限 / 事件闭环 / 返回结构），否则 Gemini 容易泛泛而谈。建议配合 `iterative-retrieval` 模式分批检索而非一次性载入。
5. **多模态输入需指定 media_type**：截图喂给 Gemini 时必须显式声明 `media_type`（`image/png`），且分辨率过高时先降采样（单边 > 2048px 降为 2048），避免触发 token 上限。

## 五、与 OpenClaw 网关的集成

Gemini 推理请求经 OpenClaw 网关路由（替代已弃用的 WeBrain/Hermes，见 [AGENTS.md](AGENTS.md) §四）：

- **endpoint**：`ai.openclaw.gateway` launchd 服务，:18789（见 [AGENTS.md](AGENTS.md) §六 集群依赖）
- **provider 路由**：OpenClaw 的 gemini provider 转发到 Google AI API，AI-Omni 侧不直接持有 Google API key（凭据由 OpenClaw 集群统一管理，符合 [AGENTS.md](AGENTS.md) §四.4 不硬编码基础设施凭据）
- **请求格式**：OpenAI 兼容（`/v1/chat/completions`），工具调用走 OpenAI function calling 风格——`omni_sdk` 注册的工具 schema（见 [CLAUDE.md](CLAUDE.md) §2.1）可直接透传
- **限流**：OpenClaw 网关侧统一限流，AI-Omni 不实现本地限流；遇到 429 时由 OpenClaw 重试，AI-Omni 侧 handler 返回 `E_BACKEND_UNAVAILABLE`
- **隐私边界**：Gemini 请求经 OpenClaw 网关时，敏感数据不外传——`omni_voice` 的 ASR/TTS 同样走 OpenClaw 网关 OpenAI 兼容端点（`/v1/audio/transcriptions`、`/v1/audio/speech`），音频不出内网；仅文本摘要可经 OpenClaw 路由到 Gemini；`omni_home` 的设备 token / 实体 ID 脱敏后再送推理

## 六、与其他规范文件的关系

| 文件 | 适用范围 | 优先级 |
|------|----------|--------|
| [AGENTS.md](AGENTS.md) | 所有 Agent（含 Gemini）的协作流程、里程碑、TDD、隔离纪律 | 强制 |
| [CLAUDE.md](CLAUDE.md) | 所有 Agent 的代码风格、插件开发规范、UI 约束、测试要求 | 强制 |
| 本文件（GEMINI.md） | Gemini 模型特有的能力利用、限制、MCP 集成 | 补充 |

冲突时以 [AGENTS.md](AGENTS.md) / [CLAUDE.md](CLAUDE.md) 为准；本文件仅在不冲突的前提下补充 Gemini 特化配置。
