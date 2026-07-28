/**
 * HUD 全局状态（M7.2 收窄，M7.4 扩展 sleeping，M20.6 扩展 fieldMode，M21.4 扩展 cinemaMode，M22.2 扩展 wallpaperMode）：
 * 穿透状态机退役后的全局开关。
 *
 * M7.1 起点击穿透由 Rust 分区轮询拥有（set_interactive_zones + zones.rs），
 * 前端 hover 切换窗口级穿透的 mode 状态机随之退役；store 收窄为：
 * - prefers-reduced-motion 全局动效开关；
 * - sleeping 睡眠态标记（M7.4：睡眠 = 场近零 + zones 只留声井）；
 * - fieldMode 场景模式（M20.6：space=显影场 / shelf=3D 卡片架）；
 * - cinemaMode 电影镜头模式（M21.4：off/calm/standard/intense，D21.2 预设模式）；
 * - wallpaperMode 桌面壁纸模式（M22.2：true = 沉到桌面图标层下方）。
 *
 * sleeping 跨多个组件：WellZone 切换按钮、CaptionLayer 退出显影、
 * FieldStage 场近零（M7.3 后续接入）、zoneRegistry 各组件按 sleeping
 * 决定是否注册自身分区。store 只持有标记，下游各自响应。
 *
 * fieldMode 跨 ShelfView / FieldStage / ImmersiveSpace：
 * - shelf 模式下 ShelfView 挂载 ShelfStage、FieldStage 场景淡化（setMood 低流速）；
 * - space 模式下 ShelfView 卸载、FieldStage 恢复默认氛围。
 *
 * cinemaMode 跨 ImmersiveSpace / FieldStage：
 * - off：不干预基础视差 rig（默认）；
 * - calm/standard/intense：叠加 dolly/环绕/摇晃（由 createSpace cinemaRig 消费）。
 *
 * wallpaperMode 跨 App.tsx / FieldStage / zoneRegistry：
 * - true + idle → 窗口沉到 desktopIconWindowLevel（M22.1 D22.1），
 *   FieldStage 降密降亮（M22.4），zones 保留交互区（M22.3）；
 * - true + 活跃态 → 自动浮出回 screenSaver level（M22.5），活跃态结束后渐回壁纸态；
 * - false → 完全不干预窗口层级（沿用 M12 mini/full 语音推导）。
 *
 * 框架无关订阅模式，React 侧经 useSyncExternalStore 绑定。
 */

/** 场景模式：space=显影场（默认）/ shelf=3D 卡片架。 */
export type FieldMode = "space" | "shelf";

/** 电影镜头模式（D21.2 预设模式）：off=不启用（默认）。 */
export type CinemaMode = "off" | "calm" | "standard" | "intense";

export interface HudState {
  readonly reducedMotion: boolean;
  /** 睡眠态：场近零 + zones 只留声井点击区。 */
  readonly sleeping: boolean;
  /** 场景模式（M20.6）：space=显影场 / shelf=3D 卡片架。 */
  readonly fieldMode: FieldMode;
  /** 电影镜头模式（M21.4）：off/calm/standard/intense。 */
  readonly cinemaMode: CinemaMode;
  /** 桌面壁纸模式（M22.2）：true = 沉到桌面图标层下方，活跃态自动浮出。 */
  readonly wallpaperMode: boolean;
  /**
   * M22.5 壁纸模式唤醒浮出标记：true = 浮出到 screenSaver level + 全亮 bloom；
   * false = 沉到 desktopIcon level + 半亮 bloom。
   * 双击唤醒区触发 wakeWallpaper() 置 true，2s 无交互后由 App.tsx 计时器
   * 调 sleepWallpaper() 置 false（渐回壁纸态）。退出壁纸模式时同步清零。
   */
  readonly wallpaperAwake: boolean;
  /**
   * M22.5 唤醒序号：每次 wakeWallpaper() 自增（即使 awake 已为 true）。
   * App.tsx 的 2s 渐回计时器 effect 依赖本字段——重复双击唤醒时序号变化
   * 触发 effect 重跑，旧计时器清除、新计时器起算（重置 2s 倒计时）。
   * 故 wakeWallpaper() 不做幂等短路（与其他 setter 不同）。
   */
  readonly wallpaperAwakeSeq: number;
}

