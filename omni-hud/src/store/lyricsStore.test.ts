/**
 * lyricsStore 测试（M18 TDD）。
 *
 * 经 ``deps.invoker`` 依赖注入 fake 调用器，不 mock Tauri 模块。
 * 覆盖：初始状态 / fetchLyrics 成功失败 / refreshCurrentLine 二分查找正确性
 * （多组已知时间轴断言）/ setOffset 持久化往返 / searchLyrics / uploadLyrics
 * / normalize 拒绝非法 / invoker 注入 / subscribe 通知 / clear。
 *
 * 后端契约来自 omni_lyrics/lyrics_chain.py LyricsResult.to_dict + lrc_parser.py。
 */
import { describe, expect, it, vi } from "vitest";

import {
  EMPTY_LYRICS_STATE,
  createLyricsStore,
  type LyricsInvoker,
  type LyricsToolResult,
} from "./lyricsStore";

/** 构造一个合法的 Word dict（IPC 边界原始数据，后端字段为 text）。 */
function makeWordDict(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return { time_s: 1.5, text: "故", ...overrides };
}

/** 构造一个合法的 LyricsLine dict（lrc_parser LyricsLine.to_dict）。 */
function makeLineDict(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    time_s: 1.0,
    text: "故事的小黄花",
    translation: null,
    words: null,
    ...overrides,
  };
}

/** 构造一个合法的 LyricsResult dict（lyrics_chain LyricsResult.to_dict）。 */
function makeLyricsResultDict(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    lyrics: "[00:01.00]故事的小黄花",
    source: "local_file",
    parsed: [makeLineDict()],
    ...overrides,
  };
}

/** fake invoker：按 tool 名分派预设结果，记录所有调用。 */
interface FakeInvokerOptions {
  results?: Record<string, LyricsToolResult<unknown>>;
  sequences?: Record<string, LyricsToolResult<unknown>[]>;
  defaultResult?: LyricsToolResult<unknown>;
}

