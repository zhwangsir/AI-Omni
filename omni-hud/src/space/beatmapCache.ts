/**
 * beatmapCache 节拍缓存（M21.6）：
 * 避免对同一曲目重复 BPM/节拍分析——首次分析后持久化到存储抽象，
 * 后续播放直接读缓存。存储可为 fs（~/.ai-omni/cache/beatmaps/）或内存。
 *
 * 设计：
 * - Beatmap 数据结构：{ songId, bpm, beatTimes, duration, analyzedAt }
 * - BeatmapStorage 抽象：read/write/delete/list（fs / memory 双实现）
 * - BeatmapCache：getOrAnalyze(songId, analyzer) 命中缓存或调 analyzer
 *   + 并发去重（同 songId 并发只调一次 analyzer）
 *   + 存储损坏容错（非法 JSON / 结构校验失败 → 回退 analyzer）
 * - 序列化纯函数：serializeBeatmap / parseBeatmap（JSON + 严格校验）
 *
 * 纯逻辑模块：无 fs / DOM 依赖，存储抽象注入，可独立单测。
 */

/** 节拍图：一首曲目的 BPM + 拍点时间序列。 */
export interface Beatmap {
  /** 曲目唯一标识（与 musicStore current_song.id 对齐）。 */
  readonly songId: string;
  /** 估算 BPM（beats per minute）。 */
  readonly bpm: number;
  /** 拍点时间序列（秒，升序）。 */
  readonly beatTimes: readonly number[];
  /** 曲目时长（秒）。 */
  readonly duration: number;
  /** 分析时间戳（ms epoch）。 */
  readonly analyzedAt: number;
}

/**
 * 存储抽象：fs / memory / 其他实现的统一契约。
 * read 返回 unknown：存储边界不受信任，cache 侧经 validateBeatmap 防御性校验
 * （fs 实现可能返回损坏 JSON 字符串 / 部分反序列化对象 / null）。
 * 诚实实现（memory）返回 Beatmap 对象；fs 实现返回 JSON 字符串由 parseBeatmap 解析。
 */
export interface BeatmapStorage {
  /** 读取 songId 对应的 beatmap；未命中返回 null。返回值经 cache 侧防御性校验。 */
  read(songId: string): Promise<unknown | null>;
  /** 写入 beatmap；覆盖同 songId 旧条目。 */
  write(beatmap: Beatmap): Promise<void>;
  /** 删除 songId 对应条目；未命中幂等。 */
  delete(songId: string): Promise<void>;
  /** 列出所有已缓存 songId。 */
  list(): Promise<readonly string[]>;
}

/** 节拍分析器：给定 songId 返回 Beatmap 或 null（分析失败）。 */
export type BeatmapAnalyzer = (songId: string) => Promise<Beatmap | null>;

/** 序列化 Beatmap 为 JSON 字符串（fs 实现内部使用）。 */
export function serializeBeatmap(beatmap: Beatmap): string {
  return JSON.stringify(beatmap);
}

/**
 * 解析 JSON 字符串为 Beatmap；严格结构校验，非法返回 null（不抛错）。
 * fs 实现内部使用：从磁盘读 JSON 后校验。
 * 校验：songId 非空字符串、bpm 正数、beatTimes 非负升序数值数组、
 * duration 非负数、analyzedAt 非负数。
 */
export function parseBeatmap(json: string): Beatmap | null {
  if (typeof json !== "string" || json.length === 0) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(json);
  } catch {
    return null;
  }
  return validateBeatmap(parsed);
}

/**
 * 校验未知值是否为合法 Beatmap 结构；非法返回 null。
 * 存储层 read 后调用此函数做防御性校验（存储实现可能返回损坏数据 / 字符串 / 结构非法对象）。
 */
