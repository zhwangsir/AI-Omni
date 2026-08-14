/**
 * storeCoordinator 测试。
 *
 * 覆盖：协调器启动/停止 / 天气→主题联动（autoThemeLink 模式）。
 */
import { beforeEach, describe, expect, it } from "vitest";

import { createStoreCoordinator } from "./storeCoordinator";
import type { WeatherMood } from "../data/sources";
import type { ThemeStore } from "../theme/themeStore";
import type { LyricsStore } from "./lyricsStore";
import type { MusicStore } from "./musicStore";
import type { WeatherStore } from "./weatherStore";

type Listener = () => void;

function makeFakeWeatherStore(initialMood: WeatherMood | null = null): {
  store: WeatherStore;
  setMood: (mood: WeatherMood | null) => void;
  listeners: Set<Listener>;
} {
  let state = { mood: initialMood, loading: false, error: null };
  const listeners = new Set<Listener>();

  const store: WeatherStore = {
    getState: () => state,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    refresh: async () => {},
  };

  return {
    store,
    listeners,
    setMood: (mood) => {
      state = { ...state, mood };
      listeners.forEach((l) => l());
    },
  };
}

function makeFakeThemeStore(initialThemeId = "developer-amber"): {
  store: ThemeStore;
  setThemeCalls: string[];
} {
  const setThemeCalls: string[] = [];
  const store: ThemeStore = {
    getState: () => ({
      themeId: initialThemeId,
      theme: {
        id: initialThemeId,
        label: "测试",
        tokens: { abyss: "#000", panel: "#111", hairline: "#222", fog: "#fff", dim: "#888", accent: "#fc0" },
        particles: ["#fc0"],
      },
    }),
    subscribe: () => () => {},
    setTheme: (id) => {
      setThemeCalls.push(id);
    },
    cycleTheme: () => {},
  };
  return { store, setThemeCalls };
}

function makeFakeMusicStore(): { store: MusicStore } {
  return {
    store: {
      getState: () => ({
        playerState: null,
        isLoading: false,
        error: null,
        loginQr: null,
        loginStatus: "idle" as const,
        onlineResults: null,
      }),
      subscribe: () => () => {},
      fetchPlayerState: async () => {},
      play: async () => {},
      pause: async () => {},
      resume: async () => {},
      stop: async () => {},
      next: async () => {},
      previous: async () => {},
      seek: async () => {},
      setRepeatMode: async () => {},
      startLogin: async () => {},
      stopLoginPolling: () => {},
      searchOnline: async () => {},
      clearOnlineResults: () => {},
      debugSetPlayerState: () => {},
    },
  };
}

function makeFakeLyricsStore(): { store: LyricsStore } {
  return {
    store: {
      getState: () => ({
        currentLyrics: null,
        currentIndex: -1,
        currentWordIndex: null,
        offsetS: 0,
        isLoading: false,
        error: null,
      }),
      subscribe: () => () => {},
      fetchLyrics: async () => {},
      refreshCurrentLine: () => {},
      setOffset: async () => {},
      searchLyrics: async () => null,
      uploadLyrics: async () => null,
      clear: () => {},
      debugSetLyrics: () => {},
    },
  };
}

describe("storeCoordinator", () => {
  let weather: ReturnType<typeof makeFakeWeatherStore>;
  let theme: ReturnType<typeof makeFakeThemeStore>;
  let music: ReturnType<typeof makeFakeMusicStore>;
  let lyrics: ReturnType<typeof makeFakeLyricsStore>;

  beforeEach(() => {
    weather = makeFakeWeatherStore();
    theme = makeFakeThemeStore();
    music = makeFakeMusicStore();
    lyrics = makeFakeLyricsStore();
  });

  it("start 注册订阅，stop 注销订阅", () => {
    const coord = createStoreCoordinator({
      weatherStore: weather.store,
      themeStore: theme.store,
      musicStore: music.store,
      lyricsStore: lyrics.store,
      autoThemeLink: false,
    });

    expect(weather.listeners.size).toBe(0);
    coord.start();
    expect(weather.listeners.size).toBe(0);

    coord.stop();
  });

  it("autoThemeLink=true 时订阅 weatherStore", () => {
    const coord = createStoreCoordinator({
      weatherStore: weather.store,
      themeStore: theme.store,
      musicStore: music.store,
      lyricsStore: lyrics.store,
      autoThemeLink: true,
    });

    expect(weather.listeners.size).toBe(0);
    coord.start();
    expect(weather.listeners.size).toBe(1);

    coord.stop();
    expect(weather.listeners.size).toBe(0);
  });

  it("天气 mood 变化时联动切换主题", () => {
    const coord = createStoreCoordinator({
      weatherStore: weather.store,
      themeStore: theme.store,
      musicStore: music.store,
      lyricsStore: lyrics.store,
      autoThemeLink: true,
    });

    coord.start();

    const sunnyMood: WeatherMood = {
      mood: "sunny",
      description: "晴天",
      colorPalette: ["#c9a86a"],
      particleParams: { speed: 1.0, density: 1.0, brightness: 1.0 },
      temperature: 25,
      weatherCode: 0,
      cachedAt: "",
    };
    weather.setMood(sunnyMood);
    expect(theme.setThemeCalls).toContain("developer-amber");

    coord.stop();
  });

  it("幂等：多次 start 不重复注册订阅", () => {
    const coord = createStoreCoordinator({
      weatherStore: weather.store,
      themeStore: theme.store,
      musicStore: music.store,
      lyricsStore: lyrics.store,
      autoThemeLink: true,
    });

    coord.start();
    coord.start();
    expect(weather.listeners.size).toBe(1);

    coord.stop();
  });
});