function makeFakeInvoker(opts: FakeInvokerOptions = {}): {
  invoker: LyricsInvoker;
  calls: { tool: string; args?: Record<string, unknown> }[];
} {
  const calls: { tool: string; args?: Record<string, unknown> }[] = [];
  const seqCounters: Record<string, number> = {};
  const invoker: LyricsInvoker = async (tool, args) => {
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

const okLyrics = (overrides: Record<string, unknown> = {}): LyricsToolResult<unknown> => ({
  ok: true,
  data: makeLyricsResultDict(overrides),
});

// ---------------------------------------------------------------------------
// 初始状态
// ---------------------------------------------------------------------------
describe("lyricsStore 初始状态", () => {
  it("createLyricsStore 返回 EMPTY_LYRICS_STATE 副本", () => {
    const { invoker } = makeFakeInvoker();
    const store = createLyricsStore({ invoker });
    const state = store.getState();
    expect(state.currentLyrics).toBeNull();
    expect(state.currentIndex).toBe(-1);
    expect(state.currentWordIndex).toBeNull();
    expect(state.offsetS).toBe(0);
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  it("EMPTY_LYRICS_STATE 是冻结的初始快照", () => {
    expect(EMPTY_LYRICS_STATE.currentLyrics).toBeNull();
    expect(EMPTY_LYRICS_STATE.currentIndex).toBe(-1);
    expect(EMPTY_LYRICS_STATE.offsetS).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// subscribe
// ---------------------------------------------------------------------------
describe("lyricsStore subscribe", () => {
  it("状态变化时通知 listener", async () => {
    const { invoker } = makeFakeInvoker({
      results: { lyrics_get: okLyrics() },
    });
    const store = createLyricsStore({ invoker });
    const listener = vi.fn();
    const unsub = store.subscribe(listener);
    await store.fetchLyrics("s1");
    expect(listener).toHaveBeenCalled();
    unsub();
  });

  it("unsubscribe 后不再通知", async () => {
    const { invoker } = makeFakeInvoker({
      results: { lyrics_get: okLyrics() },
    });
    const store = createLyricsStore({ invoker });
    const listener = vi.fn();
    const unsub = store.subscribe(listener);
    unsub();
    await store.fetchLyrics("s1");
    expect(listener).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// fetchLyrics
// ---------------------------------------------------------------------------
describe("lyricsStore fetchLyrics", () => {
  it("成功时归一化并写入 currentLyrics，清空 error", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: {
        lyrics_get: okLyrics({
          lyrics: "[00:01.00]故事的小黄花",
          source: "local_file",
          parsed: [
            makeLineDict({ time_s: 1.0, text: "故事的小黄花", translation: "story" }),
            makeLineDict({ time_s: 5.0, text: "从出生那年就飘着", translation: null }),
          ],
        }),
      },
    });
    const store = createLyricsStore({ invoker });
    await store.fetchLyrics("s1");
    expect(calls[0]).toEqual({
      tool: "lyrics_get",
      args: { song_id: "s1" },
    });
    const state = store.getState();
    expect(state.currentLyrics).not.toBeNull();
    expect(state.currentLyrics?.source).toBe("local_file");
    expect(state.currentLyrics?.lyrics).toBe("[00:01.00]故事的小黄花");
    expect(state.currentLyrics?.parsed).toHaveLength(2);
    expect(state.currentLyrics?.parsed[0]?.text).toBe("故事的小黄花");
    expect(state.currentLyrics?.parsed[0]?.translation).toBe("story");
    expect(state.currentLyrics?.parsed[0]?.words).toBeNull();
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  it("传递 source 过滤参数", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: { lyrics_get: okLyrics() },
    });
    const store = createLyricsStore({ invoker });
    await store.fetchLyrics("s1", "embedded");
    expect(calls[0]?.args).toEqual({ song_id: "s1", source: "embedded" });
  });

  it("成功后 currentIndex 重置为 -1（等待 refreshCurrentLine）", async () => {
    const { invoker } = makeFakeInvoker({
      results: { lyrics_get: okLyrics() },
    });
    const store = createLyricsStore({ invoker });
    await store.fetchLyrics("s1");
    expect(store.getState().currentIndex).toBe(-1);
    expect(store.getState().currentWordIndex).toBeNull();
  });

  it("后端返回 error 时写入 state.error，currentLyrics 保持 null", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        lyrics_get: {
          ok: false,
          error: { code: "E_NOT_FOUND", message: "未找到歌曲" },
        },
      },
    });
    const store = createLyricsStore({ invoker });
    await store.fetchLyrics("missing");
    const state = store.getState();
    expect(state.currentLyrics).toBeNull();
    expect(state.error).toBe("未找到歌曲");
    expect(state.isLoading).toBe(false);
  });

  it("归一化拒绝非法 parsed（非数组 → 空列表，source 非法 → none）", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        lyrics_get: okLyrics({
          lyrics: null,
          source: "totally_invalid_source",
          parsed: "not-an-array",
        }),
      },
    });
    const store = createLyricsStore({ invoker });
    await store.fetchLyrics("s1");
    const state = store.getState();
    expect(state.currentLyrics).not.toBeNull();
    expect(state.currentLyrics?.source).toBe("none");
    expect(state.currentLyrics?.parsed).toEqual([]);
    expect(state.currentLyrics?.lyrics).toBeNull();
  });

  it("归一化过滤 parsed 中的非法行（缺 text / 非对象）", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        lyrics_get: okLyrics({
          source: "online",
          parsed: [
            makeLineDict({ time_s: 1.0, text: "合法行" }),
            null,
            { time_s: 2.0 }, // 缺 text
            "not-an-object",
            makeLineDict({ time_s: 3.0, text: "另一合法行" }),
          ],
        }),
      },
    });
    const store = createLyricsStore({ invoker });
    await store.fetchLyrics("s1");
    const parsed = store.getState().currentLyrics?.parsed ?? [];
    expect(parsed).toHaveLength(2);
    expect(parsed[0]?.text).toBe("合法行");
    expect(parsed[1]?.text).toBe("另一合法行");
  });

  it("归一化保留逐字 words，并映射后端 text → 前端 char", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        lyrics_get: okLyrics({
          source: "online",
          parsed: [
            makeLineDict({
              time_s: 1.0,
              text: "故事",
              words: [
                makeWordDict({ time_s: 1.0, text: "故" }),
                makeWordDict({ time_s: 1.5, text: "事" }),
                { time_s: "bad" }, // 非法 word，应被过滤
                null,
              ],
            }),
          ],
        }),
      },
    });
    const store = createLyricsStore({ invoker });
    await store.fetchLyrics("s1");
    const line = store.getState().currentLyrics?.parsed[0];
    expect(line?.words).not.toBeNull();
    expect(line?.words).toHaveLength(2);
    expect(line?.words?.[0]?.char).toBe("故");
    expect(line?.words?.[0]?.time_s).toBe(1.0);
    expect(line?.words?.[1]?.char).toBe("事");
  });
});

