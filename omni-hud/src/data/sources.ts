/**
 * HUD 数据源抽象（M4.3）：语音管道状态 / 家庭摘要 / 系统资源。
 *
 * 实现侧：tauriSource.ts（Tauri IPC 轮询 Rust commands + voice-status 事件推送）；
 * 测试侧：fake 数据源经依赖注入替换（statusStore 单测）。
 * 字段命名与 Rust 侧 serde camelCase 负载一一对应；
 * 源不可用一律降级为 available:false 空负载，UI 呈现离线态而非报错刷屏。
 * M5.4：subscribe 落地——Rust voice_watch 监听共享状态文件并经
 * `voice-status` 事件推送；statusStore 事件驱动更新 voice 通道，轮询降为兜底。
 */

/** omni_voice 管道状态机（与 pipeline.py PipelineState 对齐）。 */
export type VoicePipelineState =
  | "idle"
  | "wake_listening"
  | "follow_up_listening"
  | "recording"
  | "transcribing"
  | "thinking"
  | "tool_using"
  | "speaking";

/**
 * HUD 窗口形态（M12 灵动岛双形态 + M22 壁纸模式）。
 * - "mini"：240×48 顶部居中浮窗，鼠标穿透，显示状态文字（idle 待命态）；
 * - "full"：cover-display 全屏覆盖（FieldStage + CaptionLayer + WellZone，活跃态）；
 * - "wallpaper"：沉到桌面图标层下方（M22 D22.1），几何同 full 仅 level 不同，
 *   用户主动选择的常驻形态（hudStore.wallpaperMode），活跃态自动浮出回 full。
 * "mini"/"full" 由 Python 侧 derive_window_mode(state) 推导，经状态文件 →
 * Rust voice_watch → 前端联动；"wallpaper" 由前端 hudStore 持有，App.tsx
 * 合并语音推导模式与 wallpaperMode 计算最终形态。null 表示旧版缺省，按 "full" 处理。
 */
export type WindowMode = "mini" | "full" | "wallpaper";

/**
 * 工具调用状态（M13.2 Agent 可视化）：pending=加载中 / success=成功 / error=失败。
 * 与 Rust ``ToolCallPayload.status`` / Python ``state_file.tool_calls[].status`` 对齐。
 */
export type ToolCallStatus = "pending" | "success" | "error";

/**
 * 单次工具调用记录（M13.2 Agent 可视化）。
 *
 * 字段命名与 Rust ``ToolCallPayload``（camelCase 序列化）一一对应；
 * Rust 解析 Python 状态文件时已做 snake_case → camelCase 归一
 * （``name``→``toolName`` / ``args``→``params`` / ``ts``→``timestamp``）。
 */
export interface ToolCallRecord {
  readonly id: string;
  readonly toolName: string;
  /** 调用参数（JSON 对象原样透传）。 */
  readonly params: Record<string, unknown>;
  /** 工具返回结果（JSON 字符串）；null 表示尚未返回（pending）。 */
  readonly result: string | null;
  readonly status: ToolCallStatus;
  /** 调用时间戳（Python ``time.time()`` 秒级浮点）。 */
  readonly timestamp: number;
}