export function validateBeatmap(value: unknown): Beatmap | null {
  if (typeof value !== "object" || value === null) return null;
  const obj = value as Record<string, unknown>;
  const { songId, bpm, beatTimes, duration, analyzedAt } = obj;
  if (typeof songId !== "string" || songId.length === 0) return null;
  if (typeof bpm !== "number" || !Number.isFinite(bpm) || bpm <= 0) return null;
  if (!Array.isArray(beatTimes)) return null;
  for (const t of beatTimes) {
    if (typeof t !== "number" || !Number.isFinite(t) || t < 0) return null;
  }
  // 升序校验（允许相等，不允许倒序）
  for (let i = 1; i < beatTimes.length; i += 1) {
    if (beatTimes[i]! < beatTimes[i - 1]!) return null;
  }
  if (typeof duration !== "number" || !Number.isFinite(duration) || duration < 0) return null;
  if (typeof analyzedAt !== "number" || !Number.isFinite(analyzedAt) || analyzedAt < 0) return null;
  return {
    songId,
    bpm,
    beatTimes: beatTimes as number[],
    duration,
    analyzedAt,
  };
}

/** 内存存储实现（测试 / 降级用）。直接持有 Beatmap 对象，无序列化开销。 */
export function createMemoryBeatmapStorage(): BeatmapStorage {
  const map = new Map<string, Beatmap>();
  return {
    async read(songId) {
      return map.get(songId) ?? null;
    },
    async write(beatmap) {
      map.set(beatmap.songId, beatmap);
    },
    async delete(songId) {
      map.delete(songId);
    },
    async list() {
      return [...map.keys()];
    },
  };
}

/** BeatmapCache：缓存 + 并发去重 + 存储容错。 */
export interface BeatmapCache {
  /** 命中缓存直接返回；未命中调 analyzer 并写入。并发同 songId 只调一次。 */
  getOrAnalyze(songId: string, analyzer: BeatmapAnalyzer): Promise<Beatmap | null>;
  /** 直接读缓存；未命中或损坏返回 null。 */
  get(songId: string): Promise<Beatmap | null>;
  /** 删除条目；未命中幂等。 */
  invalidate(songId: string): Promise<void>;
  /** 清空所有缓存。 */
  clear(): Promise<void>;
  /** 列出所有已缓存 songId。 */
  list(): Promise<readonly string[]>;
}

export function createBeatmapCache(storage: BeatmapStorage): BeatmapCache {
  // 并发去重：同 songId 的进行中分析共享同一 Promise
  const inFlight = new Map<string, Promise<Beatmap | null>>();

  const safeRead = async (songId: string): Promise<Beatmap | null> => {
    try {
      const raw = await storage.read(songId);
      if (raw === null) return null;
      // 防御性校验：存储实现可能返回 Beatmap 对象（memory）或字符串/损坏数据（fs / 测试 fake）。
      // 字符串先 JSON.parse，对象直接 validateBeatmap；任一环节失败回退 null（视为未命中）。
      if (typeof raw === "string") {
        return parseBeatmap(raw);
      }
      return validateBeatmap(raw);
    } catch {
      // 存储故障：视为未命中，回退 analyzer
      return null;
    }
  };

  return {
    async getOrAnalyze(songId, analyzer) {
      // 先查缓存
      const cached = await safeRead(songId);
      if (cached !== null) return cached;
      // 并发去重：同 songId 共享进行中分析
      const existing = inFlight.get(songId);
      if (existing) return existing;
      const promise = (async (): Promise<Beatmap | null> => {
        try {
          const result = await analyzer(songId);
          if (result !== null) {
            try {
              await storage.write(result);
            } catch {
              // 写入失败不阻塞返回（缓存写入是 best-effort）
            }
          }
          return result;
        } finally {
          inFlight.delete(songId);
        }
      })();
      inFlight.set(songId, promise);
      return promise;
    },

    async get(songId) {
      return safeRead(songId);
    },

    async invalidate(songId) {
      try {
        await storage.delete(songId);
      } catch {
        // 删除失败静默（幂等语义）
      }
    },

    async clear() {
      const ids = await storage.list().catch(() => []);
      await Promise.all(
        ids.map((id) =>
          storage.delete(id).catch(() => {
            /* 个别删除失败不阻塞整体清空 */
          }),
        ),
      );
    },

    async list() {
      try {
        return await storage.list();
      } catch {
        return [];
      }
    },
  };
}
