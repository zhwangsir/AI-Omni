# AGENTS.md · AI-Omni Agent 协作规范

> 本文件约束所有参与 AI-Omni 开发的 Agent（主 Agent 与子 Agent）。代码风格细则见 [CLAUDE.md](CLAUDE.md)，环境搭建见 [PROJECT_INIT.md](PROJECT_INIT.md)。

## 一、子 Agent 团队工作模式

AI-Omni 采用**主 Agent 编排 + 子 Agent 执行**的团队模式：

1. **每个任务派发独立 subagent**。主 Agent 负责拆解任务、下发上下文、验收结果；具体实现（编码、测试、文档）由独立 subagent 完成。subagent 之间不共享工作区状态，所需上下文由主 Agent 在派发时一次性给足。
2. **两阶段 review**：
   - **阶段一 · 自验测试**：执行 subagent 在交付前必须自跑相关测试（`python3 -m pytest`，前端启用后含 `vitest run` 与 build），全部通过方可提交结果；交付报告中必须附测试输出摘要。
   - **阶段二 · reviewer 审计**：由独立的 reviewer subagent 对产出做审计——核对需求覆盖度、代码规范（[CLAUDE.md](CLAUDE.md)）、测试真实有效性（非空断言、非自我实现）、以及对既有功能的回归影响。审计不通过则退回执行 subagent 修复。
3. **禁止自审自批**：写代码的 subagent 不得兼任自己产出的 reviewer；reviewer 只审不改，发现问题退回而非代改。

## 二、里程碑工作流

每个里程碑 `M{N}`（含子任务 `M{N}.1`、`M{N}.2`……）必须按以下流程推进，**五件产出缺一不可**：

| # | 产出 | 要求 |
|---|------|------|
| 1 | **代码实现** | 符合 [CLAUDE.md](CLAUDE.md) 规范；只新增 `omni_*` 插件与本仓库代码，不改 WeBrain 核心 |
| 2 | **TDD 测试** | 测试先行（先写失败测试再实现）；覆盖率 ≥ 80%（`pyproject.toml` `fail_under = 80`） |
| 3 | **全量回归** | `python3 -m pytest` 全绿；前端启用后追加 `vitest run` 与 `build` 成功；记录实际输出 |
| 4 | **STATE.json 更新** | 新增 / 更新 `M{N}` 条目及全部子任务 `M{N}.1`、`M{N}.2`……，状态机：`pending → in_progress → completed` |
| 5 | **TEST_LOG.md 记录** | 按时间顺序追加条目：**含关键代码片段与真实测试结果输出**（命令 + 通过/失败数字 + 覆盖率），禁止只写"测试通过"一句话 |

里程碑关闭条件：五件产出齐备 + reviewer 审计通过。任一缺失，里程碑不得标记 `completed`。

## 三、TDD 纪律

1. **测试先行**：先写会失败的测试（red），再写最小实现使其通过（green），然后重构（refactor）。没有失败过的测试不算数。
2. **覆盖率 ≥ 80%**：`python3 -m pytest --cov=omni-brain/plugins/<plugin>` 低于 80% 视为里程碑未完成。
3. **测试独立性**：单元测试一律使用 fake 后端 / fake 依赖注入，**不得依赖音频硬件、GPU、真实模型文件、内网推理节点**；重型依赖缺失时测试也必须全绿（见 [CLAUDE.md](CLAUDE.md) 惰性导入约定）。
4. **断言真实**：禁止空测试、恒真断言、复制实现逻辑的镜像断言；reviewer 审计时重点核查。
5. **回归优先**：任何 bug 修复必须先补一条能复现该 bug 的失败测试，再修实现。

## 四、项目隔离纪律

> **历史背景**：WeBrain / Hermes 已弃用（见 `/Users/wangzhenyu/Desktop/ALLProject/.设备说明.md` §3.21），由 OpenClaw 网关（4 MacStudio + 4 MacMini :18789）替代。本节原 WeBrain/Hermes 引用已迁移至 OpenClaw。

1. **AI-Omni 与 OpenClaw 保持独立模块边界**。AI-Omni 通过 OpenClaw 网关（`ai.openclaw.gateway` launchd 服务，:18789）接入推理能力，不做源码级侵入；不直接调用已弃用的 WeBrain/Hermes 接口。
2. **OpenClaw 网关与其他项目代码不修改**。OpenClaw gateway 为集群共享资产，AI-Omni 任务中一律不改；发现 OpenClaw 缺陷时在本仓库记录并绕开，或提请用户在 OpenClaw 侧单独处理。
3. **只新增 `omni_*` 插件**。AI-Omni 侧的新能力统一落在 `omni-brain/plugins/omni_*/`，经 `register(ctx)` 挂载；其余复用资产（QieZiOS / flipped / LUVU / AIHub）同样只读复用、封装接入，不 fork、不重写。
4. **共用基础设施但不耦合**。OpenClaw 网关、EXO 集群、ComfyUI、NAS 等基础设施为共享资源，AI-Omni 以配置（endpoint / 凭据引用）方式消费；禁止把基础设施的地址、密钥硬编码进代码，禁止跨仓库 import。

