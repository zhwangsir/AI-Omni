/**
 * beatmapCache 节拍缓存测试（M21.6 TDD）：
 * 避免对同一曲目重复 BPM/节拍分析——首次分析后持久化，
 * 后续播放直接读缓存。
 *
 * 设计：
 * - Beatmap 数据结构：{ songId, bpm, beatTimes, duration, analyzedAt }
 * - BeatmapStorage 抽象：read/write/delete/list（fs / memory 双实现）
 * - BeatmapCache：getOrAnalyze(songId, analyzer) 命中缓存或调 analyzer
 * - 序列化纯函数：serializeBeatmap / parseBeatmap（JSON + 校验）
 *
 * 纯逻辑测试：MemoryBeatmapStorage，不碰真实 fs。
 */
import { describe, expect, it, vi } from "vitest";

import {
  type Beatmap,
  type BeatmapStorage,
  type BeatmapAnalyzer,
  createBeatmapCache,
  parseBeatmap,
  serializeBeatmap,
  createMemoryBeatmapStorage,
} from "./beatmapCache";

const SAMPLE_BEATMAP: Beatmap = {
  songId: "song-001",
  bpm: 128,
  beatTimes: [0.5, 1.0, 1.5, 2.0],
  duration: 180,
  analyzedAt: 1700000000000,
};

describe("serializeBeatmap / parseBeatmap 序列化", () => {
  it("serialize 产出合法 JSON 字符串", () => {
    const json = serializeBeatmap(SAMPLE_BEATMAP);
    expect(typeof json).toBe("string");
    const parsed = JSON.parse(json);
    expect(parsed.songId).toBe("song-001");
    expect(parsed.bpm).toBe(128);
    expect(parsed.beatTimes).toEqual([0.5, 1.0, 1.5, 2.0]);
  });

  it("parse 合法 JSON 还原 Beatmap", () => {
    const json = serializeBeatmap(SAMPLE_BEATMAP);
    const parsed = parseBeatmap(json);
    expect(parsed).toEqual(SAMPLE_BEATMAP);
  });

  it("parse 非法 JSON 返回 null（不抛错）", () => {
    expect(parseBeatmap("not json")).toBeNull();
    expect(parseBeatmap("")).toBeNull();
    expect(parseBeatmap("{invalid")).toBeNull();
  });

  it("parse 缺字段返回 null（结构校验）", () => {
    expect(parseBeatmap(JSON.stringify({ songId: "x" }))).toBeNull();
    expect(parseBeatmap(JSON.stringify({ songId: "x", bpm: 120 }))).toBeNull();
    expect(
      parseBeatmap(JSON.stringify({ songId: "x", bpm: 120, beatTimes: [], duration: 0 })),
    ).toBeNull(); // 缺 analyzedAt
  });

  it("parse 类型错误返回 null（bpm 非数字、beatTimes 非数组）", () => {
    expect(
      parseBeatmap(
        JSON.stringify({
          songId: "x",
          bpm: "fast",
          beatTimes: [],
          duration: 0,
          analyzedAt: 0,
        }),
      ),
    ).toBeNull();
    expect(
      parseBeatmap(
        JSON.stringify({
          songId: "x",
          bpm: 120,
          beatTimes: "not array",
          duration: 0,
          analyzedAt: 0,
        }),
      ),
    ).toBeNull();
  });

  it("parse beatTimes 负值或 NaN 返回 null（数据完整性）", () => {
    expect(
      parseBeatmap(
        JSON.stringify({
          songId: "x",
          bpm: 120,
          beatTimes: [1, -1, 2],
          duration: 0,
          analyzedAt: 0,
        }),
      ),
    ).toBeNull();
    expect(
      parseBeatmap(
        JSON.stringify({
          songId: "x",
          bpm: 120,
          beatTimes: [1, Number.NaN],
          duration: 0,
          analyzedAt: 0,
        }),
      ),
    ).toBeNull();
  });
});

