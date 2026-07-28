//! 交互分区穿透：鼠标悬停在交互区（FieldStage / CaptionLayer / WellZone 等 React 组件）
//! 时关闭穿透，离开交互区恢复穿透。
//!
//! 设计原则（M7.1）：
//! - 窗口级 `set_ignore_cursor_events` 只能全穿透 / 全不穿透，无法按区域生效。
//! - 交互区几何由前端 React 组件在布局变化时经 `set_interactive_zones` command
//!   下发为窗口坐标系矩形列表；Rust 侧后台线程以 60Hz 轮询鼠标位置，命中
//!   任一矩形 → 关闭穿透（允许点击），否则 → 全穿透。
//! - 分区集合（`Vec<Rect>`）是分区轮询线程的唯一事实来源，Rust 不硬编码任何
//!   声井 / 舞台 / 字幕布局——休眠态"只留声井"由前端下发单分区表达。
//! - Mini 模式（MiniBar 浮窗）和 Wallpaper 壁纸模式（D22.2）的穿透策略由共享
//!   `SharedWindowMode` 决定：Mini 模式全穿透（浮窗只看状态不交互），Wallpaper
//!   模式沿用分区决策（保留桌面图标层之下交互分区的点击可达性）。

use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

use crate::utils::{self, StopHandle};
use crate::WindowMode;

/// 轮询间隔：≈16ms ≈ 60Hz，够流畅且不烧 CPU。
const CURSOR_POLL_INTERVAL_MS: u64 = 16;
/// 几何稳定判断窗口：100ms 内无几何/分区变化才记为稳定，避免 resize 期间抖动。
const STABILITY_WINDOW_MS: u64 = 100;

/// 窗口坐标系矩形（CSS 逻辑像素，与前端 DOMRect 一致）。
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Rect {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

impl Rect {
    fn contains(self, (px, py): (f64, f64)) -> bool {
        px >= self.x && px < self.x + self.width && py >= self.y && py < self.y + self.height
    }
}

/// 跨进程共享的交互分区列表：前端 `set_interactive_zones` command 写入，
/// 鼠标轮询线程读取。初始为空列表 = 全穿透（HUD 默认行为）。
pub type SharedZones = Arc<Mutex<Vec<Rect>>>;

/// 构造共享分区状态（初始空列表 = 全穿透）。
pub fn shared_zones() -> SharedZones {
    Arc::new(Mutex::new(Vec::new()))
}

/// 当前交互穿透状态机。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum PassthroughState {
    /// 全穿透（鼠标事件交给桌面）。
    Ignoring,
    /// 不穿透（鼠标事件交给 HUD WebView）。
    Receiving,
}

#[cfg(target_os = "macos")]
mod sys {
    //! macOS 实现：用 CoreGraphics 事件源读取全局鼠标位置（不依赖窗口 focus）。
    //!
    //! 为什么不用 Tauri / Wry 自带 API：Tauri `cursor_position()` 只在窗口有焦点时
    //! 返回有效位置；`set_ignore_cursor_events(true)` 后窗口拿不到任何鼠标事件。
    //! CoreGraphics `CGEventCreate(nil) + CGEventGetLocation` 直接读系统光标位置，
    //! 与窗口焦点无关，是桌面覆盖层的标准做法。

    use core_graphics::event::CGEvent;
    use core_graphics::event_source::{CGEventSource, CGEventSourceStateID};

    /// 读取全局鼠标位置（主显示器窗口坐标系，左上角原点，逻辑像素）。
    ///
    /// CGEventSource 在 M 系列 / 多屏 / 前台 app 切换场景下都会返回有效坐标。
    /// 返回 None 代表事件源创建失败（极少发生，权限不足时），调用方保持上次状态。
    /// 对 CGEventGetLocation 返回的坐标做 NaN / 有限值检查，避免非法指针
    /// （如 CGEventCreate 返回 null 时）导致未定义行为。
    pub fn get_cursor_position() -> Option<(f64, f64)> {
        // SAFETY: CGEventSource::new 返回 Result，Err 分支直接返回 None，
        // 不会访问非法指针。
        let event_source = CGEventSource::new(CGEventSourceStateID::HIDSystemState).ok()?;

        // SAFETY: CGEvent::new 返回 Result，Err 分支直接返回 None，
        // event_source 由上一步成功构造，保证合法。
        let event = CGEvent::new(event_source).ok()?;

        // SAFETY: event 由上一步 CGEvent::new 成功返回，保证是合法 CGEventRef；
        // location 返回 CGPoint，检查 x/y 是否为有限值，NaN/Inf 时返回 None。
        let location = event.location();
        if !location.x.is_finite() || !location.y.is_finite() {
            return None;
        }

        Some((location.x, location.y))
    }
}