// ---------------------------------------------------------------------------
// refreshCurrentLine — 二分查找正确性
// ---------------------------------------------------------------------------
describe("lyricsStore refreshCurrentLine 二分查找", () => {
  /** 构造已知时间轴 store：[0.0, 2.0, 4.0, 6.0, 8.0]，无 words。 */
  function makeTimedStore(): ReturnType<typeof createLyricsStore> {
    const { invoker } = makeFakeInvoker({
      results: {
        lyrics_get: okLyrics({
          source: "local_file",
          parsed: [0, 2, 4, 6, 8].map((t) =>
            makeLineDict({ time_s: t, text: `line-${t}` }),
          ),
        }),
      },
    });
    return createLyricsStore({ invoker });
  }

  it("无歌词时 currentIndex 保持 -1", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        lyrics_get: okLyrics({ parsed: [], source: "none", lyrics: null }),
      },
    });
    const store = createLyricsStore({ invoker });
    await store.fetchLyrics("s1");
    store.refreshCurrentLine(5.0);
    expect(store.getState().currentIndex).toBe(-1);
    expect(store.getState().currentWordIndex).toBeNull();
  });

  it("position 落在某行时间内 → 返回该行索引", async () => {
    const store = makeTimedStore();
    await store.fetchLyrics("s1");
    store.refreshCurrentLine(3.0);
    expect(store.getState().currentIndex).toBe(1); // [0,2,4,6,8] → idx 1 (time 2.0)
    store.refreshCurrentLine(5.0);
    expect(store.getState().currentIndex).toBe(2); // idx 2 (time 4.0)
    store.refreshCurrentLine(7.5);
    expect(store.getState().currentIndex).toBe(3); // idx 3 (time 6.0)
  });

  it("position 恰好等于某行 time_s → 返回该行索引", async () => {
    const store = makeTimedStore();
    await store.fetchLyrics("s1");
    store.refreshCurrentLine(4.0);
    expect(store.getState().currentIndex).toBe(2);
  });

  it("position 小于所有行 time_s → 返回 0（第一行）", async () => {
    const store = makeTimedStore();
    await store.fetchLyrics("s1");
    store.refreshCurrentLine(0.5);
    expect(store.getState().currentIndex).toBe(0);
    store.refreshCurrentLine(0);
    expect(store.getState().currentIndex).toBe(0);
  });

  it("position 超过最后一行 → 返回最后一行索引", async () => {
    const store = makeTimedStore();
    await store.fetchLyrics("s1");
    store.refreshCurrentLine(100.0);
    expect(store.getState().currentIndex).toBe(4);
  });

  it("无歌词缓存时 refresh 是 no-op", () => {
    const { invoker } = makeFakeInvoker();
    const store = createLyricsStore({ invoker });
    store.refreshCurrentLine(5.0);
    expect(store.getState().currentIndex).toBe(-1);
  });

  it("偏移叠加：offsetS=1.0 → eff=position+1.0", async () => {
    // 用 makeTimedStore 拉到歌词，再用 setOffset 设偏移后 refresh
    const { invoker, calls } = makeFakeInvoker({
      results: {
        lyrics_get: okLyrics({
          source: "local_file",
          parsed: [0, 2, 4, 6, 8].map((t) => makeLineDict({ time_s: t, text: `l-${t}` })),
        }),
        lyrics_set_offset: { ok: true, data: { offset_s: 1.0 } },
      },
    });
    const store = createLyricsStore({ invoker });
    await store.fetchLyrics("s1");
    await store.setOffset(1.0);
    expect(calls.find((c) => c.tool === "lyrics_set_offset")).toEqual({
      tool: "lyrics_set_offset",
      args: { offset_s: 1.0 },
    });
    expect(store.getState().offsetS).toBe(1.0);
    // position=3.0 + offset=1.0 = eff=4.0 → 命中 idx 2 (time 4.0)
    store.refreshCurrentLine(3.0);
    expect(store.getState().currentIndex).toBe(2);
    // position=1.0 + offset=1.0 = eff=2.0 → 命中 idx 1 (time 2.0)
    store.refreshCurrentLine(1.0);
    expect(store.getState().currentIndex).toBe(1);
  });

  it("逐字行：currentWordIndex 跟随 position 推进", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        lyrics_get: okLyrics({
          source: "online",
          parsed: [
            makeLineDict({
              time_s: 1.0,
              text: "故事",
              words: [
                makeWordDict({ time_s: 1.0, text: "故" }),
                makeWordDict({ time_s: 1.5, text: "事" }),
              ],
            }),
            makeLineDict({ time_s: 3.0, text: "后续", words: null }),
          ],
        }),
      },
    });
    const store = createLyricsStore({ invoker });
    await store.fetchLyrics("s1");
    // position=1.2 → 行 idx 0 (time 1.0)，word idx 0 (time 1.0)
    store.refreshCurrentLine(1.2);
    expect(store.getState().currentIndex).toBe(0);
    expect(store.getState().currentWordIndex).toBe(0);
    // position=1.6 → 行 idx 0，word idx 1 (time 1.5)
    store.refreshCurrentLine(1.6);
    expect(store.getState().currentIndex).toBe(0);
    expect(store.getState().currentWordIndex).toBe(1);
    // position=3.5 → 行 idx 1 (无 words)，word null
    store.refreshCurrentLine(3.5);
    expect(store.getState().currentIndex).toBe(1);
    expect(store.getState().currentWordIndex).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// setOffset