export interface VoiceStatus {
  readonly available: boolean;
  /** 管道状态；源不可用或状态无法识别时为 null。 */
  readonly state: VoicePipelineState | null;
  readonly running: boolean;
  readonly fakeMode: boolean;
  /**
   * 本轮回复文本（M6.3）：omni_voice 进入 speaking 时随状态文件写入，
   * 驱动 OpenTalking speakText 联动；其他状态 / 旧版 Rust 缺省为 null。
   */
  readonly reply: string | null;
  /**
   * 回复轮次序号（M6.3 修复）：omni_voice 每显式写入一次回复递增；
   * 相同文本的新一轮回复也构成语义变化；旧版 Rust/Python 缺省为 null。
   */
  readonly replySeq: number | null;
  /**
   * HUD 窗口形态（M12 灵动岛双形态）：Python 侧 derive_window_mode(state) 推导，
   * 经状态文件透传到前端。null / 缺省时前端按 "full" 处理（安全态）。
   */
  readonly windowMode: WindowMode | null;
  /**
   * 当前轮次进行中的工具调用列表（M13.2 Agent 可视化）。
   * - ``null``：状态文件未携带 tool_calls 键（M12 旧格式 / 旧版 Rust），前端不渲染工具卡片；
   * - ``[]``：本轮工具链已结束（进入 speaking 时显式清空），前端可显示「工具调用完成」态；
   * - ``[...]``：本轮有进行中 / 已完成的工具调用，前端按顺序渲染 ToolCallCard。
   * 元素经 ``normalizeToolCall`` 守卫，非法元素被过滤。
   */
  readonly toolCalls: readonly ToolCallRecord[] | null;
}

export interface HomeDeviceBrief {
  readonly name: string;
  /** omni_home 知识图谱的中文状态描述（如 "开启" / "制冷中（设定 26°C）"）。 */
  readonly stateText: string;
}

export interface HomeRoomBrief {
  readonly name: string;
  readonly devices: readonly HomeDeviceBrief[];
}

export interface HomeSummary {
  readonly available: boolean;
  /** true = 数据来自 omni_home --fake 演示家庭（真实 HA 不可达时的降级），UI 须如实标注。 */
  readonly demo: boolean;
  readonly rooms: readonly HomeRoomBrief[];
  readonly stats: { readonly devices: number; readonly rooms: number } | null;
}

export interface SystemStats {
  readonly available: boolean;
  readonly cpuPercent: number;
  readonly memoryUsedBytes: number;
  readonly memoryTotalBytes: number;
  readonly networkRxBytesPerSec: number;
  readonly networkTxBytesPerSec: number;
}

/** 预留：源侧事件推送（WebSocket/SSE 在后续里程碑接入）。 */
export interface HudSourceEvent {
  readonly type: string;
  readonly payload: unknown;
}

export type HudSourceEventListener = (event: HudSourceEvent) => void;

/** voice-status 事件名（与 Rust voice_watch.rs VOICE_STATUS_EVENT 对齐）。 */
export const VOICE_STATUS_EVENT = "voice-status";

/**
 * voice-status 事件负载的运行时守卫。
 *
 * 契约：voice-status 事件的 payload 必须是已归一化的 VoiceStatus
 * （tauriSource 在 IPC 边界归一化）；这里兜底畸形负载，store 侧不 crash。
 */
export function isVoiceStatusPayload(raw: unknown): raw is VoiceStatus {
  if (raw === null || typeof raw !== "object") return false;
  const obj = raw as Record<string, unknown>;
  return (
    typeof obj.available === "boolean" &&
    typeof obj.running === "boolean" &&
    typeof obj.fakeMode === "boolean" &&
    (obj.state === null || typeof obj.state === "string") &&
    (obj.reply === null || typeof obj.reply === "string") &&
    (obj.replySeq === null || typeof obj.replySeq === "number") &&
    (obj.windowMode === null ||
      obj.windowMode === "mini" ||
      obj.windowMode === "full") &&
    (obj.toolCalls === null || Array.isArray(obj.toolCalls))
  );
}

export interface HudDataSource {
  voiceStatus(): Promise<VoiceStatus>;
  homeSummary(): Promise<HomeSummary>;
  systemStats(): Promise<SystemStats>;
  /**
   * 订阅源侧事件推送（M5.4 voice-status），返回退订函数。
   * 环境不支持推送（纯浏览器 / 监听注册失败）时返回 noop 退订，
   * 调用方按轮询兜底，无需区分。
   */
  subscribe?(listener: HudSourceEventListener): () => void;
}

export const EMPTY_VOICE_STATUS: VoiceStatus = {
  available: false,
  state: null,
  running: false,
  fakeMode: false,
  reply: null,
  replySeq: null,
  windowMode: null,
  toolCalls: null,
};

