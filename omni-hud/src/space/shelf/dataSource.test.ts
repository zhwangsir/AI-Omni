/**
 * shelf/dataSource 卡片数据源适配器（M20.4 TDD 红）：
 * - playlistToCards：libraryStore.Playlist[] → CardData[]（kind=playlist）
 * - messagesToCards：agentStore.Message[] → CardData[]（kind=message，最近 N 条）
 * - toolCallsToCards：ToolCallRecord[] → CardData[]（kind=tool_result）
 * - recommendationsToCards：混合数据 → CardData[]（kind=recommendation）
 * - createPlaylistDataSource / createMessageDataSource / createToolCallDataSource：
 *   框架无关订阅模式 CardDataSource 实现，subscribe 透传到源 store
 * - 合并多数据源的 createCompositeDataSource
 *
 * 纯逻辑模块：不依赖 React / three；输入领域模型，输出 CardData[]。
 */
import { describe, expect, it, vi } from "vitest";

import type { Message, ToolCallRecord } from "../../components/agent/types";
import type { Playlist } from "../../store/libraryStore";
import type { Song } from "../../store/musicStore";

import {
  composeDataSources,
  createMessageDataSource,
  createPlaylistDataSource,
  createToolCallDataSource,
  messagesToCards,
  playlistToCards,
  recommendationsToCards,
  toolCallsToCards,
  type CardDataSource,
} from "./dataSource";

const PLAYLISTS: Playlist[] = [
  { id: 1, name: "夜行", created_at: 0, updated_at: 0, song_count: 12 },
  { id: 2, name: "晨光", created_at: 0, updated_at: 0, song_count: 8 },
  { id: 3, name: "雨夜", created_at: 0, updated_at: 0, song_count: 15 },
];

const MESSAGES: Message[] = [
  { id: "u1", role: "user", text: "今天天气怎么样", timestamp: 1000 },
  { id: "a1", role: "assistant", text: "北京今天晴朗，最高气温 25 度。", timestamp: 1100 },
  { id: "u2", role: "user", text: "播放一首轻音乐", timestamp: 2000 },
  { id: "a2", role: "assistant", text: "好的，正在为您播放夜曲。", timestamp: 2100 },
];

const TOOL_CALLS: ToolCallRecord[] = [
  {
    id: "tc1",
    toolName: "home_control_light",
    params: { room: "客厅", action: "on" },
    result: '{"ok": true}',
    status: "success",
    timestamp: 1500,
  },
  {
    id: "tc2",
    toolName: "music_play",
    params: { keyword: "夜曲" },
    result: null,
    status: "pending",
    timestamp: 1800,
  },
];

describe("playlistToCards 歌单适配", () => {
  it("Playlist[] → CardData[]（kind=playlist，title=name，subtitle=N 首）", () => {
    const cards = playlistToCards(PLAYLISTS);
    expect(cards).toHaveLength(3);
    expect(cards[0]!.kind).toBe("playlist");
    expect(cards[0]!.title).toBe("夜行");
    expect(cards[0]!.subtitle).toBe("12 首");
    expect(cards[0]!.id).toBe("playlist-1");
    expect(cards[0]!.payload).toEqual({ id: 1, name: "夜行", song_count: 12 });
  });

  it("空数组返回空", () => {
    expect(playlistToCards([])).toEqual([]);
  });

  it("coverUrl 始终为 null（Playlist 无封面字段）", () => {
    const cards = playlistToCards(PLAYLISTS);
    for (const c of cards) expect(c.coverUrl).toBeNull();
  });
});

describe("messagesToCards 对话历史适配", () => {
  it("Message[] → CardData[]（kind=message，取最近 N 条）", () => {
    const cards = messagesToCards(MESSAGES, 2);
    expect(cards).toHaveLength(2);
    expect(cards[0]!.kind).toBe("message");
    // 最近 2 条：u2 + a2
    expect(cards[0]!.id).toBe("message-u2");
    expect(cards[1]!.id).toBe("message-a2");
  });

  it("title 取消息前 20 字符，subtitle 显示角色", () => {
    // slice(-1) 返回最后一条消息（a2: "好的，正在为您播放夜曲。"）
    const cards = messagesToCards(MESSAGES, 1);
    expect(cards[0]!.title).toBe("好的，正在为您播放夜曲。");
    expect(cards[0]!.subtitle).toBe("雪莉");
  });

  it("assistant 消息 subtitle 显示「雪莉」", () => {
    const cards = messagesToCards([MESSAGES[1]!], 5);
    expect(cards[0]!.subtitle).toBe("雪莉");
  });

  it("不传 limit 时取全部", () => {
    expect(messagesToCards(MESSAGES)).toHaveLength(4);
  });

  it("空数组返回空", () => {
    expect(messagesToCards([])).toEqual([]);
  });
});

describe("toolCallsToCards 工具结果适配", () => {
  it("ToolCallRecord[] → CardData[]（kind=tool_result，title=工具名）", () => {
    const cards = toolCallsToCards(TOOL_CALLS);
    expect(cards).toHaveLength(2);
    expect(cards[0]!.kind).toBe("tool_result");
    expect(cards[0]!.title).toBe("home_control_light");
    expect(cards[0]!.subtitle).toBe("成功");
  });

  it("pending 状态 subtitle 显示「进行中」", () => {
    const cards = toolCallsToCards([TOOL_CALLS[1]!]);
    expect(cards[0]!.subtitle).toBe("进行中");
  });

  it("payload 携带完整 ToolCallRecord", () => {
    const cards = toolCallsToCards(TOOL_CALLS);
    expect(cards[0]!.payload).toEqual(TOOL_CALLS[0]);
  });
});