// ---------------------------------------------------------------------------
describe("lyricsStore setOffset", () => {
  it("持久化到后端 lyrics_set_offset 并更新本地 offsetS", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: {
        lyrics_set_offset: { ok: true, data: { offset_s: 0.5 } },
      },
    });
    const store = createLyricsStore({ invoker });
    await store.setOffset(0.5);
    expect(calls[0]).toEqual({
      tool: "lyrics_set_offset",
      args: { offset_s: 0.5 },
    });
    expect(store.getState().offsetS).toBe(0.5);
  });

  it("后端返回归一化后的 offset（可能不同于入参）", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        lyrics_set_offset: { ok: true, data: { offset_s: 0.3 } },
      },
    });
    const store = createLyricsStore({ invoker });
    await store.setOffset(0.5);
    expect(store.getState().offsetS).toBe(0.3);
  });

  it("后端失败时 offsetS 不变，写入 error", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        lyrics_set_offset: {
          ok: false,
          error: { code: "E_INVALID_ARGS", message: "offset 非法" },
        },
      },
    });
    const store = createLyricsStore({ invoker });
    await store.setOffset(99);
    expect(store.getState().offsetS).toBe(0);
    expect(store.getState().error).toBe("offset 非法");
  });

  it("非有限数 setOffset 是 no-op", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: { lyrics_set_offset: { ok: true, data: { offset_s: 0 } } },
    });
    const store = createLyricsStore({ invoker });
    await store.setOffset(NaN);
    await store.setOffset(Infinity);
    expect(calls).toHaveLength(0);
    expect(store.getState().offsetS).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// searchLyrics / uploadLyrics
// ---------------------------------------------------------------------------
describe("lyricsStore searchLyrics", () => {
  it("调 lyrics_search 并返回归一化后的 songs 列表", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: {
        lyrics_search: {
          ok: true,
          data: {
            songs: [
              { id: "s1", name: "晴天", artists: ["周杰伦"], source: "netease" },
              { id: "s2", name: "稻香", artists: ["周杰伦"], source: "netease" },
            ],
            count: 2,
          },
        },
      },
    });
    const store = createLyricsStore({ invoker });
    const songs = await store.searchLyrics("晴天");
    expect(calls[0]).toEqual({
      tool: "lyrics_search",
      args: { keyword: "晴天" },
    });
    expect(songs).toHaveLength(2);
    expect(songs?.[0]?.id).toBe("s1");
    expect(songs?.[1]?.name).toBe("稻香");
  });

  it("后端失败时返回 null 并写 error", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        lyrics_search: {
          ok: false,
          error: { code: "E_SEARCH_FAILED", message: "搜索失败" },
        },
      },
    });
    const store = createLyricsStore({ invoker });
    const songs = await store.searchLyrics("x");
    expect(songs).toBeNull();
    expect(store.getState().error).toBe("搜索失败");
  });

  it("归一化过滤非法 song（缺 id/name）", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        lyrics_search: {
          ok: true,
          data: {
            songs: [
              { id: "s1", name: "晴天" },
              { id: "s2" }, // 缺 name
              { name: "无id" }, // 缺 id
              "not-an-object",
              null,
            ],
            count: 5,
          },
        },
      },
    });
    const store = createLyricsStore({ invoker });
    const songs = await store.searchLyrics("x");
    expect(songs).toHaveLength(1);
    expect(songs?.[0]?.id).toBe("s1");
  });
});

