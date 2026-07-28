# CLAUDE.md · AI-Omni 代码规范

> 本文件为在本仓库工作的 AI 编码 Agent 提供代码规范。协作流程见 [AGENTS.md](AGENTS.md)，环境搭建见 [PROJECT_INIT.md](PROJECT_INIT.md)。

## 项目速览

AI-Omni = 本地大脑 + 插件化能力的 AI 全能助手。Python 后端（`omni-brain/`）以 `omni_*` 插件挂载到 WeBrain (Hermes) 插件机制上；前端（Phase 3 起）为 Tauri/Rust 壳 + React/Svelte。隐私优先，核心数据全部本地运行。**WeBrain 核心代码只读不改**，所有新能力以插件形式新增。

---

## 一、Python 代码风格

1. **类型注解**：所有公开函数 / 方法的参数与返回值必须有类型注解；模块顶部统一 `from __future__ import annotations`。
2. **docstring 中文**：模块、类、公开函数必须写中文 docstring，说明"做什么、为什么"，不堆砌显而易见的描述。
3. **import 顺序**：标准库 → 第三方库 → 本地模块，每组之间空一行；组内按字母序；禁止 `import *`。
4. **线程安全单例**：`threading` 单例一律使用**双重检查锁**；直接复用 WeBrain `webrain-core/plugins/plugin_utils.py` 提供的 `lazy_singleton` 装饰器（零参工厂场景）与 `SingletonSlot`（带构建参数场景），不要手搓锁逻辑。
5. 兼容 Python ≥ 3.11（当前开发机 3.14）；禁止使用 3.11 之前的兼容层写法。

## 二、插件开发规范（register(ctx) 契约）

每个 `omni_*` 插件 = `plugin.yaml` + `__init__.py` 暴露的 `register(ctx)`，由 WeBrain 插件加载器调用一次：

```python
def register(ctx) -> None:
    ctx.register_tool(
        name="voice_status",          # tool 名：<域>_<动作>
        description="查询语音管道状态",  # 中文描述
        emoji="🎙️",                    # Hermes CLI 展示用（沿用 WeBrain 惯例）
        schema=VOICE_STATUS_SCHEMA,   # JSON Schema（OpenAI function 风格）
        handler_func=_handle_status,  # 处理函数
    )
    ctx.register_hook("on_turn_end", _on_turn_end)  # 订阅事件总线钩子
```

- **`ctx.register_tool(name, description, emoji, schema, handler_func)`**：`schema` 为 JSON Schema dict；**handler 必须返回 JSON 字符串**——`json.dumps(result, ensure_ascii=False)`。
- **返回结构统一**：成功 `{"ok": true, ...}`；失败 `{"ok": false, "error": {"code": "E_XXX", "message": "..."}}`。handler 内部捕获全部异常，不向加载器抛错。
- **`ctx.register_hook(name, func)`**：注册事件钩子，挂到 S5 `loop_engine` 事件总线。
- 插件只依赖 ctx 注入的能力与显式配置，**禁止跨仓库 import WeBrain 内部模块**。

> 注意：`register_tool` 的 `emoji` 参数是 Hermes CLI 展示契约的一部分（WeBrain 惯例），与下方"前端 UI 禁用 emoji 图标"不冲突——前者是插件元数据，后者是前端渲染约束。

### 2.1 OmniPlugin 基类（M15 起）

> M15 起 `omni_sdk` 包正式化（见 [transformation-plan-m12-m26.md](docs/specs/transformation-plan-m12-m26.md) §M15）。新插件必须继承 `OmniPlugin`；现有 `register(ctx)` 契约（见上文 §二）通过 `omni_sdk/compat.py` 适配层继续兼容，迁移期间不破坏既有功能。协作流程层面的规范见 [AGENTS.md](AGENTS.md) §七。

#### 基类骨架