export const EMPTY_HOME_SUMMARY: HomeSummary = {
  available: false,
  demo: false,
  rooms: [],
  stats: null,
};

export const EMPTY_SYSTEM_STATS: SystemStats = {
  available: false,
  cpuPercent: 0,
  memoryUsedBytes: 0,
  memoryTotalBytes: 0,
  networkRxBytesPerSec: 0,
  networkTxBytesPerSec: 0,
};

// ---------------------------------------------------------------------------
// M23 天气情绪（WeatherMood）：omni_weather weather_get_mood 工具返回归一化结构
// ---------------------------------------------------------------------------

/**
 * 天气情绪枚举（M23.2 天气情绪映射表）。
 *
 * 与 omni_weather 后端 `mood` 字段对齐：clear→sunny / cloudy→calm / rain→melancholy /
 * fog→dreamy / snow→dreamy / storm→dramatic / night→mysterious。
 * `"unknown"` 为前端归一化兜底值——后端返回未识别字符串 / null 时降级为 unknown，
 * 视觉上等同 calm 基线，避免非法字段污染渲染层。
 */
export type WeatherMoodKind =
  | "sunny"
  | "calm"
  | "melancholy"
  | "dreamy"
  | "mysterious"
  | "dramatic"
  | "unknown";

/**
 * 天气情绪粒子参数（M23.3 FieldStage 视觉联动规格）。
 *
 * 数值范围契约（后端 omni_weather mood_table.py 保证，前端二次钳制）：
 * - speed ∈ [0.3, 2.0]：粒子流速倍率（与 M21 节奏粒子叠加，互不冲突）
 * - density ∈ [0.5, 2.0]：粒子密度倍率（受 quality tier 上限钳制 high≤4000/medium≤2000/low≤800）
 * - brightness ∈ [0.2, 1.0]：粒子亮度（同时影响 AmbientLight 强度与粒子 alpha）
 */
export interface WeatherParticleParams {
  readonly speed: number;
  readonly density: number;
  readonly brightness: number;
}

/**
 * 天气情绪完整数据（M23 前端归一化后结构）。
 *
 * 字段命名遵循 sources.ts 既有 camelCase 风格（colorPalette 而非 color_palette，
 * particleParams 而非 particle_params），与 Rust 侧 serde camelCase 序列化对齐。
 * 后端 omni_weather 返回 snake_case + 部分字段可缺省，前端经
 * `normalizeWeatherMood` 防御性归一化后产出此结构。
 */
export interface WeatherMood {
  /** 情绪枚举（归一化后必为已知值，不会是 null）。 */
  readonly mood: WeatherMoodKind;
  /** 中文描述（如 "晴朗午后"）；后端缺失时为空串。 */
  readonly description: string;
  /** hex 颜色列表（≤6 色，CLAUDE.md §六.3 主题内容色 ≤6 红线）；归一化后至少 1 色。 */
  readonly colorPalette: readonly string[];
  /** 粒子参数（数值范围已钳制到合法区间）。 */
  readonly particleParams: WeatherParticleParams;
  /** 摄氏度（NaN 视为非法，归一化失败整个 mood 返回 null）。 */
  readonly temperature: number;
  /** WMO weather code（整数；缺失归 0）。 */
  readonly weatherCode: number;
  /** ISO8601 时间戳（后端 cached_at 字段；缺失为空串）。 */
  readonly cachedAt: string;
}

/**
 * 默认天气情绪（calm 基线）：用于 weatherStore 初始状态与 clearWeatherMood 复位。
 * 不视为「真实情绪」——store.mood === null 才表示尚未拉取 / 拉取失败。
 */
export const EMPTY_WEATHER_MOOD: WeatherMood = {
  mood: "calm",
  description: "",
  colorPalette: ["#c9a86a"],
  particleParams: { speed: 1, density: 1, brightness: 0.6 },
  temperature: 20,
  weatherCode: 0,
  cachedAt: "",
};
