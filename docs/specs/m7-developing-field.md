# M7「显影场」The Developing Field — 无角色环境在场

> 2026-07-23 用户 directive：「当前的效果我并不喜欢，不要沿用桌宠这个效果了换个思路，不把你的项目参考设定死」。
> 本文档为 M7 里程碑规格，是各执行子 Agent 的统一契约。

## 一、方向

数字人角色路线（Live2D / OpenTalking）整体退役。AI 的在场不再有脸、没有框、没有常驻桌宠角落——**整块屏幕的透明覆盖层就是它的本体**。Film Atelier 走到逻辑终点：桌面即暗房，光是它。

- 平时：稀疏粒子近乎隐形的缓慢呼吸漂移，UI 完全退后
- 控制不常驻：鼠标滑入底部「声井」，粒子聚集成控制环，用完即散
- 字幕即内容：应答时场整体退场变暗，回复以显影字幕浮于下三分之一，纯排版

明确不做（YAGNI）：全局热键、窗口完全隐藏（防失锚，休眠=场调至近零+仅声井可交互）、GPU 节点 / OpenTalking 未来（M6.4 取消）、home/system 持久状态条。

## 二、窗口与分区交互底座（M7.1）

- **cover-display 窗口**：替代 `dock_bottom_right`。窗口覆盖主显示器可视区域（position 0,0 + visible frame size），保持既有契约：transparent / decorations:false / alwaysOnTop / skipTaskbar。**禁止** macOS fullscreen Space（会盖住桌面）。显示器变更时重新覆盖（监听 resize/scale 事件即可，不追求完美）。
- **分区交互**：`set_ignore_cursor_events` 是窗口级，无法按区分穿透，故采用 M4.1 预留方向——**Rust 鼠标位置轮询**：
  - 轮询线程（60–100ms）读全局鼠标位置（macOS CoreGraphics `CGEventGetLocation`，纯 position 无需辅助功能权限）；抽纯函数做决策，OS 调用压成薄适配层。
  - `decide_click_through(cursor, zones) -> bool`：cursor 落在任一 active zone 内 → false（可交互），否则 true（穿透）。
  - 去抖：结果不变不调用；切换最小间隔 100ms。
  - zones 由前端经 command `set_interactive_zones(zones: Vec<Rect>)` 下发（TS 按 DOM/状态计算，Rust 不硬编码布局）。Rect = {x, y, width, height}（窗口坐标系）。
- **休眠模式**：声井控制环的「睡眠」项 = 场透明度降至近零 + zones 清空只留声井；不隐藏窗口（防失锚，skipTaskbar 无 Dock 图标找不回）。
- 浏览器环境（vitest）所有新 invoke 静默降级（沿用 window.ts 既有模式）。

## 三、角色系统退役（M7.2）

**删除**（git 历史留档，不做兼容层）：
- `src/avatar/` 全部（OpenTalking client/bridge/store/config/types + subtitleStore 移至 `src/store/subtitleStore.ts` 保留——字幕逻辑复用）
- `src/live2d/` 全部（createAvatar / speakingDriver / modelAssets 测试）
- `src/components/`：`Live2DAvatar.tsx`、`AvatarDock.tsx`、`AvatarBackendSwitcher.tsx`、`StatusBar.tsx`、`ThemeSwitcher.tsx` 及各自测试（主题切换并入声井控制环）
- `public/models/`、`public/live2d/` 资产；package.json 移除 `pixi.js`、`pixi-live2d-display` 依赖
- `src/components/app-interactions.test.tsx`、`hud-layout.test.tsx` 按新骨架重写

**保留**：`src/space/`（M5 3D 引擎）、`src/particles/`（2D 降级）、`src/ripple/`、`src/motion/`、`src/theme/`、`src/data/`、`src/store/{statusStore,hudStore,visibility,statusRuntime}`、`src/components/{ImmersiveSpace,ParticleField,RippleLayer,AmbientLight,ui/Icon}`、Rust `status.rs` / `voice_watch.rs`（reply/reply_seq 数据通道继续供字幕）。

**新 App 骨架**（槽位组件，M7.2 建空壳保 build，M7.3/M7.4 填充）：
```tsx
<ImmersiveSpace />   // 既有 3D 粒子空间（全屏容器适配）
<FieldStage />       // 四态场语义层（M7.3）
<CaptionLayer />     // mono 状态标 + 显影字幕（M7.4）
<WellZone />         // 声井 + 召唤控制环（M7.4）
```

