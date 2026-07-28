/**
 * WeatherMood 测试夹具（M23 E2E）。
 *
 * 与 src/data/sources.ts 的 WeatherMood 类型 + omni_weather 后端 mood_table
 * 返回的 snake_case 结构对齐。覆盖 6 种已知情绪（sunny / calm / melancholy /
 * dreamy / dramatic / mysterious）+ unknown 兜底 + 畸形负载。
 *
 * 后端返回字段为 snake_case（color_palette / particle_params / weather_code /
 * cached_at），由前端 normalizeWeatherMood 归一为 camelCase。fixture 直接给出
 * 后端原始结构（snake_case），让 normalizeWeatherMood 在 E2E 中真实执行归一化路径。
 *
 * 数值范围契约（与 weatherStore.ts SPEED/DENSITY/BRIGHTNESS 钳制区间对齐）：
 * - speed ∈ [0.3, 2.0]
 * - density ∈ [0.5, 2.0]
 * - brightness ∈ [0.2, 1.0]
 */
import type { WeatherMoodKind } from "../../src/data/sources";

/** 后端 weather_get_mood 工具返回的原始结构（snake_case）。 */
export interface WeatherMoodRaw {
  readonly mood: string;
  readonly description: string;
  readonly color_palette: readonly string[];
  readonly particle_params: {
    readonly speed: number;
    readonly density: number;
    readonly brightness: number;
  };
  readonly temperature: number;
  readonly weather_code: number;
  readonly cached_at: string;
}

/** weather_tool invoke 参数结构（与 weatherStore.refresh 对齐）。 */
export interface WeatherToolArgs {
  readonly tool: string;
  readonly args: Record<string, unknown>;
}

/** 标签 + fixture 二元组，用于参数化测试。 */
export interface WeatherMoodFixture {
  readonly label: WeatherMoodKind;
  readonly raw: WeatherMoodRaw;
}

/** sunny 情绪：晴朗午后，琥珀暖色 + 高亮度。 */
export const WEATHER_SUNNY: WeatherMoodRaw = {
  mood: "sunny",
  description: "晴朗午后",
  color_palette: ["#f4c870", "#e8a850", "#c9805a"],
  particle_params: { speed: 0.6, density: 0.8, brightness: 1.0 },
  temperature: 26.5,
  weather_code: 0,
  cached_at: "2026-07-27T14:00:00+08:00",
};

/** calm 情绪：多云平静，银盐中性色。 */
export const WEATHER_CALM: WeatherMoodRaw = {
  mood: "calm",
  description: "多云平静",
  color_palette: ["#c9a86a", "#8a8580", "#5a5752"],
  particle_params: { speed: 1.0, density: 1.0, brightness: 0.6 },
  temperature: 20.0,
  weather_code: 2,
  cached_at: "2026-07-27T10:00:00+08:00",
};

/** melancholy 情绪：阴雨绵延，冷蓝灰。 */
export const WEATHER_MELANCHOLY: WeatherMoodRaw = {
  mood: "melancholy",
  description: "阴雨绵延",
  color_palette: ["#3a4a5a", "#2a3540", "#1a2530"],
  particle_params: { speed: 0.5, density: 1.5, brightness: 0.4 },
  temperature: 14.2,
  weather_code: 61,
  cached_at: "2026-07-27T16:00:00+08:00",
};

/** dreamy 情绪：雪夜梦幻，冷紫白。 */
export const WEATHER_DREAMY: WeatherMoodRaw = {
  mood: "dreamy",
  description: "雪夜梦幻",
  color_palette: ["#d0c8e8", "#a8a0c8", "#7868a0"],
  particle_params: { speed: 0.4, density: 1.8, brightness: 0.7 },
  temperature: -2.0,
  weather_code: 75,
  cached_at: "2026-07-27T22:00:00+08:00",
};

/** dramatic 情绪：雷雨激烈，深紫黑 + 高流速。 */
export const WEATHER_DRAMATIC: WeatherMoodRaw = {
  mood: "dramatic",
  description: "雷雨激烈",
  color_palette: ["#2a1a3a", "#1a0a2a", "#0a0510"],
  particle_params: { speed: 2.0, density: 2.0, brightness: 0.3 },
  temperature: 18.0,
  weather_code: 95,
  cached_at: "2026-07-27T18:00:00+08:00",
};

