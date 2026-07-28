/**
 * 天气情绪 store（M23.3 前端）。
 *
 * 框架无关订阅模式（与 lyricsStore / musicStore 同款），React 侧经
 * ``useSyncExternalStore`` 绑定。维护：
 *
 * 1. ``mood``：来自后端 ``omni_weather.weather_get_mood`` 工具返回的
 *    WeatherMood 数据（情绪枚举 / 色板 / 粒子参数 / 温度 / WMO code / 缓存时间戳），
 *    前端只读消费，不本地修改——后端是唯一权威源。
 * 2. ``loading`` / ``error``：调用 IPC 期间的瞬态状态与错误信息（用户可读）。
 *
 * IPC 通道（D17.1 同款）：经通用 ``weather_tool`` command 调 Rust → Python
 * omni_weather 工具（M23.5 后端）。工具返回 JSON 字符串
 * ``{"ok": true, "data": ...}``，store 侧解析 + 防御性归一化（IPC 边界不可信）。
 *
 * 非 Tauri 环境（vitest / 纯 web 预览）默认 invoker 返回 ``E_NOT_TAURI``，
 * store 呈现离线态而非报错刷屏；测试经 ``deps.invoker`` 注入 fake 即可。
 *
 * 与 M21 节奏粒子共存：weatherMood 影响 AmbientLight + 粒子色板 + 粒子密度
 * （互不冲突，叠加生效）；M21 节奏粒子影响粒子动效（bass/mid/treble/beat）。
 */
import { invoke } from "@tauri-apps/api/core";

import { isTauri } from "../lib/window";
import type { WeatherMood, WeatherMoodKind } from "../data/sources";

// ---------------------------------------------------------------------------
// IPC 边界（不可信数据归一化）
// ---------------------------------------------------------------------------

/** 工具返回的 JSON 字符串解析后结构。 */
export interface WeatherToolResult<T> {
  readonly ok: boolean;
  readonly data?: T;
  readonly error?: { readonly code: string; readonly message: string };
}

/**
 * 通用天气工具调用器：经 ``invoke('weather_tool', {tool, args})`` 调 Rust → Python。
 * 返回解析后的 ``WeatherToolResult``；实现侧负责 JSON 解析与防御性归一化。
 */
export type WeatherInvoker = (
  tool: string,
  args?: Record<string, unknown>,
) => Promise<WeatherToolResult<unknown>>;

/** 默认 Tauri invoker：非 Tauri 环境降级为 E_NOT_TAURI（不抛错）。 */
async function defaultInvoker(
  tool: string,
  args?: Record<string, unknown>,
): Promise<WeatherToolResult<unknown>> {
  if (!isTauri()) {
    return {
      ok: false,
      error: { code: "E_NOT_TAURI", message: "非 Tauri 环境，天气工具不可用" },
    };
  }
  try {
    // 后端返回 JSON 字符串 {"ok": true, "data": ...} / {"ok": false, "error": {...}}
    const raw = await invoke<string>("weather_tool", { tool, args: args ?? {} });
    const parsed = JSON.parse(raw) as WeatherToolResult<unknown>;
    return parsed;
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return { ok: false, error: { code: "E_IPC_FAILED", message } };
  }
}

function asRecord(raw: unknown): Record<string, unknown> | null {
  return raw !== null && typeof raw === "object" ? (raw as Record<string, unknown>) : null;
}

function asString(raw: unknown): string | null {
  return typeof raw === "string" ? raw : null;
}

function asFiniteNumber(raw: unknown): number | null {
  return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
}

const WEATHER_MOOD_KINDS: ReadonlySet<string> = new Set<WeatherMoodKind>([
  "sunny",
  "calm",
  "melancholy",
  "dreamy",
  "mysterious",
  "dramatic",
]);

/** 数值范围常量（与后端 mood_table 对齐，前端二次钳制）。 */
const SPEED_MIN = 0.3;
const SPEED_MAX = 2.0;
const DENSITY_MIN = 0.5;
const DENSITY_MAX = 2.0;
const BRIGHTNESS_MIN = 0.2;
const BRIGHTNESS_MAX = 1.0;

/** hex 颜色正则：3 位 / 6 位，前导 # 可选。 */
const HEX_RE = /^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

/** 主题内容色硬上限（CLAUDE.md §六.3 红线 ≤6 色）。 */
const PALETTE_MAX = 6;

/**
 * 把不可信输入归一为 WeatherMood；任一必填字段缺失 / 类型不符返回 null。
 *
 * 后端字段为 snake_case（``color_palette`` / ``particle_params`` / ``weather_code`` /
 * ``cached_at``），前端归一为 camelCase（与 sources.ts WeatherMood 对齐）。
 * mood 字段未识别字符串 / null / 缺失 → 降级为 ``"unknown"``（不返回 null）。
 * colorPalette 至少 1 色且全为合法 hex，超 6 色截断为前 6 色。
 * particleParams 数值字段 NaN 视为非法（整条 mood 返回 null）；范围超界钳制到合法区间。
 */
