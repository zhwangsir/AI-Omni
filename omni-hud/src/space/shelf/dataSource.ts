/**
 * shelf/dataSource 卡片数据源抽象与适配器（M20.4）。
 *
 * 设计决策 D20.4：CardDataSource 接口抽象「卡片内容来源」——
 * 歌单（libraryStore playlists）/ 对话历史（agentStore messages）/
 * 工具结果（agentStore toolCalls）/ 推荐卡片（混合）。每个数据源实现 toCards()
 * 把领域模型映射为统一的 CardData[]，ShelfStage 不感知具体领域。
 *
 * 框架无关订阅模式（与 musicStore / agentStore 同款）；适配器 subscribe 透传到源 store。
 * composeDataSources 合并多数据源（按顺序拼接卡片，订阅透传到全部子源）。
 *
 * 不依赖 React / three；输入领域模型，输出 CardData[]。
 */
import type { Message, ToolCallRecord } from "../../components/agent/types";
import { getAssistantLabel } from "../../store/identityStore";
import type { Playlist } from "../../store/libraryStore";
import type { Song } from "../../store/musicStore";

/** 卡片内容类型（决定渲染图标 / 兜底色）。 */
export type CardKind = "playlist" | "message" | "tool_result" | "recommendation";

/** 统一卡片数据契约（ShelfStage 消费）。 */
export interface CardData {
  /** 唯一 ID（领域模型 id 字符串化）。 */
  readonly id: string;
  /** 内容类型。 */
  readonly kind: CardKind;
  /** 标题（卡片下半显示，≤14 字符）。 */
  readonly title: string;
  /** 副标题（≤18 字符）。 */
  readonly subtitle: string;
  /** 封面 URL（可选，null = 显示标题纹理兜底）。 */
  readonly coverUrl: string | null;
  /** 领域原始数据（点击回调时透传，ShelfStage 不解析）。 */
  readonly payload: Record<string, unknown>;
}

/** CardDataSource 抽象接口（ShelfStage 消费方）。 */
export interface CardDataSource {
  /** 取当前卡片列表快照。 */
  getCards(): readonly CardData[];
  /** 订阅卡片列表变化（数据源更新时触发）。 */
  subscribe(listener: () => void): () => void;
}

/** 把 CardKind 映射为兜底色（无封面时显示，Film Atelier 风格暗房配色）。 */
export const KIND_FALLBACK_COLORS: ReadonlyRecord<CardKind, string> = {
  playlist: "#3a2f24", // 显影琥珀暗调
  message: "#242a33", // 银盐冷灰暗调
  tool_result: "#2a2424", // 暗房安全灯暗调
  recommendation: "#2d2a33", // 混合暗紫
};

/** Readonly Record 别名（避免循环 Record 类型工具）。 */
export type ReadonlyRecord<K extends string, V> = { readonly [key in K]: V };

// ---------------------------------------------------------------------------
// 适配器：领域模型 → CardData[]
// ---------------------------------------------------------------------------

/** 标题裁剪到 20 字符（卡片下半显示约束，兼容 ASCII 工具名与 CJK 标题）。 */
function clampTitle(text: string): string {
  return text.slice(0, 20);
}

/** 副标题裁剪到 24 字符。 */
function clampSubtitle(text: string): string {
  return text.slice(0, 24);
}

/** Playlist[] → CardData[]（kind=playlist）。 */
export function playlistToCards(playlists: readonly Playlist[]): readonly CardData[] {
  return playlists.map((p) => ({
    id: `playlist-${p.id}`,
    kind: "playlist" as const,
    title: clampTitle(p.name),
    subtitle: clampSubtitle(`${p.song_count} 首`),
    coverUrl: null,
    payload: { id: p.id, name: p.name, song_count: p.song_count },
  }));
}

/** Message[] → CardData[]（kind=message，取最近 limit 条，默认全部）。 */
export function messagesToCards(messages: readonly Message[], limit?: number): readonly CardData[] {
  const slice = limit !== undefined ? messages.slice(-limit) : messages;
  return slice.map((m) => ({
    id: `message-${m.id}`,
    kind: "message" as const,
    title: clampTitle(m.text),
    subtitle: clampSubtitle(getAssistantLabel(m.role)),
    coverUrl: null,
    payload: { id: m.id, role: m.role, text: m.text, timestamp: m.timestamp },
  }));
}