describe("recommendationsToCards 推荐适配", () => {
  it("Song[] → CardData[]（kind=recommendation，title=name，subtitle=artists）", () => {
    const songs: Song[] = [
      {
        id: "s1",
        name: "夜曲",
        artists: ["周杰伦"],
        album: "十一月的萧邦",
        duration_s: 223,
        url: null,
        lyrics: null,
        cover_url: "https://example.com/cover.jpg",
        source: "netease",
      },
    ];
    const cards = recommendationsToCards(songs);
    expect(cards).toHaveLength(1);
    expect(cards[0]!.kind).toBe("recommendation");
    expect(cards[0]!.title).toBe("夜曲");
    expect(cards[0]!.subtitle).toBe("周杰伦");
    expect(cards[0]!.coverUrl).toBe("https://example.com/cover.jpg");
    expect(cards[0]!.payload).toEqual({ id: "s1", name: "夜曲" });
  });

  it("多歌手合并为「A / B」", () => {
    const songs: Song[] = [
      {
        id: "s2",
        name: "合唱",
        artists: ["A", "B"],
        album: null,
        duration_s: 200,
        url: null,
        lyrics: null,
        cover_url: null,
        source: "local",
      },
    ];
    const cards = recommendationsToCards(songs);
    expect(cards[0]!.subtitle).toBe("A / B");
  });

  it("无歌手时 subtitle 显示「未知艺术家」", () => {
    const songs: Song[] = [
      {
        id: "s3",
        name: "无名",
        artists: [],
        album: null,
        duration_s: 200,
        url: null,
        lyrics: null,
        cover_url: null,
        source: "local",
      },
    ];
    const cards = recommendationsToCards(songs);
    expect(cards[0]!.subtitle).toBe("未知艺术家");
  });
});

/** fake store 契约（与 libraryStore / agentStore 同构）。 */
interface FakeStore<T> {
  getState: () => T;
  subscribe: (listener: () => void) => () => void;
}

function makeFakeStore<T>(initial: T): FakeStore<T> & { emit: () => void } {
  let state = initial;
  const listeners = new Set<() => void>();
  return {
    getState: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    emit: () => {
      for (const l of listeners) l();
    },
  };
}

describe("createPlaylistDataSource 订阅式数据源", () => {
  it("getCards 返回当前 playlist 快照", () => {
    const store = makeFakeStore({ playlists: PLAYLISTS });
    const ds = createPlaylistDataSource(store);
    expect(ds.getCards()).toHaveLength(3);
    expect(ds.getCards()[0]!.title).toBe("夜行");
  });

  it("subscribe 透传到 store（store emit 时数据源监听器被调用）", () => {
    const store = makeFakeStore({ playlists: PLAYLISTS });
    const ds = createPlaylistDataSource(store);
    const listener = vi.fn();
    ds.subscribe(listener);
    store.emit();
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("subscribe 返回的 unsubscribe 解除监听", () => {
    const store = makeFakeStore({ playlists: PLAYLISTS });
    const ds = createPlaylistDataSource(store);
    const listener = vi.fn();
    const unsub = ds.subscribe(listener);
    unsub();
    store.emit();
    expect(listener).not.toHaveBeenCalled();
  });
});

describe("createMessageDataSource 订阅式数据源", () => {
  it("getCards 返回最近 N 条消息", () => {
    const store = makeFakeStore({ messages: MESSAGES });
    const ds = createMessageDataSource(store, 2);
    expect(ds.getCards()).toHaveLength(2);
  });
});

describe("createToolCallDataSource 订阅式数据源", () => {
  it("getCards 返回当前 toolCalls", () => {
    const store = makeFakeStore({ currentToolCalls: TOOL_CALLS });
    const ds = createToolCallDataSource(store);
    expect(ds.getCards()).toHaveLength(2);
    expect(ds.getCards()[0]!.kind).toBe("tool_result");
  });
});

describe("composeDataSources 合并多数据源", () => {
  it("getCards 合并多个数据源的卡片（按顺序拼接）", () => {
    const ds1: CardDataSource = {
      getCards: () => playlistToCards(PLAYLISTS),
      subscribe: () => () => {},
    };
    const ds2: CardDataSource = {
      getCards: () => messagesToCards(MESSAGES, 2),
      subscribe: () => () => {},
    };
    const composed = composeDataSources([ds1, ds2]);
    expect(composed.getCards()).toHaveLength(5);
    expect(composed.getCards()[0]!.kind).toBe("playlist");
    expect(composed.getCards()[3]!.kind).toBe("message");
  });

  it("subscribe 透传到所有子数据源", () => {
    const listener1 = vi.fn();
    const listener2 = vi.fn();
    const ds1: CardDataSource = { getCards: () => [], subscribe: (l) => { listener1.mockImplementation(l); return () => {}; } };
    const ds2: CardDataSource = { getCards: () => [], subscribe: (l) => { listener2.mockImplementation(l); return () => {}; } };
    const composed = composeDataSources([ds1, ds2]);
    const listener = vi.fn();
    composed.subscribe(listener);
    listener1();
    expect(listener).toHaveBeenCalledTimes(1);
    listener2();
    expect(listener).toHaveBeenCalledTimes(2);
  });
});