describe("createMemoryBeatmapStorage 内存存储", () => {
  it("write 后 read 返回同一 beatmap", async () => {
    const storage = createMemoryBeatmapStorage();
    await storage.write(SAMPLE_BEATMAP);
    const read = await storage.read("song-001");
    expect(read).toEqual(SAMPLE_BEATMAP);
  });

  it("read 未命中返回 null", async () => {
    const storage = createMemoryBeatmapStorage();
    const read = await storage.read("missing");
    expect(read).toBeNull();
  });

  it("delete 后 read 返回 null", async () => {
    const storage = createMemoryBeatmapStorage();
    await storage.write(SAMPLE_BEATMAP);
    await storage.delete("song-001");
    expect(await storage.read("song-001")).toBeNull();
  });

  it("delete 未命中幂等（不抛错）", async () => {
    const storage = createMemoryBeatmapStorage();
    await expect(storage.delete("missing")).resolves.not.toThrow();
  });

  it("list 返回所有已缓存 songId", async () => {
    const storage = createMemoryBeatmapStorage();
    await storage.write(SAMPLE_BEATMAP);
    await storage.write({ ...SAMPLE_BEATMAP, songId: "song-002" });
    const ids = await storage.list();
    expect([...ids].sort()).toEqual(["song-001", "song-002"]);
  });

  it("write 覆盖同 songId 旧条目", async () => {
    const storage = createMemoryBeatmapStorage();
    await storage.write(SAMPLE_BEATMAP);
    await storage.write({ ...SAMPLE_BEATMAP, bpm: 140 });
    const read = await storage.read("song-001");
    expect((read as Beatmap | null)?.bpm).toBe(140);
  });
});

describe("createBeatmapCache getOrAnalyze", () => {
  it("缓存未命中时调 analyzer 并写入存储", async () => {
    const storage = createMemoryBeatmapStorage();
    const analyzer = vi.fn().mockResolvedValue(SAMPLE_BEATMAP);
    const cache = createBeatmapCache(storage);
    const result = await cache.getOrAnalyze("song-001", analyzer);
    expect(result).toEqual(SAMPLE_BEATMAP);
    expect(analyzer).toHaveBeenCalledTimes(1);
    expect(analyzer).toHaveBeenCalledWith("song-001");
    // 已写入存储
    expect(await storage.read("song-001")).toEqual(SAMPLE_BEATMAP);
  });

  it("缓存命中时不调 analyzer（避免重复分析）", async () => {
    const storage = createMemoryBeatmapStorage();
    await storage.write(SAMPLE_BEATMAP);
    const analyzer = vi.fn().mockResolvedValue(SAMPLE_BEATMAP);
    const cache = createBeatmapCache(storage);
    const result = await cache.getOrAnalyze("song-001", analyzer);
    expect(result).toEqual(SAMPLE_BEATMAP);
    expect(analyzer).not.toHaveBeenCalled();
  });

  it("analyzer 抛错时不写入缓存，错误向上传播", async () => {
    const storage = createMemoryBeatmapStorage();
    const analyzer = vi.fn().mockRejectedValue(new Error("analysis failed"));
    const cache = createBeatmapCache(storage);
    await expect(cache.getOrAnalyze("song-001", analyzer)).rejects.toThrow("analysis failed");
    expect(await storage.read("song-001")).toBeNull();
  });

  it("analyzer 返回 null 不写入缓存", async () => {
    const storage = createMemoryBeatmapStorage();
    const analyzer = vi.fn().mockResolvedValue(null);
    const cache = createBeatmapCache(storage);
    const result = await cache.getOrAnalyze("song-001", analyzer);
    expect(result).toBeNull();
    expect(await storage.read("song-001")).toBeNull();
  });

  it("并发 getOrAnalyze 同 songId：analyzer 只调一次（去重）", async () => {
    const storage = createMemoryBeatmapStorage();
    let callCount = 0;
    const analyzer = vi.fn().mockImplementation(async () => {
      callCount += 1;
      await new Promise((r) => setTimeout(r, 10));
      return SAMPLE_BEATMAP;
    });
    const cache = createBeatmapCache(storage);
    const [a, b, c] = await Promise.all([
      cache.getOrAnalyze("song-001", analyzer),
      cache.getOrAnalyze("song-001", analyzer),
      cache.getOrAnalyze("song-001", analyzer),
    ]);
    expect(a).toEqual(SAMPLE_BEATMAP);
    expect(b).toEqual(SAMPLE_BEATMAP);
    expect(c).toEqual(SAMPLE_BEATMAP);
    expect(callCount).toBe(1);
  });
});

