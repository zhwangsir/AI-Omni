# AI-Omni · 项目初始化文档

> 更新日期: 2026-07-20 | 状态中枢: [STATE.json](STATE.json) | 测试日志: [TEST_LOG.md](TEST_LOG.md)

## 一、项目基本信息

| 字段 | 值 |
|------|----|
| 项目名称 | AI-Omni（本地大脑 + 插件化能力的 AI 全能助手） |
| 当前阶段 | Phase 1 — 语音交互 MVP（`current_phase: 1`，`current_milestone: M1`） |
| 创建日期 | 2026-07-20 |
| 项目路径 | /Users/wangzhenyu/Desktop/ALLProject/AI-Omni |
| 技术栈 | Python 后端 + Tauri/Rust 桌面壳 + React/Svelte 前端 |
| 决策大脑 | 复用 WeBrain (Hermes)：`/Users/wangzhenyu/Desktop/ALLProject/WeBrain/webrain-core/` |
| 执行网关 | 复用 OpenClaw |
| Python | ≥ 3.11（当前开发机 3.14.6，pytest 9.1.1） |
| 测试框架 | pytest + pytest-cov，覆盖率门槛 ≥ 80%（`pyproject.toml` `fail_under = 80`） |

## 二、目录结构及各部分职责

```
AI-Omni/
├── omni-brain/               # Python 后端：决策大脑宿主，所有 omni_* 插件的存放根
│   └── plugins/
│       └── omni_voice/       # Phase 1 语音插件（plugin.yaml + register(ctx)）
├── omni-hud/                 # 交互呈现层前端（React/Svelte，Phase 3 启用，复用 QieZiOS 基座）
├── omni-desktop/             # Tauri / Rust 桌面壳（Phase 3 启用，复用 flipped）
├── omni-storage/             # 数据存储层服务：记忆 / 文件 / 备份（Phase 2+ 启用）
├── docs/
│   └── specs/                # 各 Phase 设计文档（phase1-voice-mvp.md 等）
├── tests/                    # pytest 测试套件：全部 fake 后端，无硬件依赖
├── scripts/                  # 开发 / 运维脚本（模型预下载、回归脚本等）
├── STATE.json                # 项目状态中枢：阶段、里程碑、约束、上游资产、模型后端
├── TEST_LOG.md               # 测试日志：按时间记录每个里程碑的测试执行情况
├── pyproject.toml            # 项目元数据 + pytest / coverage 配置
├── README.md                 # 项目门面
├── PROJECT_INIT.md           # 本文件
├── AGENTS.md                 # Agent 协作规范
├── CLAUDE.md                 # 代码规范
└── UniHub/                   # 历史 uni-app 参考资产（只读，不参与构建，勿改）
```

职责要点：

- **`omni-brain/plugins/omni_*/`**：AI-Omni 唯一的新增代码形态。所有能力（语音、家居、自动化……）都是挂到 WeBrain Hermes 插件机制上的 `omni_*` 插件，不改 WeBrain 核心。
- **`tests/`**：pytest 主测试目录（`pyproject.toml` 中 `testpaths = ["tests", "omni-brain/plugins"]`）。测试只允许使用 fake 后端，禁止触碰音频硬件 / GPU / 网络模型下载。
- **`STATE.json` / `TEST_LOG.md`**：每个里程碑必须同步更新，见 [AGENTS.md](AGENTS.md) 里程碑工作流。

## 三、开发环境搭建

### 3.1 基础环境（开发与测试）

```bash
# 需要 Python 3.11+
python3 --version          # 当前开发机: Python 3.14.6

# 安装测试依赖
pip install pytest pytest-cov

# 验证
python3 -m pytest --version   # 当前: 9.1.1
```

基础环境即可运行**全部单元测试与集成测试**——所有重型后端在测试中均由 fake 实现替换。

### 3.2 可选音频依赖（仅真机运行时需要）

以下依赖**只在真实设备上运行语音功能时**才需要安装；单元测试一律使用 fake，不安装也能全量通过：

| 依赖 | 用途 |
|------|------|
| `sounddevice` | 麦克风采集 / 扬声器播放 |

```bash
# 仅在真机运行时安装
pip install sounddevice
```

> ASR / TTS / LLM 推理统一经 OpenClaw 网关（`:18789`）OpenAI 兼容端点接入
> （`/v1/audio/transcriptions`、`/v1/audio/speech`、`/v1/chat/completions`），
> AI-Omni 不自行加载本地模型（[AGENTS.md](AGENTS.md) §四 项目隔离纪律）；
> VAD 为纯 Python 能量检测（`backends/energy_vad.py`），零第三方依赖。

代码侧约定：`sounddevice` 一律**惰性导入且可缺省**（见 [CLAUDE.md](CLAUDE.md)），缺失时插件降级返回错误码而不是崩溃。

## 四、如何运行测试

