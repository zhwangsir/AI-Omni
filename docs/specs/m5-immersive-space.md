# M5：HUD 视效重构 —— 3D 沉浸粒子空间

> 版本：v1.0 | 日期：2026-07-21 | 状态：已批准（用户 directive：抛开原有架构限制，把效果推到最好）
> 前置：M4 已完成（omni-hud 骨架/Live2D/三通道状态/Film Atelier 2D 视觉）
> 本里程碑**替换视觉底层**，保留窗口契约、StatusBar、Live2D 数字人、statusStore 数据通道（M5.4 除外）。

## 一、目标与设计哲学

把 HUD 从「2D canvas 粒子背景」升级为「3D 沉浸式粒子空间」：粒子有真实深度、相机随鼠标视差、GPU 后处理氛围（bloom/暗角/胶片颗粒），数字人悬浮于星尘之中。用户 directive：技术架构约束全部松绑；**审美红线继续死守**。

### 审美红线（不可触碰，reviewer 逐项核对）

- 禁止高饱和彩虹配色、大面积闪烁、粒子爆炸、快速频闪
- 禁止磨砂玻璃（backdrop-filter blur）、纯白背景
- 必须有暗角（vignette）与景深层次
- 粒子/波纹/光效层不得遮挡文字与交互控件（z-index + pointer-events）
- 动画以 spring/ease-out、慢呼吸为主，交互反馈点到为止
- `prefers-reduced-motion`：全场景静止降级

### 技术约束松绑（旧 → 新）

| 项 | M4 旧约束（2D canvas） | M5 新约束（GPU） |
|---|---|---|
| 粒子数 | ≤300 | 按画质档：high 4000 / medium 2000 / low 800，fps 自动降档 |
| 速度 | ≤1.2 px/frame | 世界单位流速有界（flow amplitude 常量化，保留呼吸感） |
| 色彩 | PALETTE ≤5 | 每主题 ≤6 内容色，模块加载硬校验 |
| 渲染 | 2D canvas | Three.js WebGL（Soft sprite + bloom = 自然 bokeh 景深） |

## 二、架构

```
omni-hud/src/
  space/                      # M5 新增：3D 空间层（纯 TS，three 全部经此层收口）
    createSpace.ts            # 场景装配：renderer/scene/camera/composer/循环/resize/dispose
    quality.ts                # 画质档 tiers + fps 监控自动降档（纯逻辑）
    particles.ts              # GPU 实例化粒子（InstancedBufferGeometry + ShaderMaterial）
    flowfield.ts              # 流场位移（vertex shader 内 noise，零 CPU 成本）
    attractor.ts              # 鼠标吸引子/聚集（uniform 驱动 + 阻尼钳制）
    shapes.ts                 # 聚集目标形状点云生成（球壳/环/星等，纯逻辑）
    ripples.ts                # shader 水波纹队列（uniform array，max 并发，慢速大范围）
    mood.ts                   # 语音状态 → 场景氛围映射（idle/speaking 活跃度）
    postfx.ts                 # EffectComposer：Bloom + 自定义 pass（vignette+grain）
  components/
    ImmersiveSpace.tsx        # 替代 ParticleField：canvas 挂载 + 懒加载 three + 降级
  particles/                  # M4 的 2D 引擎：保留文件但不再挂载（M5.3 完成后删除）
```

- **three 版本锁定**，不用 react-three-fiber（保持手卷引擎风格与可测性）
- **懒加载**：`ImmersiveSpace` 动态 `import('./space/createSpace')`，首屏 bundle 不进 three
- **WebGL 失败降级**：context 创建失败 → 回退 M4 的 2D ParticleField（保留即为此）
- **双层 WebGL 共存**：pixi（Live2D）与 three（空间）各自 canvas，z-index 分层

## 三、子任务

