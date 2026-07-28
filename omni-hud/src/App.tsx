/**
 * HUD 根组件（M7.2 显影场骨架）：3D 沉浸空间 + 三槽位空壳。
 *
 * 角色系统（Live2D / OpenTalking / StatusBar / ThemeSwitcher / 后端切换）已退役——
 * 「无角色环境在场」：UI 退到桌面之后，场本身即存在。骨架槽位：
 *   FieldStage   四态场语义层（M7.3 填充）
 *   CaptionLayer mono 状态标 + 显影字幕（M7.4 填充）
 *   WellZone     声井 + 召唤控制环（M7.4 填充）
 *
 * M7.1 起点击穿透由 Rust 分区轮询拥有（set_interactive_zones），前端不再有
 * hover 切换窗口级穿透的 mode 状态机；hudStore 收窄为 reduced-motion 全局开关。
 *
 * 保留接线：状态轮询（statusStore）+ visibility 联动、主题换肤（themeStore）、
 * M5.3 点击交互（clickGather：shader 水波纹 + 吸引子脉冲 + 形状聚集缓释）、
 * 语音氛围（bindSpaceMood：voice.state → 场景流速 / bloom）、
 * engineRef 2D 降级引擎聚集（WebGL 失败回退路径保持可用）。
 */
import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";

import { AgentPanel } from "./components/agent/AgentPanel";
import { CaptionLayer } from "./components/CaptionLayer";
import { FieldStage } from "./components/FieldStage";
import { ImmersiveSpace } from "./components/ImmersiveSpace";
import { LyricsDisplay } from "./components/lyrics";
import { LibraryView, NowPlaying, PlayControlBar, QueueList } from "./components/music";
import { MiniBar } from "./components/MiniBar";
import { ShelfView } from "./components/ShelfView";
import { WallpaperZones } from "./components/WallpaperZones";
import { WellZone } from "./components/WellZone";
import type { ParticleEngine } from "./particles/engine";
import type { Space } from "./space/createSpace";
import { createClickGather, ndcFromClientPoint } from "./space/interactions";
import { bindSpaceMood } from "./space/mood";
import { bindAgentSync, getAgentStore } from "./store/agentRuntime";
import { getIdentityStore } from "./store/identityRuntime";
import { createHudStore, type HudStore } from "./store/hudStore";
import { getLibraryStore } from "./store/libraryRuntime";
import { getMusicStore } from "./store/musicRuntime";
import { bindLyricsSync, getLyricsStore } from "./store/lyricsRuntime";
import { getStatusStore } from "./store/statusRuntime";
import { getSubtitleStore } from "./store/subtitleRuntime";
import { useStoreSelector } from "./store/useStoreSelector";
import { bindWeatherToSpace, getWeatherStore } from "./store/weatherRuntime";
import { bindVisibilityPause } from "./store/visibility";
import { getThemeStore } from "./theme/themeRuntime";
import { resolveFieldState } from "./field/fieldState";
import { invoke } from "@tauri-apps/api/core";
import type { VoicePipelineState, WindowMode } from "./data/sources";

let singleton: HudStore | null = null;

function getHudStore(): HudStore {
  singleton ??= createHudStore();
  return singleton;
}

