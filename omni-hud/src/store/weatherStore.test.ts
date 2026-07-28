/**
 * weatherStore 测试（M23 TDD）。
 *
 * 经 ``deps.invoker`` 依赖注入 fake 调用器，不 mock Tauri 模块。
 * 覆盖：初始状态 / refresh 成功失败 / normalizeWeatherMood 拒非法字段
 * （mood 枚举校验 / colorPalette hex 校验 / particleParams 数值范围校验）
 * / invoker 注入 / subscribe 通知 / 错误信封降级 / cached_at 透传。
 *
 * 后端契约：omni_weather.weather_get_mood 返回
 * ``{mood, description, color_palette, particle_params, temperature, weather_code, cached_at}``
 * （snake_case），前端归一化为 WeatherMood（camelCase）。
 */
import { describe, expect, it } from "vitest";

import { EMPTY_WEATHER_MOOD } from "../data/sources";
import {
  EMPTY_WEATHER_STATE,
  createWeatherStore,
  normalizeWeatherMood,
  type WeatherInvoker,
  type WeatherToolResult,
} from "./weatherStore";

/** 构造一个合法的 weather_get_mood 后端返回 dict（snake_case）。 */
function makeMoodDict(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    mood: "sunny",
    description: "晴朗午后",
    color_palette: ["#ffd966", "#ffb347", "#ff8c42"],
    particle_params: { speed: 1.2, density: 1.0, brightness: 0.8 },
    temperature: 25.5,
    weather_code: 0,
    cached_at: "2026-07-27T10:00:00Z",
    ...overrides,
  };
}

/** fake invoker：按 tool 名分派预设结果，记录所有调用。 */
interface FakeInvokerOptions {
  results?: Record<string, WeatherToolResult<unknown>>;
  sequences?: Record<string, WeatherToolResult<unknown>[]>;
  defaultResult?: WeatherToolResult<unknown>;
}

function makeFakeInvoker(opts: FakeInvokerOptions = {}): {
  invoker: WeatherInvoker;
  calls: { tool: string; args?: Record<string, unknown> }[];
} {
  const calls: { tool: string; args?: Record<string, unknown> }[] = [];
  const seqCounters: Record<string, number> = {};
  const invoker: WeatherInvoker = async (tool, args) => {
    calls.push({ tool, args });
    const seq = opts.sequences?.[tool];
    if (seq !== undefined) {
      const idx = seqCounters[tool] ?? 0;
      seqCounters[tool] = idx + 1;
      const result = seq[Math.min(idx, seq.length - 1)];
      if (result !== undefined) return result;
    }
    const result = opts.results?.[tool];
    if (result !== undefined) return result;
    return opts.defaultResult ?? {
      ok: false,
      error: { code: "E_NO_MOCK", message: `未 mock tool: ${tool}` },
    };
  };
  return { invoker, calls };
}

const okMood = (overrides: Record<string, unknown> = {}): WeatherToolResult<unknown> => ({
  ok: true,
  data: makeMoodDict(overrides),
});

// ---------------------------------------------------------------------------
// 初始状态
// ---------------------------------------------------------------------------