/** ToolCallRecord[] → CardData[]（kind=tool_result）。 */
export function toolCallsToCards(calls: readonly ToolCallRecord[]): readonly CardData[] {
  return calls.map((c) => ({
    id: `tool-${c.id}`,
    kind: "tool_result" as const,
    title: clampTitle(c.toolName),
    subtitle: clampSubtitle(
      c.status === "success" ? "成功" : c.status === "error" ? "失败" : "进行中",
    ),
    coverUrl: null,
    payload: c as unknown as Record<string, unknown>,
  }));
}

/** Song[] → CardData[]（kind=recommendation）。 */
export function recommendationsToCards(songs: readonly Song[]): readonly CardData[] {
  return songs.map((s) => ({
    id: `rec-${s.id}`,
    kind: "recommendation" as const,
    title: clampTitle(s.name),
    subtitle: clampSubtitle(
      s.artists.length > 0 ? s.artists.join(" / ") : "未知艺术家",
    ),
    coverUrl: s.cover_url,
    payload: { id: s.id, name: s.name },
  }));
}

// ---------------------------------------------------------------------------
// 订阅式数据源（与 libraryStore / agentStore 同构）
// ---------------------------------------------------------------------------

/** 最小 store 契约（与 libraryStore / agentStore 的 getState/subscribe 对齐）。 */
export interface ReadableStore<T> {
  getState: () => T;
  subscribe: (listener: () => void) => () => void;
}

/** libraryStore 状态切片（含 playlists）。 */
export interface PlaylistStoreSlice {
  readonly playlists: readonly Playlist[];
}

/** agentStore 状态切片（含 messages）。 */
export interface MessageStoreSlice {
  readonly messages: readonly Message[];
}

/** agentStore 状态切片（含 currentToolCalls）。 */
export interface ToolCallStoreSlice {
  readonly currentToolCalls: readonly ToolCallRecord[];
}

/**
 * 创建歌单数据源：libraryStore.playlists → CardData[]（kind=playlist）。
 */
export function createPlaylistDataSource(
  store: ReadableStore<PlaylistStoreSlice>,
): CardDataSource {
  return {
    getCards: () => playlistToCards(store.getState().playlists),
    subscribe: (listener) => store.subscribe(listener),
  };
}

/**
 * 创建对话历史数据源：agentStore.messages → CardData[]（kind=message，最近 limit 条）。
 */
export function createMessageDataSource(
  store: ReadableStore<MessageStoreSlice>,
  limit?: number,
): CardDataSource {
  return {
    getCards: () => messagesToCards(store.getState().messages, limit),
    subscribe: (listener) => store.subscribe(listener),
  };
}

/**
 * 创建工具结果数据源：agentStore.currentToolCalls → CardData[]（kind=tool_result）。
 */
export function createToolCallDataSource(
  store: ReadableStore<ToolCallStoreSlice>,
): CardDataSource {
  return {
    getCards: () => toolCallsToCards(store.getState().currentToolCalls),
    subscribe: (listener) => store.subscribe(listener),
  };
}

// ---------------------------------------------------------------------------
// 组合器：合并多数据源
// ---------------------------------------------------------------------------

/**
 * 合并多个 CardDataSource 为单一数据源。
 * - getCards 按顺序拼接所有子源的卡片
 * - subscribe 透传到所有子源（任一子源变化都触发外层监听器）
 * - unsubscribe 解除全部子源监听
 */
export function composeDataSources(sources: readonly CardDataSource[]): CardDataSource {
  return {
    getCards: () => {
      const all: CardData[] = [];
      for (const src of sources) {
        all.push(...src.getCards());
      }
      return all;
    },
    subscribe: (listener) => {
      const unsubs = sources.map((s) => s.subscribe(listener));
      return () => {
        for (const unsub of unsubs) unsub();
      };
    },
  };
}