export function normalizeWeatherMood(raw: unknown): WeatherMood | null {
  const obj = asRecord(raw);
  if (obj === null) return null;

  // mood：未知 / null / 缺失 → "unknown"；已知枚举透传
  const moodStr = asString(obj.mood);
  const mood: WeatherMoodKind =
    moodStr !== null && WEATHER_MOOD_KINDS.has(moodStr)
      ? (moodStr as WeatherMoodKind)
      : "unknown";

  // description：缺失 / 非字符串 → 空串
  const description = asString(obj.description) ?? "";

  // color_palette：必填，数组中元素过滤为合法 hex；空数组 / 全非法 → 返回 null
  if (!Array.isArray(obj.color_palette)) return null;
  const hexColors = obj.color_palette
    .map((v) => asString(v))
    .filter((v): v is string => v !== null && HEX_RE.test(v))
    .map((v) => (v.startsWith("#") ? v : `#${v}`));
  if (hexColors.length === 0) return null;
  const colorPalette = hexColors.slice(0, PALETTE_MAX);

  // particle_params：必填对象；speed/density/brightness 必填且为有限数值
  const paramsObj = asRecord(obj.particle_params);
  if (paramsObj === null) return null;
  const speed = asFiniteNumber(paramsObj.speed);
  const density = asFiniteNumber(paramsObj.density);
  const brightness = asFiniteNumber(paramsObj.brightness);
  if (speed === null || density === null || brightness === null) return null;
  const particleParams = {
    speed: Math.min(SPEED_MAX, Math.max(SPEED_MIN, speed)),
    density: Math.min(DENSITY_MAX, Math.max(DENSITY_MIN, density)),
    brightness: Math.min(BRIGHTNESS_MAX, Math.max(BRIGHTNESS_MIN, brightness)),
  };

  // temperature：必填且为有限数值（NaN / 缺失 → null）
  const temperature = asFiniteNumber(obj.temperature);
  if (temperature === null) return null;

  // weather_code：缺失归 0
  const weatherCode = asFiniteNumber(obj.weather_code) ?? 0;

  // cached_at：缺失 / 非字符串 → 空串
  const cachedAt = asString(obj.cached_at) ?? "";

  return {
    mood,
    description,
    colorPalette,
    particleParams,
    temperature,
    weatherCode,
    cachedAt,
  };
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export interface WeatherState {
  /** 当前天气情绪；null = 尚未拉取 / 拉取失败。 */
  readonly mood: WeatherMood | null;
  /** 正在拉取 / 调用工具中。 */
  readonly loading: boolean;
  /** 最近一次错误信息（用户可读）；null = 无错误。 */
  readonly error: string | null;
}

export interface WeatherStore {
  getState: () => WeatherState;
  subscribe: (listener: () => void) => () => void;
  /** 拉取天气情绪（weather_get_mood）：经 IPC 调用后端工具，归一化后写入 mood。 */
  refresh: () => Promise<void>;
}

export interface WeatherStoreDeps {
  /** 注入自定义 invoker（测试用）；缺省走 Tauri invoke。 */
  readonly invoker?: WeatherInvoker;
}

/** 空状态：无情绪、无错误、未在加载。 */
export const EMPTY_WEATHER_STATE: WeatherState = {
  mood: null,
  loading: false,
  error: null,
};

export function createWeatherStore(deps: WeatherStoreDeps = {}): WeatherStore {
  const invoker: WeatherInvoker = deps.invoker ?? defaultInvoker;
  let state: WeatherState = { ...EMPTY_WEATHER_STATE };
  const listeners = new Set<() => void>();

  const emit = (): void => {
    for (const listener of listeners) listener();
  };

  const patch = (next: Partial<WeatherState>): void => {
    state = { ...state, ...next };
    emit();
  };

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    async refresh() {
      patch({ loading: true, error: null });
      let result: WeatherToolResult<unknown>;
      try {
        result = await invoker("weather_get_mood", {});
      } catch (e) {
        // invoker 抛错（网络断开 / IPC reject）降级为 E_IPC_FAILED 错误信封，
        // 不向调用方传播异常——store 呈现离线态而非崩溃
        const message = e instanceof Error ? e.message : String(e);
        patch({ loading: false, error: message });
        return;
      }
      if (result.ok) {
        const normalized = normalizeWeatherMood(result.data);
        if (normalized === null) {
          // ok=true 但 data 非法（缺必填字段 / 类型不符）——降级为归一化错误
          patch({
            loading: false,
            mood: null,
            error: "归一化失败：后端返回的数据缺少必填字段或类型不符",
          });
          return;
        }
        patch({ loading: false, mood: normalized, error: null });
        return;
      }
      const message = result.error?.message ?? "未知错误";
      patch({ loading: false, error: message });
    },
  };
}