describe("createBeatmapCache get / invalidate / clear", () => {
  it("get 命中返回 beatmap，未命中返回 null", async () => {
    const storage = createMemoryBeatmapStorage();
    await storage.write(SAMPLE_BEATMAP);
    const cache = createBeatmapCache(storage);
    expect(await cache.get("song-001")).toEqual(SAMPLE_BEATMAP);
    expect(await cache.get("missing")).toBeNull();
  });

  it("invalidate 删除条目，后续 get 返回 null", async () => {
    const storage = createMemoryBeatmapStorage();
    await storage.write(SAMPLE_BEATMAP);
    const cache = createBeatmapCache(storage);
    await cache.invalidate("song-001");
    expect(await cache.get("song-001")).toBeNull();
  });

  it("invalidate 未命中幂等", async () => {
    const storage = createMemoryBeatmapStorage();
    const cache = createBeatmapCache(storage);
    await expect(cache.invalidate("missing")).resolves.not.toThrow();
  });

  it("clear 清空所有缓存", async () => {
    const storage = createMemoryBeatmapStorage();
    await storage.write(SAMPLE_BEATMAP);
    await storage.write({ ...SAMPLE_BEATMAP, songId: "song-002" });
    const cache = createBeatmapCache(storage);
    await cache.clear();
    expect(await cache.get("song-001")).toBeNull();
    expect(await cache.get("song-002")).toBeNull();
    expect(await storage.list()).toEqual([]);
  });

  it("list 返回所有已缓存 songId", async () => {
    const storage = createMemoryBeatmapStorage();
    await storage.write(SAMPLE_BEATMAP);
    await storage.write({ ...SAMPLE_BEATMAP, songId: "song-002" });
    const cache = createBeatmapCache(storage);
    const ids = await cache.list();
    expect([...ids].sort()).toEqual(["song-001", "song-002"]);
  });
});

describe("createBeatmapCache 存储损坏容错", () => {
  it("存储返回非法 JSON 时 get 返回 null（不抛错）", async () => {
    const corruptStorage: BeatmapStorage = {
      read: async () => "corrupt json",
      write: async () => {},
      delete: async () => {},
      list: async () => [],
    };
    const cache = createBeatmapCache(corruptStorage);
    expect(await cache.get("song-001")).toBeNull();
  });

  it("存储返回结构非法 beatmap 时 get 返回 null", async () => {
    const corruptStorage: BeatmapStorage = {
      read: async () => JSON.stringify({ songId: "x" }),
      write: async () => {},
      delete: async () => {},
      list: async () => [],
    };
    const cache = createBeatmapCache(corruptStorage);
    expect(await cache.get("song-001")).toBeNull();
  });

  it("存储 read 抛错时 get 返回 null（隔离存储故障）", async () => {
    const throwingStorage: BeatmapStorage = {
      read: async () => {
        throw new Error("fs error");
      },
      write: async () => {},
      delete: async () => {},
      list: async () => [],
    };
    const cache = createBeatmapCache(throwingStorage);
    expect(await cache.get("song-001")).toBeNull();
  });

  it("getOrAnalyze 缓存损坏时回退到 analyzer（降级而非失败）", async () => {
    const corruptStorage: BeatmapStorage = {
      read: async () => "corrupt json",
      write: async () => {},
      delete: async () => {},
      list: async () => [],
    };
    const analyzer: BeatmapAnalyzer = vi.fn().mockResolvedValue(SAMPLE_BEATMAP);
    const cache = createBeatmapCache(corruptStorage);
    const result = await cache.getOrAnalyze("song-001", analyzer);
    expect(result).toEqual(SAMPLE_BEATMAP);
    expect(analyzer).toHaveBeenCalledTimes(1);
  });
});