describe("weatherStore 初始状态", () => {
  it("createWeatherStore 返回 EMPTY_WEATHER_STATE 副本", () => {
    const { invoker } = makeFakeInvoker();
    const store = createWeatherStore({ invoker });
    const state = store.getState();
    expect(state.mood).toBeNull();
    expect(state.loading).toBe(false);
    expect(state.error).toBeNull();
  });

  it("EMPTY_WEATHER_STATE 是冻结的初始快照", () => {
    expect(EMPTY_WEATHER_STATE.mood).toBeNull();
    expect(EMPTY_WEATHER_STATE.loading).toBe(false);
    expect(EMPTY_WEATHER_STATE.error).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// normalizeWeatherMood 防御性归一化
// ---------------------------------------------------------------------------

describe("normalizeWeatherMood 防御性归一化", () => {
  it("合法 dict 完整透传为 WeatherMood（snake_case → camelCase）", () => {
    const mood = normalizeWeatherMood(makeMoodDict());
    expect(mood).not.toBeNull();
    expect(mood!.mood).toBe("sunny");
    expect(mood!.description).toBe("晴朗午后");
    expect(mood!.colorPalette).toEqual(["#ffd966", "#ffb347", "#ff8c42"]);
    expect(mood!.particleParams).toEqual({ speed: 1.2, density: 1.0, brightness: 0.8 });
    expect(mood!.temperature).toBe(25.5);
    expect(mood!.weatherCode).toBe(0);
    expect(mood!.cachedAt).toBe("2026-07-27T10:00:00Z");
  });

  it("mood 字段未识别字符串降级为 unknown（不返回 null）", () => {
    const mood = normalizeWeatherMood(makeMoodDict({ mood: "foo_unknown" }));
    expect(mood).not.toBeNull();
    expect(mood!.mood).toBe("unknown");
  });

  it("mood 字段缺失 / null 降级为 unknown", () => {
    const mood1 = normalizeWeatherMood(makeMoodDict({ mood: null }));
    const mood2 = normalizeWeatherMood(makeMoodDict({ mood: undefined }));
    expect(mood1!.mood).toBe("unknown");
    expect(mood2!.mood).toBe("unknown");
  });

  it("color_palette 非 hex 字符串被过滤，剩余 hex 仍可用", () => {
    const mood = normalizeWeatherMood(
      makeMoodDict({ color_palette: ["#ffd966", "not-a-color", "#abc", 42, null] }),
    );
    expect(mood).not.toBeNull();
    // #abc 是合法 hex 简写；非字符串与非法字符串被过滤
    expect(mood!.colorPalette).toEqual(["#ffd966", "#abc"]);
  });

  it("color_palette 为空 / 全非法 / 缺失 → 归一化失败返回 null", () => {
    expect(normalizeWeatherMood(makeMoodDict({ color_palette: [] }))).toBeNull();
    expect(normalizeWeatherMood(makeMoodDict({ color_palette: ["nope", 5] }))).toBeNull();
    expect(normalizeWeatherMood(makeMoodDict({ color_palette: undefined }))).toBeNull();
  });

  it("color_palette 超过 6 色截断为前 6 色（CLAUDE.md §六.3 主题内容色 ≤6 红线）", () => {
    const palette = ["#111111", "#222222", "#333333", "#444444", "#555555", "#666666", "#777777", "#888888"];
    const mood = normalizeWeatherMood(makeMoodDict({ color_palette: palette }));
    expect(mood).not.toBeNull();
    expect(mood!.colorPalette).toHaveLength(6);
    expect(mood!.colorPalette[0]).toBe("#111111");
    expect(mood!.colorPalette[5]).toBe("#666666");
  });

  it("particle_params 缺失 / 非对象 → 归一化失败返回 null", () => {
    expect(normalizeWeatherMood(makeMoodDict({ particle_params: undefined }))).toBeNull();
    expect(normalizeWeatherMood(makeMoodDict({ particle_params: null }))).toBeNull();
    expect(normalizeWeatherMood(makeMoodDict({ particle_params: "fast" }))).toBeNull();
  });

  it("particle_params.speed 超出 [0.3, 2.0] 钳制到合法区间", () => {
    const m1 = normalizeWeatherMood(makeMoodDict({ particle_params: { speed: 99, density: 1, brightness: 0.5 } }));
    const m2 = normalizeWeatherMood(makeMoodDict({ particle_params: { speed: 0, density: 1, brightness: 0.5 } }));
    expect(m1!.particleParams.speed).toBe(2.0);
    expect(m2!.particleParams.speed).toBe(0.3);
  });

  it("particle_params.density 超出 [0.5, 2.0] 钳制到合法区间", () => {
    const m1 = normalizeWeatherMood(makeMoodDict({ particle_params: { speed: 1, density: 5, brightness: 0.5 } }));
    const m2 = normalizeWeatherMood(makeMoodDict({ particle_params: { speed: 1, density: 0.1, brightness: 0.5 } }));
    expect(m1!.particleParams.density).toBe(2.0);
    expect(m2!.particleParams.density).toBe(0.5);
  });

  it("particle_params.brightness 超出 [0.2, 1.0] 钳制到合法区间", () => {
    const m1 = normalizeWeatherMood(makeMoodDict({ particle_params: { speed: 1, density: 1, brightness: 5 } }));
    const m2 = normalizeWeatherMood(makeMoodDict({ particle_params: { speed: 1, density: 1, brightness: 0 } }));
    expect(m1!.particleParams.brightness).toBe(1.0);
    expect(m2!.particleParams.brightness).toBe(0.2);
  });

  it("particle_params 数值字段 NaN 视为非法，整条 mood 返回 null", () => {
    const mood = normalizeWeatherMood(
      makeMoodDict({ particle_params: { speed: Number.NaN, density: 1, brightness: 0.5 } }),
    );
    expect(mood).toBeNull();
  });

  it("particle_params 缺 speed 字段 → 返回 null（必填）", () => {
    const mood = normalizeWeatherMood(
      makeMoodDict({ particle_params: { density: 1, brightness: 0.5 } }),
    );
    expect(mood).toBeNull();
  });

  it("temperature NaN / 缺失 → 返回 null（必填）", () => {
    expect(normalizeWeatherMood(makeMoodDict({ temperature: Number.NaN }))).toBeNull();
    expect(normalizeWeatherMood(makeMoodDict({ temperature: undefined }))).toBeNull();
  });

  it("weather_code 缺失归 0（非必填）", () => {
    const mood = normalizeWeatherMood(makeMoodDict({ weather_code: undefined }));
    expect(mood!.weatherCode).toBe(0);
  });

  it("cached_at 缺失 / 非字符串归空串", () => {
    expect(normalizeWeatherMood(makeMoodDict({ cached_at: undefined }))!.cachedAt).toBe("");
    expect(normalizeWeatherMood(makeMoodDict({ cached_at: 42 }))!.cachedAt).toBe("");
  });

  it("description 缺失 / 非字符串归空串", () => {
    expect(normalizeWeatherMood(makeMoodDict({ description: undefined }))!.description).toBe("");
    expect(normalizeWeatherMood(makeMoodDict({ description: 42 }))!.description).toBe("");
  });

  it("非对象输入（null / 数组 / 标量）返回 null", () => {
    expect(normalizeWeatherMood(null)).toBeNull();
    expect(normalizeWeatherMood([])).toBeNull();
    expect(normalizeWeatherMood("sunny")).toBeNull();
    expect(normalizeWeatherMood(42)).toBeNull();
    expect(normalizeWeatherMood(true)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// refresh() 成功路径
// ---------------------------------------------------------------------------

describe("weatherStore.refresh 成功路径", () => {
  it("refresh 调用 weather_get_mood 工具，args 为空对象", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: { weather_get_mood: okMood() },
    });
    const store = createWeatherStore({ invoker });
    await store.refresh();
    expect(calls).toHaveLength(1);
    expect(calls[0]!.tool).toBe("weather_get_mood");
    expect(calls[0]!.args).toEqual({});
  });

  it("refresh 成功后写入 mood 状态，loading 归 false，error 清空", async () => {
    const { invoker } = makeFakeInvoker({
      results: { weather_get_mood: okMood() },
    });
    const store = createWeatherStore({ invoker });
    await store.refresh();
    const state = store.getState();
    expect(state.mood).not.toBeNull();
    expect(state.mood!.mood).toBe("sunny");
    expect(state.mood!.colorPalette).toEqual(["#ffd966", "#ffb347", "#ff8c42"]);
    expect(state.loading).toBe(false);
    expect(state.error).toBeNull();
  });

  it("refresh 期间 loading=true（同步可见）", async () => {
    let resolveRefresh: ((value: WeatherToolResult<unknown>) => void) | null = null;
    const pending = new Promise<WeatherToolResult<unknown>>((resolve) => {
      resolveRefresh = resolve;
    });
    const invoker: WeatherInvoker = async () => pending;
    const store = createWeatherStore({ invoker });
    const refreshPromise = store.refresh();
    expect(store.getState().loading).toBe(true);
    resolveRefresh!(okMood());
    await refreshPromise;
    expect(store.getState().loading).toBe(false);
  });

  it("refresh 期间 listener 收到 loading 与 mood 两次通知", async () => {
    const { invoker } = makeFakeInvoker({
      results: { weather_get_mood: okMood() },
    });
    const store = createWeatherStore({ invoker });
    const seen: boolean[] = [];
    const seenMoods: (typeof EMPTY_WEATHER_MOOD | null)[] = [];
    store.subscribe(() => {
      const s = store.getState();
      seen.push(s.loading);
      seenMoods.push(s.mood);
    });
    await store.refresh();
    // 至少包含 loading=true 与 loading=false 两次通知
    expect(seen.length).toBeGreaterThanOrEqual(2);
    expect(seenMoods.at(-1)).not.toBeNull();
    expect(seenMoods.at(-1)!.mood).toBe("sunny");
  });
});

// ---------------------------------------------------------------------------
// refresh() 失败路径
// ---------------------------------------------------------------------------

describe("weatherStore.refresh 失败路径", () => {
  it("ok=false 错误信封写入 error 状态，mood 保持 null", async () => {
    const { invoker } = makeFakeInvoker({
      defaultResult: { ok: false, error: { code: "E_BACKEND", message: "Open-Meteo 不可达" } },
    });
    const store = createWeatherStore({ invoker });
    await store.refresh();
    const state = store.getState();
    expect(state.mood).toBeNull();
    expect(state.loading).toBe(false);
    expect(state.error).toBe("Open-Meteo 不可达");
  });

  it("ok=true 但 data 非法（normalizeWeatherMood 返回 null）→ mood=null, error 含归一化失败提示", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        weather_get_mood: { ok: true, data: { mood: "sunny" } /* 缺 color_palette 等必填 */ },
      },
    });
    const store = createWeatherStore({ invoker });
    await store.refresh();
    const state = store.getState();
    expect(state.mood).toBeNull();
    expect(state.loading).toBe(false);
    expect(state.error).toContain("归一化");
  });

  it("invoker 抛错被捕获并降级为 E_IPC_FAILED 错误信封", async () => {
    const invoker: WeatherInvoker = async () => {
      throw new Error("网络断开");
    };
    const store = createWeatherStore({ invoker });
    await store.refresh();
    const state = store.getState();
    expect(state.mood).toBeNull();
    expect(state.error).toContain("网络断开");
  });

  it("refresh 后再 refresh 成功，error 被清空", async () => {
    const seq: WeatherToolResult<unknown>[] = [
      { ok: false, error: { code: "E_X", message: "第一次失败" } },
      okMood({ mood: "calm" }),
    ];
    const { invoker } = makeFakeInvoker({
      sequences: { weather_get_mood: seq },
    });
    const store = createWeatherStore({ invoker });
    await store.refresh();
    expect(store.getState().error).toBe("第一次失败");
    await store.refresh();
    expect(store.getState().error).toBeNull();
    expect(store.getState().mood!.mood).toBe("calm");
  });
});

// ---------------------------------------------------------------------------
// subscribe 通知
// ---------------------------------------------------------------------------

describe("weatherStore.subscribe 通知", () => {
  it("subscribe 返回退订函数，调用后不再收通知", async () => {
    const { invoker } = makeFakeInvoker({
      results: { weather_get_mood: okMood() },
    });
    const store = createWeatherStore({ invoker });
    let count = 0;
    const unsubscribe = store.subscribe(() => {
      count += 1;
    });
    await store.refresh();
    const before = count;
    unsubscribe();
    await store.refresh();
    expect(count).toBe(before); // 退订后不再增加
  });

  it("多个 listener 独立退订，互不影响", async () => {
    const { invoker } = makeFakeInvoker({
      results: { weather_get_mood: okMood() },
    });
    const store = createWeatherStore({ invoker });
    let a = 0;
    let b = 0;
    const unsubA = store.subscribe(() => {
      a += 1;
    });
    store.subscribe(() => {
      b += 1;
    });
    await store.refresh();
    expect(a).toBeGreaterThan(0);
    expect(b).toBeGreaterThan(0);
    const aBefore = a;
    const bBefore = b;
    unsubA();
    await store.refresh();
    expect(a).toBe(aBefore);
    expect(b).toBeGreaterThan(bBefore);
  });
});

// ---------------------------------------------------------------------------
// 默认 invoker（非 Tauri 环境降级）
// ---------------------------------------------------------------------------

describe("weatherStore 默认 invoker", () => {
  it("非 Tauri 环境调用 refresh 返回 E_NOT_TAURI 错误（不抛错）", async () => {
    // 不注入 invoker，使用默认实现；vitest 环境非 Tauri
    const store = createWeatherStore({});
    await store.refresh();
    const state = store.getState();
    expect(state.mood).toBeNull();
    expect(state.error).toContain("Tauri");
    expect(state.loading).toBe(false);
  });
});