```bash
# 全量测试（tests/ 与 omni-brain/plugins/ 下所有 test_*.py）
python3 -m pytest

# 带覆盖率报告（门槛 80%，低于即失败）
python3 -m pytest --cov=omni-brain/plugins/omni_voice --cov-report=term-missing

# 跑单个测试文件 / 单个用例
python3 -m pytest tests/omni_voice/test_state_machine.py -v
python3 -m pytest tests/omni_voice/test_state_machine.py::test_wake_to_recording -v
```

配置位置（`pyproject.toml`）：

- `testpaths = ["tests", "omni-brain/plugins"]`
- `addopts = "-v --tb=short"`
- `[tool.coverage.report] fail_under = 80, show_missing = true`

前端启用后（Phase 3），全量回归还需追加 `vitest run` 与构建验证，见 [AGENTS.md](AGENTS.md) 全量回归要求。

## 五、如何新增一个 omni_* 插件

AI-Omni 的插件机制完全复用 WeBrain Hermes 的插件注册机制（参考 `webrain-core/plugins/` 与 `webrain_loop_engine` 的加载模式），**不重写、不fork**。

### 5.1 目录骨架

以 `omni_example` 为例：

```
omni-brain/plugins/omni_example/
├── plugin.yaml          # 插件元数据（必需）
├── __init__.py          # 暴露 register(ctx)（必需）
├── tools.py             # tool schema 与 handler 实现
└── ...                  # 其余模块按需拆分
```

### 5.2 plugin.yaml

```yaml
name: omni_example
version: 0.1.0
description: "示例插件：演示 omni_* 插件的标准骨架"
author: AI-Omni
kind: backend
provides_tools:
  - example_ping
```

### 5.3 __init__.py 暴露 register(ctx)

```python
"""omni_example 插件 —— register(ctx) 是插件加载器唯一入口。"""

from __future__ import annotations

from omni_example.tools import EXAMPLE_PING_SCHEMA, _handle_example_ping


def register(ctx) -> None:
    """注册插件的全部 tools 与 hooks。由插件加载器调用一次。"""
    ctx.register_tool(
        name="example_ping",
        description="连通性测试：原样返回入参",
        emoji="📡",
        schema=EXAMPLE_PING_SCHEMA,
        handler_func=_handle_example_ping,
    )
    # 如需订阅事件总线钩子：
    # ctx.register_hook("on_turn_end", _on_turn_end)
```

契约要点（详见 [CLAUDE.md](CLAUDE.md)）：

- `register(ctx)` 是插件唯一入口，由 WeBrain 插件加载器调用一次。
- `ctx.register_tool(name, description, emoji, schema, handler_func)` 注册工具；**handler 必须返回 JSON 字符串**（`json.dumps(..., ensure_ascii=False)`），错误统一为 `{"ok": false, "error": {"code": ..., "message": ...}}`。
- `ctx.register_hook(name, func)` 订阅事件总线钩子（S5 `loop_engine`）。
- 插件命名必须为 `omni_*`；tool 命名建议 `<域>_<动作>`（如 `voice_status`、`home_light_set`）。
- 线程安全单例直接使用 WeBrain `plugins/plugin_utils.py` 的 `lazy_singleton` / `SingletonSlot`（双重检查锁），不要手搓。

### 5.4 配套测试（TDD，先行编写）

```
tests/omni_example/
├── __init__.py
├── conftest.py            # fake 依赖 fixture
└── test_tools.py          # handler JSON 契约测试
```

新增插件的完成定义：测试先行 → 实现 → `python3 -m pytest` 全绿 → 覆盖率 ≥ 80% → 更新 STATE.json / TEST_LOG.md。

## 六、快速验证清单（M0 核对结果）

| # | 检查项 | 状态 |
|---|--------|------|
| 1 | 目录结构创建完成（omni-brain / omni-hud / omni-desktop / omni-storage / docs / tests / scripts） | ✅ 已完成 |
| 2 | STATE.json 创建（阶段 / 里程碑 / 约束 / 上游资产 / 模型后端） | ✅ 已完成 |
| 3 | 根配置文件（README / PROJECT_INIT / AGENTS / CLAUDE） | ✅ 已完成 |
| 4 | Phase 1 设计文档 `docs/specs/phase1-voice-mvp.md` | ✅ 已完成 |
| 5 | WeBrain webrain-core 路径可访问，插件机制确认（`plugin.yaml` + `register(ctx)`，`ctx.register_tool` / `ctx.register_hook`） | ✅ 已确认 |
| 6 | Python 3.11+ 与 pytest 可用（3.14.6 / 9.1.1） | ✅ 已验证 |
| 7 | pytest 冒烟测试（待 M1 测试写入后执行） | ⏳ 待 M1.5 |

> 清单与 [STATE.json](STATE.json) `M0` 子任务一一对应；任何一项状态变化必须同步更新 STATE.json。