## 五、提交规范

1. **不主动提交**：用户不明确要求时，**不执行 `git commit` / `git push`**；任务完成即停在工作区，向用户报告变更清单。
2. **Conventional Commits**：用户要求提交时，使用 Conventional Commits 格式——`feat:` / `fix:` / `docs:` / `test:` / `refactor:` / `chore:`，必要时带 scope（如 `feat(omni_voice): ...`）；提交信息用中文或英文均可，说明"为什么"而非罗列"改了什么"。
3. **提交前核对**：不提交密钥、`.env`、模型权重等大文件；不夹带与本任务无关的变更；提交前先全量回归。

---

## 六、集群依赖

本项目依赖 `/Users/wangzhenyu/Desktop/ALLProject/.设备说明.md` 中记录的集群资源：

| 依赖 | 设备 | 端口/路径 | 用途 |
|---|---|---|---|
| OpenClaw gateway | studio01-04 + openclaw01-04 | :18789 | Agent 执行 + 推理网关（替代已弃用的 WeBrain/Hermes） |
| Euryale 70B (vLLM) | spark01 (Ray head) + spark02 (worker) | http://192.168.71.82:8000 | 主推理后端，经 OpenClaw euryale provider 路由；spark02 不监听 :8000（Ray worker 正常行为） |
| EXO 集群 | studio01-04 | :52415 | 本地推理（GLM-5.2-fp8 / Kimi-K2.7-Code-4bit 按需加载） |
| ComfyUI-LB | Workstation (192.168.71.127) | :8188 | 文生图/视频（经 pc01:8188 / pc02:8193 扩展） |
| NAS SMB | NAS (192.168.71.7) | :445 (smb://192.168.71.7) | 共享存储 44TB |

**注意事项**:
- 不把基础设施地址/密钥硬编码进代码，通过环境变量/配置文件引用
- 项目隔离：不修改其他项目代码（OpenClaw / EXO / 其他 ALLProject 子项目）
- spark02 :8000 未监听是**正常行为**（Ray worker），所有推理请求一律走 spark01:8000

---

## 七、插件开发规范（M15 起）

> M15 正式化 `omni_sdk` 包（见 [transformation-plan-m12-m26.md](docs/specs/transformation-plan-m12-m26.md) §M15）。本章节定义新插件开发规范；M15 之前的 `register(ctx)` 契约见 [CLAUDE.md](CLAUDE.md) §二，通过适配层（`omni_sdk/compat.py`）继续兼容，迁移期间不破坏既有功能。

### 7.1 OmniPlugin 基类契约

所有 M15 起新增的 `omni_*` 插件必须继承 `omni_sdk.OmniPlugin`，实现以下 async 生命周期钩子：

- **`on_load(ctx: PluginContext) -> None`**：插件加载时调用，完成资源初始化、事件订阅、工具注册。失败抛 `PluginLoadError`，LifecycleHost 隔离错误不影响其他插件。
- **`on_unload() -> None`**：插件卸载时调用，释放资源（关闭 WebSocket / 文件句柄 / 音频流）。必须幂等，可被多次调用。
- **`on_event(event_type: str, payload: dict) -> None`**：事件总线分发回调，按订阅的 `event_type` 路由。

基类提供 `register_tools(ctx)` 默认实现（读取 manifest 声明的 `tools` 自动注册到 tool_registry），子类可覆盖以追加 `register_hook`。

### 7.2 manifest.json 格式

每个插件根目录必须有 `manifest.json`（替代 M15 前的 `plugin.yaml`，yaml 经迁移脚本兼容）：

```json
{
  "name": "omni_voice",
  "version": "0.1.0",
  "description": "语音交互管道（VAD/ASR/TTS/唤醒）",
  "author": "AI-Omni",
  "permissions": ["voice.listen", "fs.read:./state", "fs.write:./state", "tools.register"],
  "platforms": ["macos", "linux"],
  "dependencies": {"omni_sdk": ">=0.1.0"},
  "events": {
    "publishes": ["voice.state_changed", "voice.wake_detected", "voice.asr_final"],
    "subscribes": ["system.volume_changed"]
  },
  "tools": ["voice_status", "voice_listen", "voice_stop"]
}
```

字段约束：

- `name`：必须以 `omni_` 开头，全小写蛇形
- `permissions`：见 7.4
- `platforms`：`macos` / `linux` / `windows`，缺失视为全平台
- `dependencies`：插件间依赖，LifecycleHost 拓扑排序后加载

### 7.3 插件目录结构

```
omni-brain/plugins/omni_<name>/
├── __init__.py            # 暴露 OmniPlugin 子类（如 plugin = VoicePlugin）
├── manifest.json          # 元数据 + 权限 + 事件 + 工具声明
├── tools.py               # 工具 handler 实现（可选，可按域拆分）
├── backends/              # 后端实现（如 omni_voice/backends/ 的 VAD/ASR/TTS）
├── tests/
│   ├── __init__.py
│   ├── test_plugin.py     # 生命周期 + 权限 + 事件测试
│   └── test_tools.py      # 工具 handler 测试
└── README.md              # 可选，仅当插件对外发布
```

参考既有实现：`omni-brain/plugins/omni_voice/`（`pipeline.py` + `backends/` + `state_file.py` + `control_file.py` + `agent_bridge.py`）、`omni-brain/plugins/omni_home/`（`client.py` + `ws_sync.py` + `entities.py` + `nlu.py` + `knowledge.py`）。

### 7.4 权限声明

`manifest.json` 的 `permissions` 字段声明插件运行时所需能力，LifecycleHost 在 `on_load` 前校验：

| 权限 | 说明 | 示例 |
|------|------|------|
| `network` | 出站网络访问 | omni_home 调用 HA REST API |
| `voice.listen` | 麦克风采集 | omni_voice VoicePipeline 启动 |
| `home.control` | 智能家居设备控制 | omni_home 经 HA WebSocket 下发服务调用 |
| `fs.read:<path>` | 文件系统读 | omni_voice 读 state_file.json |
| `fs.write:<path>` | 文件系统写 | omni_voice 写 control_file.json |
| `tools.register` | 注册工具到 tool_registry | 所有插件必备 |

权限白名单宽松起步（D15.3 决策），运行时越权先日志告警而非直接拒绝，后续按需收紧。

### 7.5 事件总线命名规范

事件 `event_type` 统一 `<domain>.<event>` 点分小写：

| 域 | 示例事件 | 发布者 |
|----|----------|--------|
| `voice.*` | `voice.state_changed` / `voice.wake_detected` / `voice.asr_final` | omni_voice |
| `home.*` | `home.entity_changed` / `home.scene_applied` | omni_home |
| `music.*` | `music.started` / `music.paused` / `music.track_changed` | omni_music（M17） |
| `system.*` | `system.volume_changed` / `system.brightness_changed` / `system.locked` | omni_volume / omni_brightness / omni_power（M16） |

约束：

- `payload` 为可 JSON 序列化 dict，必须含 `timestamp`（ISO8601）与 `source`（插件 name）
- 跨插件订阅经 `ctx.event_bus.subscribe(event_type, handler)`，**禁止直接 import 其他插件模块**
- 事件总线实现见 `omni_sdk/event_bus.py`（M15）

### 7.6 工具命名规范

工具 `name` 统一 `<domain>_<action>` 蛇形小写：

| 域 | 示例工具 | 实现插件 |
|----|----------|----------|
| voice | `voice_status` / `voice_listen` / `voice_stop` | omni_voice |
| home | `home_list_entities` / `home_call_service` / `home_apply_scene` | omni_home |
| music | `music_play` / `music_pause` / `music_next` | omni_music（M17） |
| system | `system_set_volume` / `system_set_brightness` / `system_lock_screen` | omni_volume / omni_brightness / omni_power（M16） |

约束：

- 工具 handler 返回 JSON 字符串，结构 `{"ok": true, ...}` / `{"ok": false, "error": {"code": "E_XXX", "message": "..."}}`（沿用 register(ctx) 契约）
- `schema` 为 OpenAI function 风格 JSON Schema，参数必须有 `type` / `description` / `required`
- `emoji` 参数保留（Hermes CLI 展示契约，见 [CLAUDE.md](CLAUDE.md) §二），前端渲染不使用

### 7.7 生命周期管理

LifecycleHost（`omni_sdk/lifecycle.py`）按以下顺序启动插件：

1. **扫描**：遍历 `omni-brain/plugins/omni_*/`，读取 `manifest.json`
2. **加载**：按 `dependencies` 拓扑排序，逐个 `import` 插件模块
3. **依赖注入**：构造 `PluginContext`（config / event_bus / tool_registry / permission_checker / logger），传入 `on_load`
4. **注册**：基类 `register_tools` 默认实现读取 `manifest.tools` 注册到 tool_registry；子类可在 `on_load` 中追加 `ctx.register_hook`
5. **就绪**：发布 `plugin.loaded` 事件，插件进入运行态

卸载为反向流程：`on_unload` → 注销工具 → 取消事件订阅 → 释放资源。任一插件加载失败，LifecycleHost 记录日志并跳过，不阻塞其他插件（错误隔离）。

### 7.8 热加载说明

`omni_sdk` 提供 `LifecycleHost.reload(plugin_name)` API（D15.2 决策）：

- **M15 默认不启用热加载**——运行时热加载有状态不一致风险，先提供能力，后续按需开启
- **启用方式**：配置文件 `omni_sdk.hot_reload = true`，或环境变量 `OMNI_SDK_HOT_RELOAD=1`
- **触发机制**：监听 `manifest.json` 文件变更（watchdog），自动 `on_unload` → 重新 import → `on_load`
- **期间行为**：该插件的事件订阅暂停，进行中的工具调用返回 `E_PLUGIN_RELOADING`

---

## 端口配置

> 参考: /Users/wangzhenyu/Desktop/ALLProject/项目端口规划指南.md

| 服务 | 端口 | 说明 |
|------|------|------|
| omni-hud dev | 1420 | Tauri 默认，固定不变 |
| UniHub dev | 4702 | 子项目 |

端口段 47XX 专属 AI-Omni。