```python
from __future__ import annotations

from typing import Any

from omni_sdk import OmniPlugin, PluginContext


class VoicePlugin(OmniPlugin):
    """omni_voice 插件实现：语音管道（VAD/ASR/TTS/唤醒）。"""

    name = "omni_voice"
    version = "0.1.0"

    async def on_load(self, ctx: PluginContext) -> None:
        """加载时构造 VoicePipeline，订阅事件，注册工具。"""
        self.ctx = ctx
        # VoicePipeline 的 ASR/TTS/LLM 经 OpenClaw 网关接入（见 §三）
        self.pipeline = VoicePipeline(config=ctx.config)
        await ctx.event_bus.subscribe("system.volume_changed", self._on_volume_changed)
        await self.register_tools(ctx)  # 基类默认实现，读取 manifest.tools

    async def on_unload(self) -> None:
        """卸载时关闭管道，幂等。"""
        if self.pipeline is not None:
            await self.pipeline.stop()
        self.pipeline = None

    async def on_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """事件路由。"""
        if event_type == "system.volume_changed":
            await self._on_volume_changed(payload)

    async def _on_volume_changed(self, payload: dict[str, Any]) -> None:
        """系统音量变化时调整 TTS 输出增益。"""
        ...
```

#### PluginContext 注入能力清单

`PluginContext` 由 LifecycleHost 构造并注入 `on_load`，提供以下能力：

| 属性 | 类型 | 说明 |
|------|------|------|
| `config` | `dict[str, Any]` | 插件配置（来自全局配置文件的 `plugins.omni_<name>` 段） |
| `event_bus` | `EventBus` | 事件总线，`publish(event_type, payload)` / `subscribe(event_type, handler)` |
| `tool_registry` | `ToolRegistry` | 工具注册器，`register(name, description, emoji, schema, handler_func)` |
| `permission_checker` | `PermissionChecker` | 运行时权限校验，`check("voice.listen")` 返回 bool |
| `logger` | `logging.Logger` | 插件专属 logger，命名空间 `omni.<plugin_name>` |

#### manifest.json 示例