describe("lyricsStore uploadLyrics", () => {
  it("调 lyrics_upload 并返回 path", async () => {
    const { invoker, calls } = makeFakeInvoker({
      results: {
        lyrics_upload: { ok: true, data: { path: "/tmp/song.lrc" } },
      },
    });
    const store = createLyricsStore({ invoker });
    const path = await store.uploadLyrics("s1", "[00:01.00]hello");
    expect(calls[0]).toEqual({
      tool: "lyrics_upload",
      args: { song_id: "s1", content: "[00:01.00]hello" },
    });
    expect(path).toBe("/tmp/song.lrc");
  });

  it("后端失败时返回 null 并写 error", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        lyrics_upload: {
          ok: false,
          error: { code: "E_INVALID_ARGS", message: "仅本地源支持" },
        },
      },
    });
    const store = createLyricsStore({ invoker });
    const path = await store.uploadLyrics("s1", "text");
    expect(path).toBeNull();
    expect(store.getState().error).toBe("仅本地源支持");
  });
});

// ---------------------------------------------------------------------------
// clear
// ---------------------------------------------------------------------------
describe("lyricsStore clear", () => {
  it("清空 currentLyrics 与 currentIndex，保留 offsetS", async () => {
    const { invoker } = makeFakeInvoker({
      results: {
        lyrics_get: okLyrics(),
        lyrics_set_offset: { ok: true, data: { offset_s: 0.5 } },
      },
    });
    const store = createLyricsStore({ invoker });
    await store.fetchLyrics("s1");
    await store.setOffset(0.5);
    expect(store.getState().currentLyrics).not.toBeNull();
    store.clear();
    expect(store.getState().currentLyrics).toBeNull();
    expect(store.getState().currentIndex).toBe(-1);
    expect(store.getState().currentWordIndex).toBeNull();
    // offsetS 保留（用户偏好不随切歌重置）
    expect(store.getState().offsetS).toBe(0.5);
  });
});

// ---------------------------------------------------------------------------
// debugSetLyrics（E2E / 演示注入）
// ---------------------------------------------------------------------------
describe("lyricsStore debugSetLyrics", () => {
  it("直接注入歌词结果并清错误，绕过 IPC", async () => {
    // 先制造一个错误态（非 Tauri invoker 返回 E_NOT_TAURI）
    const store = createLyricsStore();
    await store.fetchLyrics("s1");
    expect(store.getState().error).not.toBeNull();

    store.debugSetLyrics({
      lyrics: "[00:01.00]夜航星\n[00:05.00]穿越暗房",
      source: "local_file",
      parsed: [
        { time_s: 1, text: "夜航星", translation: null, words: null },
        { time_s: 5, text: "穿越暗房", translation: null, words: null },
      ],
    });
    const state = store.getState();
    expect(state.error).toBeNull();
    expect(state.isLoading).toBe(false);
    expect(state.currentLyrics?.source).toBe("local_file");
    expect(state.currentLyrics?.parsed).toHaveLength(2);
    // 注入后 refreshCurrentLine 本地二分可正常定位
    store.refreshCurrentLine(5.2);
    expect(store.getState().currentIndex).toBe(1);
  });

  it("注入 null 等价清空（保留 offsetS）", () => {
    const store = createLyricsStore();
    store.debugSetLyrics({
      lyrics: "x",
      source: "online",
      parsed: [{ time_s: 0, text: "x", translation: null, words: null }],
    });
    store.debugSetLyrics(null);
    const state = store.getState();
    expect(state.currentLyrics).toBeNull();
    expect(state.currentIndex).toBe(-1);
    expect(state.currentWordIndex).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 非 Tauri 默认 invoker
// ---------------------------------------------------------------------------
describe("lyricsStore 默认 invoker（非 Tauri）", () => {
  it("非 Tauri 环境下 fetchLyrics 返回 E_NOT_TAURI 错误信封", async () => {
    // 不注入 invoker → 用 defaultInvoker → 非 Tauri → E_NOT_TAURI
    const store = createLyricsStore();
    await store.fetchLyrics("s1");
    const state = store.getState();
    expect(state.currentLyrics).toBeNull();
    expect(state.error).not.toBeNull();
    // state.error 仅存 message（与 musicStore 同款）；message 含「Tauri」关键词
    expect(state.error).toContain("Tauri");
    expect(state.isLoading).toBe(false);
  });
});