## 四、四态场语义（M7.3）

状态源：既有 `statusStore.voice.state`（wake_listening/recording/transcribing/thinking/speaking/idle）。

| 态 | 粒子行为 | 其他 |
|---|---|---|
| idle/不可用 | 既有稀疏漂移，亮度 ×0.5（休眠另乘 0.2） | 无 caption |
| wake_listening / recording | 声井位置泛开慢速大波纹（沿用 M5.3 波纹常量化约束），半径内粒子向井心倾向 + 提亮 ≤20% | caption「聆听」显影后 2.5s 渐隐 |
| transcribing / thinking | 井心周围缓速轨道流（角速度小、有界，禁快速旋转） | caption「思考」 |
| speaking | 场整体 dim 至 30%；底部边缘一条细波形流线（振幅有界） | 字幕显影（见 §五）；caption 不重复 |

约束红线不变：粒子数 high≤4000/medium≤2000/low≤800（fps 自动降档）；粒子不覆盖字幕与交互控件（speaking 时字幕区粒子密度趋零或字幕层 z-index 在上 + 场 dim）；每主题内容色 ≤6；禁高饱和/爆闪/快速频闪；尊重 `prefers-reduced-motion`（静态稀疏场，caption/字幕直显直隐）。

实现落点：`src/space/` 引擎扩展场语义参数（dim 系数、倾向点、轨道中心、流线开关），新 `src/field/fieldState.ts` 纯函数状态机（voice state → 场参数集）保证可测。

## 五、声井与字幕（M7.4）

**WellZone**：底部居中椭圆区（约 320×180，下缘贴屏）。hover（经 M7.1 分区可交互）→ 粒子聚集成控制环：
- 语音状态点（主题 accent 色，管道不可用为灰）
- 主题点（每主题一点，点击切换——并入 ThemeSwitcher 职能）
- 睡眠/唤醒切换
- 点击井心 → voice caption 卡（当前状态 + 最近回复摘要）显影/收起
hover 离开 → 环散开，恢复穿透。

**CaptionLayer**：
- 状态标：左上 mono 小字（胶片片头标风格），仅状态变更时显影，2.5s 渐隐
- 字幕：下三分之一居中，复用 `subtitleStore` 显影语义（chunk 累加、final 停留渐隐、blur→sharp 240ms）；无框无底条，纯排版 + 柔和文字阴影保可读
- speaking 时字幕区为 active zone：hover 右端聚集出打断方符（lucide `square`），点击 → Rust `voice_interrupt` command → 写控制文件（§六）

## 六、omni_voice 打断（M7.5）

常驻管道是独立进程，CLI 打断无法直达（W1 教训），故走**控制文件通道**（与状态文件对称的反向通道）：
- 新 `control_file.py`：`VoiceControlFile`，`DEFAULT_PATH = ~/.ai-omni/state/voice-control.json`；`interrupt()` 原子写 `{action:"interrupt", seq, ts}`（seq 实例内单调递增，初始化续号同 state_file 模式）；写失败静默降级。
- 管道帧循环每帧（或 ≤50ms 间隔）读控制文件：发现未消费的 interrupt → 停当前播放（player 抽象补 `stop()`，fake 后端记录调用）、迁移回 wake_listening、发 `voice.interrupted` 事件、状态文件照写。
- `voice_interrupt` tool（host 内调用同语义）+ CLI `python3 -m omni_voice interrupt`（写控制文件，供外部进程如 HUD Rust command 调用）。
- Rust：`voice_interrupt` command → spawn CLI（沿用 status.rs CLI 模式），TS `interruptSpeaking()` 封装。

## 七、测试与回归

- TDD 先行；全 fake 后端；vitest 新增/重写覆盖：fieldState 状态机、分区决策纯函数、控制环聚集/散开、字幕显影、interrupt 链路、休眠模式；cargo 覆盖 decide_click_through / 去抖 / zones 更新；pytest 覆盖控制文件读写容错、管道消费 interrupt、tool/CLI。
- 覆盖率 ≥80%（Python fail_under=80）。
- 全量回归：`python3 -m pytest` / `pnpm vitest run` / `cargo test` / `pnpm build` 全绿。
- 五件产出：代码 + TDD + 回归 + STATE.json + TEST_LOG.md（含真实输出）。