```json
{
  "name": "omni_voice",
  "version": "0.1.0",
  "description": "语音交互管道（VAD/ASR/TTS/唤醒）",
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

字段语义与权限清单详见 [AGENTS.md](AGENTS.md) §7.2 / §7.4。

#### 与现有 register(ctx) 的兼容说明

- **M15 前的插件**（`omni_voice`、`omni_home`）保留 `plugin.yaml` + `register(ctx)` 入口，通过 `omni_sdk/compat.py` 适配层包装为 `OmniPlugin` 子类实例
- **迁移策略**：渐进式重构，先让适配层托管 `register(ctx)`，再逐步将生命周期逻辑迁移到 `on_load` / `on_unload`；迁移过程中全量回归必须保持 537 passed（见 M15 成功标准）
- **新插件**（M16 起 `omni_volume` / `omni_brightness` / `omni_power` 等）必须直接继承 `OmniPlugin`，不再使用 `register(ctx)` 入口
- **重型依赖惰性导入约定不变**（见 §三）：`on_load` 中构造 `VoicePipeline` 等后端时，`sounddevice` 等硬件依赖仍需函数内 / 工厂方法内 import；ASR/TTS/LLM 已统一走 OpenClaw 网关，不再本地加载推理模型

#### 插件脚手架命令

```bash
# 生成新插件骨架（M15 起提供）
python3 -m omni_sdk create omni_music
# 产出：
#   omni-brain/plugins/omni_music/
#   ├── __init__.py          # class MusicPlugin(OmniPlugin) 骨架
#   ├── manifest.json        # 模板（含 music.* 事件占位）
#   ├── tools.py             # 工具 handler 骨架
#   └── tests/
#       ├── test_plugin.py   # 生命周期测试骨架
#       └── test_tools.py    # 工具测试骨架
```

脚手架默认填入 `permissions: ["tools.register"]`、`platforms: ["macos"]`，开发者按需扩展。生成后需按本规范 §七（TDD）先补失败测试再实现。

## 三、重型依赖：惰性导入且可缺省

> 2026-07-28 起 ASR/TTS/LLM 统一经 OpenClaw 网关（`:18789`）OpenAI 兼容端点接入（[AGENTS.md](AGENTS.md) §四），本地不再加载推理模型；VAD 为纯 Python 能量检测（`backends/energy_vad.py`），零第三方依赖。历史重型推理依赖（`torch` / `faster-whisper` / `silero-vad` / `kokoro` / `openwakeword` / `llama-cpp-python`）已移除。

`sounddevice` 等重型 / 硬件相关依赖（以及未来新增的任何重型 / 硬件依赖）：

1. **惰性导入**：只在真正使用它们的函数 / 后端构建时 import（函数内 import 或工厂方法内 import），禁止模块顶层 import。
2. **可缺省**：`ImportError` 时必须降级为返回 `E_BACKEND_UNAVAILABLE` 错误（或跳过该后端），不允许让插件加载失败、不允许拖垮整个 `python3 -m pytest`。
3. **测试零依赖**：单元测试与集成测试**全部使用 fake 后端**（依赖注入替换 VAD / ASR / TTS / 唤醒 / 音频采集），不得触碰音频硬件、不得下载模型、不得访问内网推理节点。CI 与开发机不装音频依赖也必须全绿。

## 四、核心接口约定

插件与 WeBrain 大脑交互统一走以下接口（由宿主 / ctx 注入，签名为约定契约）：

### 4.1 事件总线（S5 loop_engine）

```python
event_publish(event_type: str, payload: dict) -> None
```

- `event_type` 用点分小写命名（如 `voice.state_changed`、`voice.wake_detected`）；`payload` 为可 JSON 序列化的 dict。
- 订阅侧经 `ctx.register_hook(name, func)` 挂载。

### 4.2 记忆系统（S3 context_engine，L1-L4）

```python
memory_store(content: str, layer: str, importance: float) -> str   # 返回记忆 id
memory_retrieve(query: str, layers: list[str]) -> list[dict]
```

- `layer` ∈ `L1`（会话级）/ `L2`（日归档）/ `L3`（主题聚合）/ `L4`（永久知识）；`importance` ∈ [0, 1]。
- 语音交互产生的对话默认写 `L1`，重要性 ≥ 0.8 的由大脑侧晋级，插件不直接写 L4。

### 4.3 目标规划

```python
goal_plan(goal: str, category: str) -> dict   # 返回分解后的子目标 / 计划结构
```

- `category` 用稳定枚举值（如 `home`、`office`、`media`），便于规划器路由。

## 五、图标规范（前端）

1. **Lucide React 是唯一图标源**。统一经 `components/ui/Icon.tsx` 封装后使用，业务代码不直接散布 `lucide-react` import。
2. **禁止**：用 emoji 当图标、引入其他图标库（fontawesome / iconfont / antd icons 等）、手写自定义 SVG 图标。Lucide 没有的新图标需求，先在 `Icon.tsx` 登记并提请确认。
3. `Icon.tsx` 统一控制尺寸、描边宽度、颜色 token，保证全站一致。

## 六、UI 设计约束（Film Atelier 暗房风格）

1. **风格基调**：Film Atelier 暗房风格——深色背景、低亮度环境光、胶片质感与显影意象；整体克制、安静、专业。
2. **动画**：克制而有**物理感与呼吸感**——缓动自然（spring / ease-out），时长偏短，避免无休止的高频动效；交互反馈点到为止。
3. **粒子系统约束（M5 起，GPU 分档）**：同屏粒子按画质档 **high ≤ 4000 / medium ≤ 2000 / low ≤ 800**（fps 自动降档）；流速振幅常量化有界、保留呼吸感；每主题内容色 **≤ 6 种**；粒子**不得覆盖文字与可交互控件**。（M4 及之前的 2D canvas 旧约束 ≤300/≤1.2/≤5 已由 [m5-immersive-space.md](docs/specs/m5-immersive-space.md) 取代，2D 引擎仅作 WebGL 失败降级。）
4. **明确禁止**：高饱和彩虹配色、大面积闪烁、粒子爆炸效果、快速频闪（光敏风险与风格双重红线）。
5. 可用性底线：动效不得牺牲可读性与对比度；文字与背景对比度满足可读标准；尊重系统 `prefers-reduced-motion`。

## 七、测试要求速查

- 运行：`python3 -m pytest`（配置见 `pyproject.toml`，`testpaths = ["tests", "omni-brain/plugins"]`）。
- 覆盖率门槛 **≥ 80%**（`fail_under = 80`）。
- 测试全部 fake 后端；TDD 测试先行；bug 修复先补复现测试。细则见 [AGENTS.md](AGENTS.md)。