function isTauriEnv(): boolean {
  return typeof window !== "undefined" && 
    (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ !== undefined;
}

if (typeof document !== "undefined") {
  if (isTauriEnv()) {
    document.documentElement.classList.add("tauri-env");
    document.body.classList.add("tauri-env");
  }
}

/** 悬停命中的可交互元素选择器：粒子向这些元素聚集（2D 降级路径）。 */
const ATTRACT_SELECTOR = "button, a, [data-attract]";

export function App() {
  const store = useMemo(getHudStore, []);
  const statusStore = useMemo(getStatusStore, []);
  const themeStore = useMemo(getThemeStore, []);
  const subtitleStore = useMemo(getSubtitleStore, []);
  const agentStore = useMemo(getAgentStore, []);
  const musicStore = useMemo(getMusicStore, []);
  const libraryStore = useMemo(getLibraryStore, []);
  const lyricsStore = useMemo(getLyricsStore, []);
  const weatherStore = useMemo(getWeatherStore, []);
  // 初始化 identityStore（触发 IPC 加载助手身份配置）
  useMemo(getIdentityStore, []);

  const wallpaperMode = useStoreSelector(store, s => s.wallpaperMode);
  const wallpaperAwake = useStoreSelector(store, s => s.wallpaperAwake);
  const wallpaperAwakeSeq = useStoreSelector(store, s => s.wallpaperAwakeSeq);
  const fieldMode = useStoreSelector(store, s => s.fieldMode);
  const reducedMotion = useStoreSelector(store, s => s.reducedMotion);
  const theme = useStoreSelector(themeStore, s => s.theme);
  const voiceState = useStoreSelector(statusStore, s => s.voice.state);
  const voiceWindowModeRaw = useStoreSelector(statusStore, s => s.voice.windowMode);
  const weatherMood = useStoreSelector(weatherStore, s => s.mood);
  const currentSong = useStoreSelector(musicStore, s => s.playerState?.current_song ?? null);
  const positionS = useStoreSelector(musicStore, s => s.playerState?.position_s ?? 0);

  // M20.6 / M19 E2E 调试入口：__omniDebug.libraryViewMounted 控制 LibraryView 挂载
  const [libraryViewMounted, setLibraryViewMounted] = useState(false);
  // M12 灵动岛双形态：voice.windowMode 决定渲染 MiniBar 还是 Full 布局。
  // null / 缺省 → "full"（安全态，保持全屏避免遮挡活跃交互）。
  // M22.2 壁纸模式：wallpaperMode=true 且语音推导为 mini（idle 待命态）时
  // 切到 wallpaper（沉到桌面图标下方）；活跃态（full）时自动浮出回 full，
  // 活跃态结束后 voice 回 mini → 再次自动切回 wallpaper。
  // M22.5 唤醒浮出：wallpaperAwake=true 时把 wallpaper 覆盖为 full（浮到
  // screenSaver level），2s 无交互后由下方 useEffect 调 sleepWallpaper 渐回。
  const voiceWindowMode: WindowMode = voiceWindowModeRaw ?? "full";
  const windowMode: WindowMode =
    wallpaperMode && voiceWindowMode === "mini"
      ? wallpaperAwake
        ? "full"
        : "wallpaper"
      : voiceWindowMode;
  const engineRef = useRef<ParticleEngine | null>(null);
  // M5.3：3D 场景句柄（ImmersiveSpace 懒加载完成后透出，卸载同步置 null）
  const spaceRef = useRef<Space | null>(null);

  // M12：windowMode 变化时通知 Rust 调整窗口几何（Mini 浮窗 / Full cover-display）。
  // 非 Tauri 环境（vitest / 浏览器）invoke 会 reject，静默吞掉即可。
  useEffect(() => {
    invoke("set_window_mode", { mode: windowMode }).catch(() => {});
  }, [windowMode]);

  // M22.5 唤醒浮出 2s 渐回计时器：wallpaperAwake=true 时启动 2s 计时器，
  // 到期调 sleepWallpaper() 渐回壁纸态（沉到 desktopIcon level）；
  // wallpaperAwake=false 或卸载时清除计时器，避免状态泄漏。
  // 依赖 wallpaperAwakeSeq：store.wakeWallpaper() 每次自增 seq（不做幂等短路），
  // 故重复双击唤醒时 seq 变化触发 effect 重跑——旧计时器先清除再启新，
  // 实现「再次双击重置 2s 倒计时」语义（不提前渐回）。
  useEffect(() => {
    if (!wallpaperAwake) return;
    const timer = window.setTimeout(() => {
      store.sleepWallpaper();
    }, 2000);
    return () => {
      window.clearTimeout(timer);
    };
  }, [wallpaperAwake, wallpaperAwakeSeq, store]);

  // 点击聚集编排：波纹 + 脉冲 + 轮换形状成形/缓释；场景未就绪时静默跳过。
  const clickGather = useMemo(
    () =>
      createClickGather({
        getSpace: () => spaceRef.current,
        setTimer: (callback, ms) => window.setTimeout(callback, ms),
        clearTimer: (handle) => window.clearTimeout(handle as number),
      }),
    [],
  );
  useEffect(() => () => clickGather.cancel(), [clickGather]);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    store.setReducedMotion(media.matches);
    const onChange = (event: MediaQueryListEvent): void => {
      store.setReducedMotion(event.matches);
    };
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [store]);

  useEffect(() => {
    statusStore.start();
    return () => statusStore.stop();
  }, [statusStore]);

  // M22.2 壁纸模式快捷键：Ctrl+Shift+W 切换壁纸模式。
  // 让用户在任意形态（full/mini）下都能快速进入/退出壁纸模式。
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === "w") {
        event.preventDefault();
        store.toggleWallpaperMode();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [store]);

  useEffect(() => {
    if (import.meta.env.DEV) {
      const debugApi = {
        setVoiceState: (state: VoicePipelineState): void => {
          const space = spaceRef.current;
          if (!space) {
            console.warn("[debug] Space not ready yet");
            return;
          }
          const params = resolveFieldState(state, store.getState().reducedMotion);
          space.setField(params);
          if (params.ripple) {
            space.addRipple({
              x: params.ripple.origin.x,
              y: params.ripple.origin.y,
              z: params.ripple.origin.z,
              durationMs: params.ripple.durationMs,
            });
          }
        },
        states: ["idle", "wake_listening", "thinking", "tool_using", "speaking", "follow_up_listening", "recording", "transcribing"] as const,
        idle: () => debugApi.setVoiceState("idle"),
        wake: () => debugApi.setVoiceState("wake_listening"),
        listen: () => debugApi.setVoiceState("recording"),
        think: () => debugApi.setVoiceState("thinking"),
        tool: () => debugApi.setVoiceState("tool_using"),
        speak: () => debugApi.setVoiceState("speaking"),
        follow: () => debugApi.setVoiceState("follow_up_listening"),
        // M17 / M18 E2E 测试入口：暴露 musicStore / lyricsStore 控制能力，
        // 让 spec 可经 page.evaluate 触发 fetchPlayerState / fetchLyrics 等
        // 异步 action，无需依赖未实现的自动轮询。生产构建（非 DEV）不挂载。
        music: {
          fetchPlayerState: () => musicStore.fetchPlayerState(),
          play: (opts?: { songId?: string; index?: number; keyword?: string }) =>
            musicStore.play(opts),
          pause: () => musicStore.pause(),
          resume: () => musicStore.resume(),
          stop: () => musicStore.stop(),
          next: () => musicStore.next(),
          previous: () => musicStore.previous(),
          seek: (positionS: number) => musicStore.seek(positionS),
          setRepeatMode: (mode: "single" | "list_loop" | "random" | "sequence") =>
            musicStore.setRepeatMode(mode),
          getState: () => musicStore.getState(),
        },
        lyrics: {
          fetchLyrics: (songId: string, source?: "local_file" | "embedded" | "online" | "none") =>
            lyricsStore.fetchLyrics(songId, source),
          refreshCurrentLine: (positionS: number) =>
            lyricsStore.refreshCurrentLine(positionS),
          clear: () => lyricsStore.clear(),
          getState: () => lyricsStore.getState(),
        },
        // M13.5 E2E 测试入口：暴露 agentStore 控制能力，让 spec 可经
        // page.evaluate 触发 clearSession（续听超时 / 用户主动清空的模拟）。
        // 生产构建（非 DEV）不挂载。
        agent: {
          clearSession: () => agentStore.clearSession(),
          getState: () => agentStore.getState(),
        },
        // M20.6 E2E 测试入口：暴露 hudStore 场景模式控制能力。
        hud: {
          getFieldMode: () => store.getState().fieldMode,
          setFieldMode: (mode: "space" | "shelf") => store.setFieldMode(mode),
          toggleFieldMode: () => store.toggleFieldMode(),
          getState: () => store.getState(),
        },
        // M23.3 E2E 测试入口：暴露 weatherStore 控制能力。
        weather: {
          refresh: () => weatherStore.refresh(),
          getMood: () => weatherStore.getState().mood,
          getState: () => weatherStore.getState(),
        },
        // M19 E2E 测试入口：暴露 libraryStore 控制能力 + LibraryView 挂载开关。
        library: {
          scanLibrary: (rootDir?: string) => libraryStore.scanLibrary(rootDir),
          searchLibrary: (query: string, limit?: number) =>
            libraryStore.searchLibrary(query, limit),
          fetchStatus: () => libraryStore.fetchStatus(),
          fetchPlaylists: () => libraryStore.fetchPlaylists(),
          fetchPlaylistSongs: (playlistId: number) =>
            libraryStore.fetchPlaylistSongs(playlistId),
          selectPlaylist: (playlistId: number | null) =>
            libraryStore.selectPlaylist(playlistId),
          createPlaylist: (name: string) => libraryStore.createPlaylist(name),
          addToPlaylist: (playlistId: number, songId: string, position?: number) =>
            libraryStore.addToPlaylist(playlistId, songId, position),
          removeFromPlaylist: (playlistId: number, songId: string) =>
            libraryStore.removeFromPlaylist(playlistId, songId),
          setSearchQuery: (query: string) => libraryStore.setSearchQuery(query),
          clearError: () => libraryStore.clearError(),
          getState: () => libraryStore.getState(),
        },
        // M19 E2E 测试入口：挂载 / 卸载 LibraryView 组件（默认不挂载）。
        mountLibraryView: () => setLibraryViewMounted(true),
        unmountLibraryView: () => setLibraryViewMounted(false),
      };
      (window as unknown as { __omniDebug: typeof debugApi }).__omniDebug = debugApi;
      console.log("[omni-hud] Debug API available: window.__omniDebug\n  .idle() .wake() .listen() .think() .tool() .speak() .follow()\n  .music.fetchPlayerState() .music.play() .music.pause() .music.next() .music.previous()\n  .lyrics.fetchLyrics(songId) .lyrics.refreshCurrentLine(pos)\n  .hud.getFieldMode() .hud.setFieldMode(mode) .hud.toggleFieldMode()\n  .weather.refresh() .weather.getMood()\n  .library.scanLibrary() .library.searchLibrary(q) .library.fetchPlaylists() .library.fetchStatus()\n  .library.createPlaylist(name) .library.addToPlaylist(pid, sid) .library.removeFromPlaylist(pid, sid)\n  .mountLibraryView() .unmountLibraryView()");
    }
  }, [store, musicStore, lyricsStore, libraryStore, weatherStore, agentStore]);

  // 页面隐藏时暂停轮询、重新可见恢复。
  useEffect(() => bindVisibilityPause(statusStore), [statusStore]);

  // M13.5 Agent 可视化同步：把 statusStore.voice 的 speaking + 新 replySeq
  // 回复同步到 agentStore.messages，AgentPanel 自动呈现对话流。Full 模式下
  // 挂载，mini 模式不渲染 AgentPanel 但同步仍可保留（开销极小，避免切回 full
  // 时丢消息）。退订在卸载时由 bindAgentSync 返回的清理函数执行。
  useEffect(() => bindAgentSync(statusStore, agentStore), [statusStore, agentStore]);

  // M5.3 语音氛围：voice.state → 场景流速 / bloom（场景未就绪时推送静默丢弃，
  // 基线即默认氛围，无丢失风险）；返回的解绑函数在卸载时退订。
  useEffect(
    () =>
      bindSpaceMood(statusStore, {
        setMood: (spec) => spaceRef.current?.setMood(spec),
      }),
    [statusStore],
  );

  // M18 歌词同步：musicStore.current_song 变化 → lyricsStore.fetchLyrics 切歌；
  // current_song 变 null → lyricsStore.clear()。position_s 由 LyricsDisplay 的
  // positionS prop 内部 useEffect 驱动 refreshCurrentLine（本地二分，不打 IPC）。
  useEffect(
    () => bindLyricsSync(musicStore, lyricsStore),
    [musicStore, lyricsStore],
  );

  // M23.3 天气情绪联动：weatherStore.mood 变化 → space.setWeatherMood 应用视觉联动
  // （AmbientLight 颜色 / 强度 + 粒子色板 / 密度 / uWeatherSpeed / uWeatherBrightness）。
  // 首次绑定即推送当前 mood（若已有缓存），mood 值未变不重复推送（避免场景重建抖动）。
  // spaceRef.current 在 ImmersiveSpace 挂载后才就绪——setWeatherMood 内部对 null space
  // 静默丢弃（?.可选链），场景就绪后下次 mood 变化会正常推送。
  // 挂载时触发一次 refresh 拉取天气情绪（Tauri 环境下经 IPC 调 omni_weather）。
  useEffect(() => {
    const unbind = bindWeatherToSpace(
      { setWeatherMood: (mood) => spaceRef.current?.setWeatherMood(mood) },
      weatherStore,
    );
    void weatherStore.refresh();
    return unbind;
  }, [weatherStore]);

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>): void => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    engineRef.current?.setAttractor({ x, y });
    // M5.3：同一点击同步 3D 空间——shader 水波纹 + 吸引子脉冲 + 形状聚集。
    const ndc = ndcFromClientPoint(event.clientX, event.clientY, window.innerWidth, window.innerHeight);
    clickGather.click(ndc.x, ndc.y);
  };

  const handlePointerUp = (): void => {
    engineRef.current?.setAttractor(null);
  };

  const handlePointerOver = (event: PointerEvent<HTMLDivElement>): void => {
    const engine = engineRef.current;
    if (!engine) return;
    const target = event.target instanceof Element ? event.target.closest(ATTRACT_SELECTOR) : null;
    if (!target) return;
    const hostRect = event.currentTarget.getBoundingClientRect();
    const rect = target.getBoundingClientRect();
    engine.setAttractor({
      x: rect.left - hostRect.left + rect.width / 2,
      y: rect.top - hostRect.top + rect.height / 2,
    });
  };

  const handlePointerOut = (event: PointerEvent<HTMLDivElement>): void => {
    const target = event.target instanceof Element ? event.target.closest(ATTRACT_SELECTOR) : null;
    if (target) engineRef.current?.setAttractor(null);
  };

  // M12 灵动岛双形态：Mini 形态只渲染 MiniBar，不挂载 3D 场景与 Full 槽位——
  // 节省 WebGL 资源、避免 idle 待命态占用桌面视野；活跃态切回 Full 形态时
  // ImmersiveSpace / FieldStage / CaptionLayer / WellZone 重新挂载恢复。
  // M22 壁纸模式：Wallpaper 形态渲染与 Full 相同的布局（3D 场景 + 槽位），
  // 但窗口层级已沉到桌面图标下方（Rust 侧 set_window_level_wallpaper），
  // 且粒子降密降亮（FieldStage 通过 wallpaperMode prop 感知，M22.4）。
  if (windowMode === "mini") {
    return (
      <div className="hud-root hud-root-mini" data-testid="hud-root" data-voice-state={voiceState ?? "idle"}>
        <MiniBar statusStore={statusStore} />
      </div>
    );
  }

  return (
    <div
      className={`hud-root${windowMode === "wallpaper" ? " hud-root-wallpaper" : ""}`}
      data-testid="hud-root"
      data-voice-state={voiceState ?? "idle"}
      data-window-mode={windowMode}
      data-field-mode={fieldMode}
      data-weather-mood={weatherMood?.mood ?? "none"}
    >
      <ImmersiveSpace
        reducedMotion={reducedMotion}
        theme={theme}
        engineRef={engineRef}
        spaceRef={spaceRef}
      />
      <div
        className="hud-content"
        onPointerDown={handlePointerDown}
        onPointerUp={handlePointerUp}
        onPointerOver={handlePointerOver}
        onPointerOut={handlePointerOut}
      >
        <FieldStage
          spaceRef={spaceRef}
          statusStore={statusStore}
          hudStore={store}
        />
        <CaptionLayer
          statusStore={statusStore}
          hudStore={store}
          subtitleStore={subtitleStore}
        />
        <WellZone
          statusStore={statusStore}
          hudStore={store}
          themeStore={themeStore}
          spaceRef={spaceRef}
        />
        {/* M20.6 3D 卡片架：右键唤起，fieldMode=shelf 时挂载 ShelfStage 子场景 */}
        <ShelfView
          spaceRef={spaceRef}
          hudStore={store}
          libraryStore={libraryStore}
        />
      </div>
      {/* M13.5 AgentPanel 主面板：Full 模式下挂载在底部 35vh 半透明暗房面板，
          显示雪莉对话流 + 状态指示器。mini 模式由 App.tsx 条件渲染跳过
          （AgentPanel 内部也有 windowMode 防御性返回 null）。 */}
      <AgentPanel statusStore={statusStore} agentStore={agentStore} />
      {/* M17 音乐控制 UI：Full 模式下挂载播放控制条 + 当前曲目信息卡 + 队列列表。
          组件内部对空状态有占位渲染（data-empty="true"），无 current_song 时
          显示「未在播放」/「队列为空」，不阻塞其他 UI。E2E 经 __omniDebug.music
          触发 fetchPlayerState() 拉取后端状态。 */}
      <PlayControlBar store={musicStore} />
      <NowPlaying store={musicStore} />
      <QueueList store={musicStore} />
      {/* M18 歌词面板：仅 Full 模式且当前有播放曲目时渲染。
          positionS 来自 musicStore.playerState.position_s，LyricsDisplay 内部
          useEffect 驱动 lyricsStore.refreshCurrentLine 本地二分查找当前行。 */}
      {currentSong !== null ? (
        <LyricsDisplay store={lyricsStore} positionS={positionS} />
      ) : null}
      {/* M22.3 壁纸模式交互分区：仅 wallpaperMode=true 时挂载，
          注册右下控制条 / 左右边缘触发条 / 双击唤醒区为交互分区。
          onWake 触发唤醒浮出（wallpaperAwake=true，浮到 screenSaver level +
          全亮 bloom），2s 无交互后渐回壁纸态（由上方 useEffect 计时）。 */}
      <WallpaperZones
        wallpaperMode={wallpaperMode}
        onWake={() => {
          // M22.5：双击唤醒 → 触发唤醒浮出（窗口浮到顶层 + 亮度提升）
          store.wakeWallpaper();
        }}
        onExitWallpaper={() => store.setWallpaperMode(false)}
      />
      {/* M19 E2E 调试挂载点：__omniDebug.mountLibraryView() 触发后渲染 LibraryView，
          生产构建（非 DEV）不挂载。E2E 测试通过此入口验证库浏览 UI。 */}
      {libraryViewMounted ? (
        <LibraryView store={libraryStore} />
      ) : null}
    </div>
  );
}