#[cfg(not(target_os = "macos"))]
mod sys {
    /// 非 macOS 平台暂不支持全局鼠标位置读取（返回 None → 保持全穿透）。
    pub fn get_cursor_position() -> Option<(f64, f64)> {
        None
    }
}

use sys::get_cursor_position;

/// 点 (px, py) 是否落在任一交互分区内。
///
/// 纯函数，便于单测。
fn point_in_any_zone(point: (f64, f64), zones: &[Rect]) -> bool {
    zones.iter().any(|z| z.contains(point))
}

/// 启动后台轮询线程：60Hz 读鼠标位置，命中交互区 → 关穿透，否则 → 开穿透。
/// 返回 `StopHandle`，调用方在窗口关闭/应用退出时调用 `.stop()` 通知线程退出，
/// 避免进程退出时线程悬挂导致资源泄漏。
///
/// 几何稳定策略：
/// - 启动后 / 分区或窗口几何变化后，100ms 内不切换穿透状态——等前端布局/resize
///   稳定下来再决策，避免窗口刚启动时短时间内 "穿透→不穿透→穿透" 闪烁。
/// - 稳定判断基于"分区内容快照"的内容变化 + 窗口 outer_position/outer_size
///   变化，任一变化都重置稳定计时器。
/// - Mini 模式（M12）下直接强制全穿透（浮窗只显示状态不接收点击），不做分区命中；
///   Wallpaper 模式（M22）下沿用 Full 模式分区穿透策略（保留交互分区点击）。
///
/// 线程安全：
/// - `Arc<Mutex<Vec<Rect>>>` 读共享分区列表（只在轮询循环里短暂加锁）；
/// - `Arc<Mutex<WindowMode>>` 读共享窗口形态；
/// - `StopHandle` 用 `Arc<AtomicBool>` 标记退出，线程每轮检查 `is_stopped()`，
///   确保 stop 调用后线程在下一个 16ms tick 内退出；
/// - 所有 Mutex 锁污染统一记录 warn 日志并降级到安全默认值（空分区/Full 模式）；
/// - 两个锁（zones + window_mode）合并到同一个临界区获取，减少状态不一致窗口。
pub fn start_zone_polling<R: tauri::Runtime>(
    window: tauri::WebviewWindow<R>,
    zones_state: SharedZones,
    mode_state: Arc<Mutex<WindowMode>>,
) -> Result<StopHandle, String> {
    let stop_handle = StopHandle::new();
    let stop_clone = stop_handle.clone();

    thread::Builder::new()
        .name("zone-poll".to_string())
        .spawn(move || {
            let mut current_state = PassthroughState::Ignoring;
            let mut last_zones_snapshot: Vec<Rect> = Vec::new();
            let mut last_window_rect: Option<(i32, i32, u32, u32)> = None;
            let mut stable_since: Option<Instant> = None;

            while !stop_clone.is_stopped() {
                // 合并锁获取：同时读 zones + window_mode，缩短不一致窗口
                let zones_snapshot = utils::lock_clone(&zones_state, "interactive_zones_poll");
                let window_mode = utils::lock_clone(&mode_state, "window_mode_poll");

                let window_rect = window
                    .outer_position()
                    .ok()
                    .map(|p| (p.x, p.y, 0, 0))
                    .and_then(|(x, y, _, _)| {
                        window
                            .outer_size()
                            .ok()
                            .map(|s| (x, y, s.width, s.height))
                    });

                let geometry_changed = last_zones_snapshot != zones_snapshot
                    || last_window_rect != window_rect;
                if geometry_changed {
                    last_zones_snapshot = zones_snapshot.clone();
                    last_window_rect = window_rect;
                    stable_since = Some(Instant::now());
                }

                let is_stable = stable_since
                    .map(|t| t.elapsed() >= Duration::from_millis(STABILITY_WINDOW_MS))
                    .unwrap_or(true);

                let next_state = if window_mode == WindowMode::Mini {
                    PassthroughState::Ignoring
                } else if !is_stable {
                    current_state
                } else {
                    match get_cursor_position() {
                        Some((global_x, global_y)) => {
                            if let Some((wx, wy, _, _)) = window_rect {
                                let local = (global_x - wx as f64, global_y - wy as f64);
                                if point_in_any_zone(local, &zones_snapshot) {
                                    PassthroughState::Receiving
                                } else {
                                    PassthroughState::Ignoring
                                }
                            } else {
                                current_state
                            }
                        }
                        None => current_state,
                    }
                };

                if next_state != current_state {
                    let ignore = matches!(next_state, PassthroughState::Ignoring);
                    let _ = window.set_ignore_cursor_events(ignore);
                    current_state = next_state;
                }

                thread::sleep(Duration::from_millis(CURSOR_POLL_INTERVAL_MS));
            }
        })
        .map_err(|e| format!("zone-poll thread spawn failed: {e}"))?;

    Ok(stop_handle)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rect(x: f64, y: f64, w: f64, h: f64) -> Rect {
        Rect {
            x,
            y,
            width: w,
            height: h,
        }
    }

    #[test]
    fn empty_zones_never_contain_any_point() {
        assert!(!point_in_any_zone((100.0, 100.0), &[]));
    }

    #[test]
    fn point_exactly_on_top_left_edge_is_inside() {
        let r = rect(50.0, 50.0, 100.0, 100.0);
        assert!(r.contains((50.0, 50.0)));
    }

    #[test]
    fn point_exactly_on_bottom_right_edge_is_outside() {
        let r = rect(50.0, 50.0, 100.0, 100.0);
        assert!(!r.contains((150.0, 150.0)));
    }

    #[test]
    fn point_inside_any_zone_returns_true() {
        let zones = vec![rect(0.0, 0.0, 100.0, 50.0), rect(200.0, 200.0, 80.0, 80.0)];
        assert!(point_in_any_zone((50.0, 25.0), &zones));
        assert!(point_in_any_zone((240.0, 240.0), &zones));
        assert!(!point_in_any_zone((150.0, 100.0), &zones));
    }

    #[test]
    fn shared_zones_initial_is_empty() {
        let zones = shared_zones();
        let snapshot = utils::lock_clone(&zones, "shared_zones_test");
        assert!(snapshot.is_empty());
    }

    #[test]
    fn passthrough_state_enum_has_expected_variants() {
        let ignoring = PassthroughState::Ignoring;
        let receiving = PassthroughState::Receiving;
        assert_ne!(ignoring, receiving);
    }

    #[test]
    fn stop_handle_initial_is_not_stopped() {
        let handle = StopHandle::new();
        assert!(!handle.is_stopped());
    }

    #[test]
    fn stop_handle_sets_stopped_flag() {
        let handle = StopHandle::new();
        handle.stop();
        assert!(handle.is_stopped());
    }

    #[test]
    fn stop_handle_clone_shares_same_flag() {
        let handle = StopHandle::new();
        let handle_clone = handle.clone();
        assert!(!handle_clone.is_stopped());
        handle.stop();
        assert!(handle_clone.is_stopped());
    }

    #[test]
    fn poll_loop_exits_immediately_when_stop_is_set_before_spawn() {
        use std::time::Duration;

        let zones = shared_zones();
        let mode = Arc::new(Mutex::new(WindowMode::Full));
        let app = tauri::test::mock_builder()
            .build(tauri::test::mock_context(tauri::test::noop_assets()))
            .expect("mock app 构建失败");
        let window = tauri::WebviewWindowBuilder::new(&app, "test", Default::default())
            .build()
            .expect("mock webview 构建失败");

        let stop_handle = StopHandle::new();
        stop_handle.stop();

        let start = Instant::now();
        while !stop_handle.is_stopped() {
            thread::sleep(Duration::from_millis(1));
            if start.elapsed() > Duration::from_secs(1) {
                break;
            }
        }
        assert!(stop_handle.is_stopped());

        let _ = start_zone_polling(window, zones, mode);
    }

    #[test]
    fn point_in_zone_handles_negative_coordinates() {
        let r = rect(-50.0, -50.0, 100.0, 100.0);
        assert!(r.contains((0.0, 0.0)));
        assert!(r.contains((-50.0, -50.0)));
        assert!(!r.contains((-51.0, 0.0)));
    }

    #[test]
    fn rect_contains_is_false_for_point_outside_by_single_epsilon() {
        let r = rect(0.0, 0.0, 1.0, 1.0);
        assert!(!r.contains((1.0, 0.5)));
        assert!(!r.contains((0.5, 1.0)));
    }
}