export interface HudStore {
  getState: () => HudState;
  subscribe: (listener: () => void) => () => void;
  setReducedMotion: (flag: boolean) => void;
  setSleeping: (flag: boolean) => void;
  /** 翻转睡眠态，返回切换后的状态。 */
  toggleSleeping: () => boolean;
  /** 设置场景模式（M20.6），幂等同值不重复通知。 */
  setFieldMode: (mode: FieldMode) => void;
  /** 在 space/shelf 间翻转场景模式，返回切换后的模式。 */
  toggleFieldMode: () => FieldMode;
  /** 设置电影镜头模式（M21.4），幂等同值不重复通知。 */
  setCinemaMode: (mode: CinemaMode) => void;
  /** 设置壁纸模式（M22.2），幂等同值不重复通知。false 时同步清 wallpaperAwake。 */
  setWallpaperMode: (flag: boolean) => void;
  /** 在正常/壁纸间翻转壁纸模式，返回切换后的状态。 */
  toggleWallpaperMode: () => boolean;
  /** M22.5 触发唤醒浮出（wallpaperAwake=true）。不做幂等短路：每次调用自增
   *  wallpaperAwakeSeq 并通知，以支持重复双击重置 2s 渐回计时器。 */
  wakeWallpaper: () => void;
  /** M22.5 结束唤醒浮出（wallpaperAwake=false），幂等同值不重复通知。 */
  sleepWallpaper: () => void;
}

export function createHudStore(): HudStore {
  let state: HudState = {
    reducedMotion: false,
    sleeping: false,
    fieldMode: "space",
    cinemaMode: "off",
    wallpaperMode: false,
    wallpaperAwake: false,
    wallpaperAwakeSeq: 0,
  };
  const listeners = new Set<() => void>();

  const emit = (): void => {
    for (const listener of listeners) listener();
  };

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    setReducedMotion(flag) {
      if (state.reducedMotion === flag) return; // 幂等：同值不重复通知
      state = { ...state, reducedMotion: flag };
      emit();
    },
    setSleeping(flag) {
      if (state.sleeping === flag) return; // 幂等
      state = { ...state, sleeping: flag };
      emit();
    },
    toggleSleeping() {
      const next = !state.sleeping;
      state = { ...state, sleeping: next };
      emit();
      return next;
    },
    setFieldMode(mode) {
      if (state.fieldMode === mode) return; // 幂等
      state = { ...state, fieldMode: mode };
      emit();
    },
    toggleFieldMode() {
      const next: FieldMode = state.fieldMode === "space" ? "shelf" : "space";
      state = { ...state, fieldMode: next };
      emit();
      return next;
    },
    setCinemaMode(mode) {
      if (state.cinemaMode === mode) return; // 幂等
      state = { ...state, cinemaMode: mode };
      emit();
    },
    setWallpaperMode(flag) {
      if (state.wallpaperMode === flag) return; // 幂等
      // M22.5：退出壁纸模式时同步清 wallpaperAwake + 重置 seq，
      // 避免下次进入壁纸模式时残留 awake 态（窗口直接浮出不沉）；
      // seq 重置确保下次唤醒序号从 1 起算，不跨会话累加。
      state = flag
        ? { ...state, wallpaperMode: true }
        : { ...state, wallpaperMode: false, wallpaperAwake: false, wallpaperAwakeSeq: 0 };
      emit();
    },
    toggleWallpaperMode() {
      const next = !state.wallpaperMode;
      state = next
        ? { ...state, wallpaperMode: true }
        : { ...state, wallpaperMode: false, wallpaperAwake: false, wallpaperAwakeSeq: 0 };
      emit();
      return next;
    },
    wakeWallpaper() {
      // 不做幂等短路：每次调用自增 seq + 置 awake=true + 通知。
      // seq 变化驱动 App.tsx 的 2s 渐回计时器 effect 重跑（重复双击重置倒计时）。
      state = {
        ...state,
        wallpaperAwake: true,
        wallpaperAwakeSeq: state.wallpaperAwakeSeq + 1,
      };
      emit();
    },
    sleepWallpaper() {
      if (!state.wallpaperAwake) return; // 幂等
      state = { ...state, wallpaperAwake: false };
      emit();
    },
  };
}
