/**
 * shared.ts 共享辅助测试（M17.10）。
 *
 * 覆盖：循环模式图标映射 / 切换顺序 / 时间格式化 / 艺术家拼接 / 播放状态判断。
 */
import { describe, expect, it } from "vitest";

import type { RepeatMode } from "../../store/musicStore";
import {
  REPEAT_MODE_CYCLE,
  REPEAT_MODE_ICON,
  REPEAT_MODE_LABEL,
  formatArtists,
  formatTime,
  getSongUrl,
  isPlaying,
  nextRepeatMode,
} from "./shared";

describe("REPEAT_MODE_ICON / LABEL 映射", () => {
  it("4 种模式全部映射到已登记 Icon 名", () => {
    expect(REPEAT_MODE_ICON.sequence).toBe("listMusic");
    expect(REPEAT_MODE_ICON.list_loop).toBe("repeat");
    expect(REPEAT_MODE_ICON.single).toBe("repeat1");
    expect(REPEAT_MODE_ICON.random).toBe("shuffle");
  });

  it("4 种模式全部有中文标签", () => {
    expect(REPEAT_MODE_LABEL.sequence).toBe("顺序播放");
    expect(REPEAT_MODE_LABEL.list_loop).toBe("列表循环");
    expect(REPEAT_MODE_LABEL.single).toBe("单曲循环");
    expect(REPEAT_MODE_LABEL.random).toBe("随机播放");
  });

  it("REPEAT_MODE_CYCLE 含 4 种模式且无重复", () => {
    expect(REPEAT_MODE_CYCLE).toHaveLength(4);
    expect(new Set(REPEAT_MODE_CYCLE).size).toBe(4);
  });
});

describe("nextRepeatMode 循环切换", () => {
  it("sequence → list_loop", () => {
    expect(nextRepeatMode("sequence")).toBe("list_loop");
  });

  it("list_loop → single", () => {
    expect(nextRepeatMode("list_loop")).toBe("single");
  });

  it("single → random", () => {
    expect(nextRepeatMode("single")).toBe("random");
  });

  it("random → sequence（回绕）", () => {
    expect(nextRepeatMode("random")).toBe("sequence");
  });

  it("连续切换 4 次回到原点", () => {
    let mode: RepeatMode = "sequence";
    for (let i = 0; i < 4; i++) {
      mode = nextRepeatMode(mode);
    }
    expect(mode).toBe("sequence");
  });
});

describe("isPlaying", () => {
  it("playing → true", () => {
    expect(isPlaying("playing")).toBe(true);
  });

  it("paused / stopped → false", () => {
    expect(isPlaying("paused")).toBe(false);
    expect(isPlaying("stopped")).toBe(false);
  });

  it("null / undefined → false", () => {
    expect(isPlaying(null)).toBe(false);
    expect(isPlaying(undefined)).toBe(false);
  });
});

describe("formatTime", () => {
  it("0 → 0:00", () => {
    expect(formatTime(0)).toBe("0:00");
  });

  it("75 → 1:15", () => {
    expect(formatTime(75)).toBe("1:15");
  });

  it("小于 10 秒补零", () => {
    expect(formatTime(5)).toBe("0:05");
  });

  it("超过 1 小时 → h:mm:ss", () => {
    expect(formatTime(3661)).toBe("1:01:01");
  });

  it("NaN / 负数 → 0:00", () => {
    expect(formatTime(NaN)).toBe("0:00");
    expect(formatTime(-5)).toBe("0:00");
    expect(formatTime(Infinity)).toBe("0:00");
  });
});

describe("formatArtists", () => {
  it("多艺术家用 / 拼接", () => {
    expect(formatArtists(["周杰伦", "费玉清"])).toBe("周杰伦 / 费玉清");
  });

  it("单艺术家", () => {
    expect(formatArtists(["陈奕迅"])).toBe("陈奕迅");
  });

  it("空列表 → 未知艺术家", () => {
    expect(formatArtists([])).toBe("未知艺术家");
  });
});

describe("getSongUrl", () => {
  it("song 有 url → 返回 url", () => {
    const song = {
      id: "1",
      name: "n",
      source: "netease" as const,
      artists: [],
      album: null,
      duration_s: 0,
      url: "http://example.com/a.mp3",
      lyrics: null,
      cover_url: null,
    };
    expect(getSongUrl(song)).toBe("http://example.com/a.mp3");
  });

  it("song.url 为 null → 返回 null", () => {
    const song = {
      id: "1",
      name: "n",
      source: "netease" as const,
      artists: [],
      album: null,
      duration_s: 0,
      url: null,
      lyrics: null,
      cover_url: null,
    };
    expect(getSongUrl(song)).toBeNull();
  });

  it("song 为 null → 返回 null", () => {
    expect(getSongUrl(null)).toBeNull();
  });
});