### M5.1 Three.js 场景底座
- `quality.ts`：tiers 定义（4000/2000/800）、fps 滚动均值自动降档（<50 降、>58 持续升）、手动覆盖；纯逻辑可测
- `createSpace.ts`：renderer（alpha、antialias 按档）、perspective 相机、相机 rig（鼠标 → 目标旋转 lerp 0.04~0.08 缓动）、resize、dispose 幂等
- `postfx.ts`：Bloom（克制强度）+ 自定义 shader pass（vignette + 静态 film grain，**禁闪烁**）
- reduced-motion：渲染循环冻结为单帧静态
- 测试：mock three；quality 降档/升档逻辑、相机 lerp 数学、主题接入、dispose 幂等

### M5.2 GPU 粒子系统
- `particles.ts`：InstancedBufferGeometry + ShaderMaterial；实例属性：种子位置/速度/尺寸/色相索引/相位；soft radial sprite 纹理（程序生成）
- `flowfield.ts`：vertex shader 伪 noise 位移，振幅常量化有界（呼吸感，不快闪）
- `attractor.ts`：uniform vec3 + strength；指针 unproject 到世界坐标、平滑跟随；强度钳制、近距阻尼，禁止爆粒
- `shapes.ts`：形状目标点云生成器（球壳/环/双锥等 ≥3 种），attribute 上传 + morphFactor lerp
- 主题绑定：色板 → uniform 数组（≤6），主题切换平滑过渡（色彩 lerp ~260ms）
- 测试：attribute 构建器计数校验、色板映射、attractor 钳制、形状生成器点云数/半径

### M5.3 交互特效
- `ripples.ts`：点击 → ripple {origin, t0} 入队（并发 ≤4，生命周期 ~2s，慢速扩散至全场），vertex shader 径向位移；参数下限硬校验（时长 ≥1200ms）
- 点击聚集：点击瞬间 attractor 脉冲 + morph 到形状 → 缓释回散（spring 回弹）
- `mood.ts`：statusStore voice.state → 场景氛围（idle 平静漂移 / speaking 流速 ×≤2 + bloom 微升），与 speakingDriver 共存；reduced-motion 全部关闭
- 清理：移除 M4 的 2D ParticleField 挂载与 `src/particles/`（降级回退保留 ParticleField 文件？——**决策：保留 2D 引擎作为 WebGL 失败降级**，不删除）
- 测试：ripple 队列并发/过期、参数下限、mood 映射与倍率钳制、降级回退路径

### M5.4 W1 数据通道重构（共享状态文件 + 事件推送）
- **omni_voice**（omni-brain 插件，允许改）：管道状态迁移时原子写 `~/.ai-omni/state/voice-status.json`（tmp+rename），schema `{state, running, fake_mode, ts}`；CLI status 优先读状态文件
- **Rust**：`notify` watcher 监听状态文件 → Tauri event `voice-status` 推送前端；文件不存在/解析失败 → 回退现有 CLI 轮询（双通道共存）
- **前端**：tauriSource 启用预留的 `subscribe` 形状 → statusStore 事件驱动更新（轮询降为兜底）
- 验收：真机上 speaking → Live2D 口型联动**真实触发**
- 测试：python 原子写/schema、Rust watcher 解析/防抖、前端订阅/回退；python 354 回归不破坏

## 四、验收标准（M5 关闭条件）

1. `pnpm vitest run` 全绿（新增测试全真实断言，mock three/pixi/@tauri-apps/api）
2. `pnpm build` 成功（three 懒加载 chunk，首屏不阻塞）
3. `cargo test --lib` 全绿；`python3 -m pytest -q` ≥354 全绿
4. reviewer 独立审计通过（审美红线逐项核对 + 测试真实性 + 回归）
5. STATE.json / TEST_LOG.md 归档；真机 `pnpm tauri dev` 冒烟记录

## 五、非目标（YAGNI）

- 不改窗口形态（380×560 dock 保持）、不改 StatusBar 信息架构
- 不引入 WebGPU、不引入音频可视化（留待后续里程碑）
- 不改 Live2D 渲染方式（pixi 保持）
