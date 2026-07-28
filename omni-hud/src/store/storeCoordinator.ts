/**
 * store 协调器：跨模块事件联动。
 *
 * 订阅各 store 的状态变化，在满足条件时触发跨模块联动：
 * - weatherStore mood 变化 → 可联动 themeStore（自动主题模式）
 * - musicStore 播放状态 → lyricsStore 启停同步（已有 bindLyricsSync 处理，此处预留）
 *
 * 保持轻量：仅做事件转发，不包含复杂业务逻辑。
 */
import type { LyricsStore } from "./lyricsStore";
import type { MusicStore } from "./musicStore";
import type { ThemeStore } from "../theme/themeStore";
import type { WeatherStore } from "./weatherStore";

export interface CoordinatorDeps {
  readonly weatherStore: WeatherStore;
  readonly themeStore: ThemeStore;
  readonly musicStore: MusicStore;
  readonly lyricsStore: LyricsStore;
  /** 是否启用天气→主题自动联动（默认 false，预留配置）。 */
  readonly autoThemeLink?: boolean;
}

export interface Coordinator {
  start: () => void;
  stop: () => void;
}

/** 天气情绪 → 主题 ID 映射（预留，autoThemeLink=true 时启用）。 */
const WEATHER_THEME_MAP: Readonly<Record<string, string>> = {
  sunny: "developer-amber",
  calm: "silver-gray",
  melancholy: "safelight-red",
  dreamy: "silver-gray",
  mysterious: "safelight-red",
  dramatic: "safelight-red",
};

export function createStoreCoordinator(deps: CoordinatorDeps): Coordinator {
  const unsubs: Array<() => void> = [];
  let running = false;

  const start = (): void => {
    if (running) return;
    running = true;

    if (deps.autoThemeLink) {
      let lastMood: string | null = null;
      const unsubWeather = deps.weatherStore.subscribe(() => {
        const mood = deps.weatherStore.getState().mood;
        if (!mood) return;
        if (mood.mood === lastMood) return;
        lastMood = mood.mood;
        const themeId = WEATHER_THEME_MAP[mood.mood];
        if (themeId) {
          try {
            deps.themeStore.setTheme(themeId);
          } catch {
            // 主题不存在时静默忽略
          }
        }
      });
      unsubs.push(unsubWeather);
    }
  };

  const stop = (): void => {
    if (!running) return;
    running = false;
    for (const unsub of unsubs) unsub();
    unsubs.length = 0;
  };

  return { start, stop };
}

/** 全局单例协调器（由 App 启动时调用 startCoordination 初始化）。 */
let globalCoordinator: Coordinator | null = null;

export function startCoordination(deps: CoordinatorDeps): void {
  globalCoordinator?.stop();
  globalCoordinator = createStoreCoordinator(deps);
  globalCoordinator.start();
}

export function stopCoordination(): void {
  globalCoordinator?.stop();
  globalCoordinator = null;
}