/** mysterious 情绪：深夜静谧，深蓝紫。 */
export const WEATHER_MYSTERIOUS: WeatherMoodRaw = {
  mood: "mysterious",
  description: "深夜静谧",
  color_palette: ["#1a1a2a", "#0a0a1a", "#050510"],
  particle_params: { speed: 0.3, density: 0.5, brightness: 0.2 },
  temperature: 12.0,
  weather_code: -1,
  cached_at: "2026-07-27T03:00:00+08:00",
};

/** unknown 情绪：后端返回未识别字符串，前端归一化为 unknown。 */
export const WEATHER_UNKNOWN: WeatherMoodRaw = {
  mood: "__unrecognized__",
  description: "未知情绪",
  color_palette: ["#888888"],
  particle_params: { speed: 1.0, density: 1.0, brightness: 0.5 },
  temperature: 0.0,
  weather_code: 0,
  cached_at: "",
};

/** 6 种已知情绪的 fixture 列表（用于参数化测试）。 */
export const ALL_WEATHER_MOODS: readonly WeatherMoodFixture[] = [
  { label: "sunny", raw: WEATHER_SUNNY },
  { label: "calm", raw: WEATHER_CALM },
  { label: "melancholy", raw: WEATHER_MELANCHOLY },
  { label: "dreamy", raw: WEATHER_DREAMY },
  { label: "dramatic", raw: WEATHER_DRAMATIC },
  { label: "mysterious", raw: WEATHER_MYSTERIOUS },
];

/**
 * 构造 weather_tool 的成功响应信封（{ ok: true, data: ... }）。
 *
 * weatherStore.refresh 调 invoker("weather_get_mood", {}) → 返回 WeatherToolResult。
 * E2E 经 fakeTauri.override(CMD.WEATHER_TOOL, ...) 注入此响应。
 */
export function weatherOkResponse(raw: WeatherMoodRaw): unknown {
  return { ok: true, data: raw };
}

/**
 * 构造 weather_tool 的失败响应信封（{ ok: false, error: {...} }）。
 *
 * 模拟后端工具调用失败（如 E_BACKEND_UNAVAILABLE / E_WEATHER_FETCH_FAILED）。
 */
export function weatherErrorResponse(
  code = "E_BACKEND_UNAVAILABLE",
  message = "天气后端不可用",
): unknown {
  return { ok: false, error: { code, message } };
}

/**
 * 畸形负载：缺 color_palette 字段，应被 normalizeWeatherMood 拒绝（返回 null）。
 *
 * weatherStore.refresh 接收 ok=true 但 data 非法时，降级为归一化错误。
 */
export const WEATHER_MALFORMED_NO_PALETTE = {
  mood: "sunny",
  description: "畸形数据",
  // 缺 color_palette
  particle_params: { speed: 1, density: 1, brightness: 0.5 },
  temperature: 20,
  weather_code: 0,
  cached_at: "",
} as unknown as WeatherMoodRaw;

/**
 * 畸形负载：particle_params 缺 brightness 字段，应被归一化拒绝。
 */
export const WEATHER_MALFORMED_NO_BRIGHTNESS = {
  mood: "sunny",
  description: "畸形数据",
  color_palette: ["#f4c870"],
  particle_params: { speed: 1, density: 1 }, // 缺 brightness
  temperature: 20,
  weather_code: 0,
  cached_at: "",
} as unknown as WeatherMoodRaw;

/**
 * 畸形负载：temperature 缺失，应被归一化拒绝。
 */
export const WEATHER_MALFORMED_NO_TEMP = {
  mood: "sunny",
  description: "畸形数据",
  color_palette: ["#f4c870"],
  particle_params: { speed: 1, density: 1, brightness: 0.5 },
  // 缺 temperature
  weather_code: 0,
  cached_at: "",
} as unknown as WeatherMoodRaw;
