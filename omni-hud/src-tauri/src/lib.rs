//! omni-hud 桌面 HUD 的 Tauri 壳。
//!
//! 窗口契约（tauri.conf.json 五项）：透明背景、无边框、置顶、跳过任务栏、点击穿透。
//! M7.1 起窗口为 **cover-display**：覆盖主显示器可视区域（position 显示器原点 +
//! size 可视 frame），禁用 macOS fullscreen Space（会盖住桌面）。
//! 点击穿透默认开启（HUD 不拦截桌面点击）；窗口级穿透无法按区域生效，
//! 故交互分区改由 zones 模块鼠标轮询驱动（见 zones.rs）。
//! 运行期决策逻辑抽成纯函数 / 状态机，保证 `cargo test` 无需窗口系统即可单测。

#![cfg_attr(target_os = "macos", allow(unexpected_cfgs))]

#[cfg(all(target_os = "macos", not(test)))]
#[macro_use]
extern crate objc;

#[cfg(all(target_os = "macos", not(test)))]
use objc::msg_send;
use serde::{Deserialize, Serialize};

pub mod desktop;
pub mod lyrics;
pub mod music;
pub mod office;
pub mod status;
pub mod utils;
pub mod voice;
pub mod voice_watch;
pub mod weather;
pub mod zones;

/// HUD 窗口形态（M12 灵动岛双形态 + M22 壁纸模式）。
///
/// - `Full`：cover-display 全屏覆盖（FieldStage 3D 空间 + CaptionLayer + WellZone），
///   默认形态，活跃语音交互期间使用；
/// - `Mini`：240×48 顶部居中浮窗（MiniBar 状态文字），鼠标穿透，
///   `idle` 待命态使用，让出桌面视野；
/// - `Wallpaper`：沉到桌面图标层下方（macOS `CGWindowLevelForKey(.desktopIconWindowLevel)`，
///   D22.1），cover-display 几何不变仅 level 不同；默认全穿透，分区轮询保留
///   交互区（右下角控制条/左边缘歌单架入口/右边缘历史/双击唤醒区）。
///
/// 形态跟随语音状态自动切换：`idle → Mini`，活跃态（wake_listening/recording/
/// transcribing/thinking/speaking/tool_using/follow_up_listening）→ `Full`。
/// 壁纸模式为用户主动选择的常驻形态（不由语音状态推导），由前端 hudStore
/// `wallpaperMode` 持有并经 `set_window_mode` command 通知 Rust 切换层级。
/// Python 侧 `state_file.py` 推导 `window_mode` 字段写入状态文件，Rust
/// `voice_watch` 透传到前端，前端 `App.tsx` 据此渲染对应组件并经
/// `set_window_mode` command 通知 Rust 调整窗口几何与层级。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum WindowMode {
    /// Mini 浮窗：240×48 顶部居中，鼠标穿透，显示状态文字。
    Mini,
    /// Full cover-display：全屏覆盖（默认形态）。
    #[default]
    Full,
    /// Wallpaper 桌面壁纸模式（M22）：沉到桌面图标下方，几何同 Full，
    /// 仅 level 不同（macOS desktopIconWindowLevel）。
    Wallpaper,
}

/// Mini 浮窗几何常量（CSS 逻辑像素）。
pub const MINI_WIDTH: u32 = 240;
pub const MINI_HEIGHT: u32 = 48;
/// Mini 浮窗顶部留白（避开 macOS 菜单栏 24px）。
pub const MINI_TOP_MARGIN_PX: i32 = 8;

/// 计算 Mini 形态目标矩形：水平居中、顶部贴顶（y=8px 下留菜单栏空间）。
///
/// 窄到放不下 240px 的显示器也不向左溢出（x 至少为 monitor_origin.x），
/// 避免浮窗跑到副屏；高度固定 48px。
pub fn mini_geometry(monitor_origin: (i32, i32), monitor_size: (u32, u32)) -> DisplayCover {
    let (mx, my) = monitor_origin;
    let (mw, mh) = monitor_size;
    let centered_x = mx + ((mw as i32 - MINI_WIDTH as i32) / 2).max(0);
    let y = my + MINI_TOP_MARGIN_PX;
    let _ = mh;
    DisplayCover {
        x: centered_x,
        y,
        width: MINI_WIDTH,
        height: MINI_HEIGHT,
    }
}

/// 跨进程共享的窗口形态状态（轮询线程读、`set_window_mode` command 写）。
pub type SharedWindowMode = std::sync::Arc<std::sync::Mutex<WindowMode>>;

/// 构造共享窗口形态状态（初始 = Full，与 setup 的 cover_display 一致）。
pub fn shared_window_mode() -> SharedWindowMode {
    std::sync::Arc::new(std::sync::Mutex::new(WindowMode::default()))
}

/// HUD 窗口运行时状态机：穿透与置顶开关的唯一事实来源。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct HudWindowState {
    /// true = 鼠标事件穿透到桌面（默认行为）。
    pub click_through: bool,
    pub always_on_top: bool,
}

impl HudWindowState {
    /// 初始状态：穿透开、置顶开。
    pub fn new() -> Self {
        Self {
            click_through: true,
            always_on_top: true,
        }
    }

    /// hover 决策：指针进入交互区（`over_interactive = true`）必须关闭穿透，
    /// 离开交互区恢复穿透。返回应用后的穿透标记。
    pub fn apply_hover(&mut self, over_interactive: bool) -> bool {
        self.click_through = !over_interactive;
        self.click_through
    }

    /// 切换置顶，返回切换后的置顶标记。
    pub fn toggle_always_on_top(&mut self) -> bool {
        self.always_on_top = !self.always_on_top;
        self.always_on_top
    }
}

impl Default for HudWindowState {
    fn default() -> Self {
        Self::new()
    }
}

/// cover-display 目标矩形（M7.1）：窗口应覆盖主显示器可视区域。
///
/// 禁用 macOS fullscreen Space——fullscreen 会把窗口推入独立 Space 盖住桌面，
/// 与「透明覆盖层透出桌面」的契约冲突；改为普通窗口铺满可视 frame。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DisplayCover {
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
}

impl DisplayCover {
    /// 覆盖目标：position = 显示器原点，size = 可视 frame。
    pub fn new(origin: (i32, i32), size: (u32, u32)) -> Self {
        Self {
            x: origin.0,
            y: origin.1,
            width: size.0,
            height: size.1,
        }
    }

    /// 当前窗口几何（outer_position / outer_size）是否已覆盖目标。
    ///
    /// resize/scale 事件与 set_size/set_position 互为因果——已覆盖时跳过，
    /// 幂等防事件回环。
    pub fn is_covered(&self, position: (i32, i32), size: (u32, u32)) -> bool {
        self.x == position.0
            && self.y == position.1
            && self.width == size.0
            && self.height == size.1
    }
}

/// 把 Mini 浮窗覆盖到主显示器顶部居中（240×48，y=8px 下留菜单栏）；
/// 优先取 primary_monitor，fallback 到 current_monitor。Mini 形态保持
/// always_on_top + screenSaver level（与 Full 形态层级一致，仅几何不同）。
fn apply_mini_geometry<R: tauri::Runtime>(
    window: &tauri::WebviewWindow<R>,
) -> tauri::Result<()> {
    let monitor = window.primary_monitor()?.or_else(|| window.current_monitor().ok().flatten());
    if let Some(monitor) = monitor {
        let origin = monitor.position();
        let size = monitor.size();
        let cover = mini_geometry((origin.x, origin.y), (size.width, size.height));
        let position = window.outer_position()?;
        let outer = window.outer_size()?;
        if !cover.is_covered((position.x, position.y), (outer.width, outer.height)) {
            window.set_size(tauri::PhysicalSize::new(cover.width, cover.height))?;
            window.set_position(tauri::PhysicalPosition::new(cover.x, cover.y))?;
        }
    }
    Ok(())
}

/// 把窗口覆盖到主显示器可视区域；已覆盖时跳过（幂等）。
/// 优先取 primary_monitor（带 macOS 菜单栏的主屏），fallback 到 current_monitor。
/// 参数取 `WebviewWindow`（几何方法集齐备）；on_window_event 回调只给 `&Window`，
/// 由回调侧按 label 取回 WebviewWindow 复用本逻辑——`WebviewWindow` 无 `&Window`
/// 访问器（`as_ref` 只给 `&Webview`），`Manager::get_window` 又是 unstable 门控。
fn cover_display<R: tauri::Runtime>(window: &tauri::WebviewWindow<R>) -> tauri::Result<()> {
    let monitor = window.primary_monitor()?.or_else(|| window.current_monitor().ok().flatten());
    if let Some(monitor) = monitor {
        let origin = monitor.position();
        let size = monitor.size();
        let cover = DisplayCover::new((origin.x, origin.y), (size.width, size.height));
        let position = window.outer_position()?;
        let outer = window.outer_size()?;
        if !cover.is_covered((position.x, position.y), (outer.width, outer.height)) {
            window.set_size(tauri::PhysicalSize::new(cover.width, cover.height))?;
            window.set_position(tauri::PhysicalPosition::new(cover.x, cover.y))?;
        }
    }
    Ok(())
}

#[cfg(target_os = "macos")]
#[cfg(not(test))]
#[allow(unexpected_cfgs)]
fn ns_window_responds_to_set_level(ns_window: *mut objc::runtime::Object) -> bool {
    unsafe {
        let _sel = objc::sel!(respondsToSelector:);
        let set_level_sel = objc::sel!(setLevel:);
        let responds: bool = msg_send![ns_window, respondsToSelector: set_level_sel];
        responds
    }
}

/// macOS：将窗口级别设为 NSScreenSaverWindowLevel（=1000），
/// 使其始终置顶覆盖所有普通应用窗口（含活动窗口），类似屏幕保护程序层级。
///
/// Tauri alwaysOnTop 只设 NSFloatingWindowLevel（=3），活动应用窗口激活时
/// 仍会覆盖在 HUD 之上；screenSaver 级别才是真正的 "覆盖一切"。
///
/// 测试构建下为 noop——`msg_send![ns_window, setLevel:]` 在 MockRuntime 下
/// 拿到的 NSWindow 指针不响应 `setLevel:`，触发 SIGSEGV；NSWindow 层级调用
/// 无法在 cargo test 中验证，改由纯常量 + 注册锚点测试覆盖（见 tests 模块）。
#[cfg(target_os = "macos")]
#[cfg(not(test))]
#[allow(unexpected_cfgs)]
fn set_window_level_screensaver<R: tauri::Runtime>(window: &tauri::WebviewWindow<R>) -> tauri::Result<()> {
    const NS_SCREEN_SAVER_LEVEL: i64 = 1000;

    let ns_window = window.ns_window()?;
    let ns_window: *mut objc::runtime::Object = ns_window as *mut _;

    if ns_window.is_null() {
        return Err(tauri::Error::from(anyhow::anyhow!("NSWindow 指针为空")));
    }

    // SAFETY: ns_window 非空且来自 tauri 合法窗口；先校验 respondsToSelector:
    // 确认对象响应 setLevel:，避免向非法对象发送消息导致 SIGSEGV。
    unsafe {
        if !ns_window_responds_to_set_level(ns_window) {
            return Err(tauri::Error::from(anyhow::anyhow!("NSWindow 不响应 setLevel:")));
        }
        let _: () = msg_send![ns_window, setLevel: NS_SCREEN_SAVER_LEVEL];
    }
    Ok(())
}

/// 测试构建 noop（macOS）：避免 MockRuntime 下 NSWindow 指针触发 SIGSEGV。
#[cfg(target_os = "macos")]
#[cfg(test)]
fn set_window_level_screensaver<R: tauri::Runtime>(_window: &tauri::WebviewWindow<R>) -> tauri::Result<()> {
    Ok(())
}

/// 非 macOS 平台：window level 设置为 noop。
#[cfg(not(target_os = "macos"))]
fn set_window_level_screensaver<R: tauri::Runtime>(_window: &tauri::WebviewWindow<R>) -> tauri::Result<()> {
    Ok(())
}

/// macOS `CGWindowLevelForKey(kCGDesktopIconWindowLevel)` 数值（D22.1）。
///
/// 沉到桌面图标层下方——`kCGDesktopWindowLevel`（-2147483623）沉到桌面壁纸之上、
/// 图标之下；`kCGDesktopIconWindowLevel`（-2147483603）沉到图标之下，但 Apple
/// 实际上把图标层放在 desktopIconWindowLevel 之上，本常量选 `desktopIconWindowLevel`
/// 让 HUD 沉到图标之下（壁纸态用户视线不被 HUD 干扰，桌面图标照常点击）。
///
/// 注意：`CGWindowLevelForKey` 是 CGWindowLevel.h 中的枚举 key（Int32），
/// 真实 level 值由 `CGWindowLevelForKey(key)` 在运行时返回；这里直接用其文档值
/// 避免链接额外 framework（CoreGraphics 已被 zones 链接）。
pub const DESKTOP_ICON_WINDOW_LEVEL: i64 = -2_147_483_603;

/// macOS：将窗口级别设为 `desktopIconWindowLevel`（D22.1），
/// 使窗口沉到桌面图标层下方，作为桌面壁纸效果显示。
///
/// 壁纸模式窗口几何仍为 cover-display（铺满主屏可视区域），仅 level 不同；
/// 鼠标穿透默认全开（壁纸态不拦截桌面点击），交互区由 zones 分区轮询
/// 在壁纸态下保留指定区域可点击（右下角控制条 / 左边缘歌单架入口 /
/// 右边缘历史 / 双击唤醒区，见 M22.3 zoneRegistry）。
///
/// 抽出纯常量 `DESKTOP_ICON_WINDOW_LEVEL` 便于 `cargo test` 直接断言
/// （NSWindow setLevel: 在 mock runtime 下无法验证调用）。
#[cfg(target_os = "macos")]
#[cfg(not(test))]
#[allow(unexpected_cfgs)]
fn set_window_level_wallpaper<R: tauri::Runtime>(window: &tauri::WebviewWindow<R>) -> tauri::Result<()> {
    let ns_window = window.ns_window()?;
    let ns_window: *mut objc::runtime::Object = ns_window as *mut _;

    if ns_window.is_null() {
        return Err(tauri::Error::from(anyhow::anyhow!("NSWindow 指针为空")));
    }

    // SAFETY: ns_window 非空且来自 tauri 合法窗口；先校验 respondsToSelector:
    // 确认对象响应 setLevel:，避免向非法对象发送消息导致 SIGSEGV。
    unsafe {
        if !ns_window_responds_to_set_level(ns_window) {
            return Err(tauri::Error::from(anyhow::anyhow!("NSWindow 不响应 setLevel:")));
        }
        let _: () = msg_send![ns_window, setLevel: DESKTOP_ICON_WINDOW_LEVEL];
    }
    Ok(())
}

/// 测试构建 noop（macOS）：避免 MockRuntime 下 NSWindow 指针触发 SIGSEGV。
#[cfg(target_os = "macos")]
#[cfg(test)]
fn set_window_level_wallpaper<R: tauri::Runtime>(_window: &tauri::WebviewWindow<R>) -> tauri::Result<()> {
    Ok(())
}

/// 非 macOS 平台：壁纸层级为 noop（Windows `SetParent Progman` 后续实现，M22 优先 macOS）。
#[cfg(not(target_os = "macos"))]
fn set_window_level_wallpaper<R: tauri::Runtime>(_window: &tauri::WebviewWindow<R>) -> tauri::Result<()> {
    Ok(())
}

/// 切换点击穿透：`ignore = true` 时鼠标事件穿透到桌面下方窗口。
///
/// 显式标注 `R: Runtime`：省略泛型时 `WebviewWindow` 默认取 `Wry`，
/// 会让 `generate_handler!` 在泛型注册入口（ipc_configured）下无法解析 CommandArg。
#[tauri::command]
fn set_click_through<R: tauri::Runtime>(
    window: tauri::WebviewWindow<R>,
    ignore: bool,
) -> Result<(), String> {
    window
        .set_ignore_cursor_events(ignore)
        .map_err(|e| e.to_string())
}

/// 运行时切换置顶。
#[tauri::command]
fn set_always_on_top<R: tauri::Runtime>(
    window: tauri::WebviewWindow<R>,
    flag: bool,
) -> Result<(), String> {
    window.set_always_on_top(flag).map_err(|e| e.to_string())
}

/// 下发交互分区（M7.1）：覆盖写共享分区状态，供分区轮询线程读取。
///
/// zones 为窗口坐标系（CSS 逻辑像素）矩形列表；空列表 = 全穿透
/// （休眠态「只留声井」由前端下发单分区表达，Rust 不硬编码布局）。
#[tauri::command]
fn set_interactive_zones(
    zones: Vec<zones::Rect>,
    state: tauri::State<'_, zones::SharedZones>,
) -> Result<(), String> {
    utils::with_lock(&state, "interactive_zones", |guard| {
        *guard = zones;
    });
    Ok(())
}

/// 运行时切换窗口形态（M12 灵动岛双形态 + M22 壁纸模式）：Mini 浮窗 /
/// Full cover-display / Wallpaper 桌面壁纸层。
///
/// - 更新共享 `SharedWindowMode`（供 zones 轮询线程读取：Mini 时全穿透；
///   Wallpaper 时沿用 zones 分区决策，但 level 沉到桌面图标下方）；
/// - 调整窗口几何：Mini → `apply_mini_geometry`（240×48 顶部居中），
///   Full / Wallpaper → `cover_display`（铺满主屏，仅 level 不同）；
/// - 窗口层级：Mini / Full → `set_window_level_screensaver`（NSWindow level=1000），
///   Wallpaper → `set_window_level_wallpaper`（desktopIconWindowLevel，沉到图标下方）；
/// - Wallpaper 形态窗口仍 always_on_top:true（避免 Tauri 内部把窗口推回 normal
///   层级），但 level 已沉到图标下方，alwaysOnTop 与 desktopIcon level 不冲突。
///
/// 前端 `App.tsx` 据状态文件 `window_mode` 字段（语音状态推导）与 hudStore
/// `wallpaperMode`（用户主动选择）合并出最终 WindowMode，调用本 command 通知
/// Rust 调整几何与层级。幂等：同形态重复调用不引发事件回环（cover_display /
/// apply_mini_geometry 内部 `is_covered` 短路；level 设置 NSWindow 自身幂等）。
#[tauri::command]
fn set_window_mode<R: tauri::Runtime>(
    window: tauri::WebviewWindow<R>,
    mode: WindowMode,
    state: tauri::State<'_, SharedWindowMode>,
) -> Result<(), String> {
    utils::with_lock(&state, "window_mode", |guard| {
        *guard = mode;
    });
    match mode {
        WindowMode::Mini => {
            set_window_level_screensaver(&window).map_err(|e| e.to_string())?;
            apply_mini_geometry(&window).map_err(|e| e.to_string())
        }
        WindowMode::Full => {
            set_window_level_screensaver(&window).map_err(|e| e.to_string())?;
            cover_display(&window).map_err(|e| e.to_string())
        }
        WindowMode::Wallpaper => {
            set_window_level_wallpaper(&window).map_err(|e| e.to_string())?;
            cover_display(&window).map_err(|e| e.to_string())
        }
    }
}

/// IPC 注册唯一入口：全部 `#[tauri::command]` 与共享状态在此集中挂载。
///
/// run() 与测试锚点（tests::status_commands_are_registered_and_monitor_is_managed）
/// 共用本函数——新增 command 必须在此登记，否则真机 invoke 直接 reject
/// （M4.3 B1 教训：command 已实现却未注册，前端静默降级永远离线）。
pub fn ipc_configured<R: tauri::Runtime>(builder: tauri::Builder<R>) -> tauri::Builder<R> {
    builder
        .manage(std::sync::Arc::new(std::sync::Mutex::new(status::SystemMonitor::new())))
        .manage(zones::shared_zones())
        .manage(shared_window_mode())
        .manage(desktop::shared_desktop_automation())
        .invoke_handler(tauri::generate_handler![
            set_click_through,
            set_always_on_top,
            set_interactive_zones,
            set_window_mode,
            status::get_voice_status,
            status::get_home_summary,
            status::get_system_stats,
            voice::voice_interrupt,
            voice::get_assistant_identity,
            music::music_tool,
            lyrics::lyrics_tool,
            weather::weather_tool,
            office::office_tool,
            desktop::desktop_mouse_move,
            desktop::desktop_mouse_click,
            desktop::desktop_mouse_double_click,
            desktop::desktop_mouse_drag,
            desktop::desktop_type_text,
            desktop::desktop_press_key,
            desktop::desktop_key_combination,
            desktop::desktop_screenshot,
            desktop::desktop_trigger_circuit_breaker,
            desktop::desktop_reset_circuit_breaker,
            desktop::desktop_is_circuit_breaker_active,
            desktop::desktop_get_logs,
            desktop::desktop_clear_logs,
        ])
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let zone_stop_handle: std::sync::Arc<std::sync::Mutex<Option<utils::StopHandle>>> =
        std::sync::Arc::new(std::sync::Mutex::new(None));
    let zone_stop_handle_setup = zone_stop_handle.clone();
    let zone_stop_handle_event = zone_stop_handle.clone();

    ipc_configured(tauri::Builder::default())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .setup(move |app| {
            use tauri::Manager as _;
            let window = app
                .get_webview_window("main")
                .expect("main webview window must exist");
            window.set_ignore_cursor_events(true)?;

            if let Err(err) = set_window_level_screensaver(&window) {
                eprintln!("[omni-hud] screenSaver window level 设置失败（降级为 alwaysOnTop）: {err}");
            }

            cover_display(&window)?;

            let stop_handle = zones::start_zone_polling(
                window.clone(),
                app.state::<zones::SharedZones>().inner().clone(),
                app.state::<SharedWindowMode>().inner().clone(),
            )
            .map_err(|e| {
                eprintln!("[omni-hud] 分区轮询启动失败，保持默认全穿透: {e}");
                e
            })
            .ok();
            if let Ok(mut guard) = zone_stop_handle_setup.lock() {
                *guard = stop_handle;
            }

            match voice_watch::default_state_file_path() {
                Ok(state_path) => {
                    if let Err(err) = voice_watch::start_voice_watcher(app.handle(), state_path) {
                        eprintln!("[omni-hud] voice watcher 启动失败，保留 CLI 轮询兜底: {err}");
                    }
                }
                Err(err) => {
                    eprintln!("[omni-hud] 无法获取状态文件路径，保留 CLI 轮询兜底: {err}");
                }
            }

            // M33.3：注册全局熔断快捷键（Cmd+Shift+Esc）
            let desktop_state = app.state::<desktop::SharedDesktopAutomation>().inner().clone();
            if let Err(err) = desktop::register_circuit_breaker_shortcut(&app.handle(), desktop_state) {
                eprintln!("[omni-hud] 全局熔断快捷键注册失败: {err}");
            }

            Ok(())
        })
        .on_window_event(move |window, event| {
            match event {
                tauri::WindowEvent::Resized(_) | tauri::WindowEvent::ScaleFactorChanged { .. } => {
                    use tauri::Manager as _;
                    if let Some(webview_window) = window.get_webview_window(window.label()) {
                        let _ = cover_display(&webview_window);
                    }
                }
                tauri::WindowEvent::CloseRequested { .. } | tauri::WindowEvent::Destroyed => {
                    utils::with_lock(&zone_stop_handle_event, "zone_stop_handle", |guard| {
                        if let Some(handle) = guard.as_ref() {
                            handle.stop();
                        }
                    });
                }
                _ => {}
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running omni-hud");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_state_is_passthrough_and_on_top() {
        let state = HudWindowState::new();
        assert!(state.click_through, "初始必须穿透（不拦截桌面点击）");
        assert!(state.always_on_top, "初始必须置顶");
    }

    #[test]
    fn hud_window_state_default_matches_new() {
        assert_eq!(HudWindowState::default(), HudWindowState::new());
    }

    #[test]
    fn hover_into_interactive_zone_disables_passthrough() {
        let mut state = HudWindowState::new();
        let applied = state.apply_hover(true);
        assert!(!applied);
        assert!(!state.click_through);
    }

    #[test]
    fn hover_leave_restores_passthrough() {
        let mut state = HudWindowState::new();
        state.apply_hover(true);
        let applied = state.apply_hover(false);
        assert!(applied);
        assert!(state.click_through);
    }

    #[test]
    fn toggle_always_on_top_flips_flag() {
        let mut state = HudWindowState::new();
        assert!(!state.toggle_always_on_top());
        assert!(state.toggle_always_on_top());
    }

    #[test]
    fn display_cover_targets_monitor_origin_and_full_frame() {
        let cover = DisplayCover::new((0, 0), (1920, 1080));
        assert_eq!(
            cover,
            DisplayCover {
                x: 0,
                y: 0,
                width: 1920,
                height: 1080
            },
            "覆盖目标必须是显示器原点 + 全部可视 frame"
        );
    }

    #[test]
    fn display_cover_respects_non_zero_monitor_origin() {
        let cover = DisplayCover::new((2560, 0), (1920, 1080));
        assert_eq!((cover.x, cover.y), (2560, 0));
    }

    #[test]
    fn is_covered_only_when_geometry_exactly_matches() {
        let cover = DisplayCover::new((0, 0), (1920, 1080));
        assert!(cover.is_covered((0, 0), (1920, 1080)), "完全一致 = 已覆盖（幂等跳过）");
        assert!(!cover.is_covered((1, 0), (1920, 1080)), "位置偏移必须重覆盖");
        assert!(!cover.is_covered((0, 0), (380, 560),), "初始小窗口必须重覆盖");
        assert!(!cover.is_covered((0, 0), (1920, 1079)), "高度差 1px 也必须重覆盖");
    }

    fn ipc_test_webview() -> tauri::WebviewWindow<tauri::test::MockRuntime> {
        let app = ipc_configured(tauri::test::mock_builder())
            .build(tauri::test::mock_context(tauri::test::noop_assets()))
            .expect("mock app 必须能构建");
        tauri::WebviewWindowBuilder::new(&app, "main", Default::default())
            .build()
            .expect("mock webview 必须能创建")
    }

    fn invoke_cmd_with_body(
        webview: &tauri::WebviewWindow<tauri::test::MockRuntime>,
        cmd: &str,
        body: tauri::ipc::InvokeBody,
    ) -> Result<serde_json::Value, serde_json::Value> {
        tauri::test::get_ipc_response(
            webview,
            tauri::webview::InvokeRequest {
                cmd: cmd.into(),
                callback: tauri::ipc::CallbackFn(0),
                error: tauri::ipc::CallbackFn(1),
                url: "tauri://localhost".parse().unwrap(),
                body,
                headers: Default::default(),
                invoke_key: tauri::test::INVOKE_KEY.to_string(),
            },
        )
        .map(|body| body.deserialize().expect("响应必须可反序列化为 JSON"))
    }

    fn invoke_cmd(
        webview: &tauri::WebviewWindow<tauri::test::MockRuntime>,
        cmd: &str,
    ) -> Result<serde_json::Value, serde_json::Value> {
        invoke_cmd_with_body(webview, cmd, tauri::ipc::InvokeBody::default())
    }

    #[test]
    fn status_commands_are_registered_and_monitor_is_managed() {
        let webview = ipc_test_webview();
        for cmd in ["get_voice_status", "get_home_summary", "get_system_stats"] {
            assert!(
                invoke_cmd(&webview, cmd).is_ok(),
                "{cmd} 未注册到 invoke_handler（B1 回归）"
            );
        }
        let stats = invoke_cmd(&webview, "get_system_stats").expect("get_system_stats 必须已注册");
        assert_eq!(
            stats["available"],
            serde_json::Value::Bool(true),
            "SystemMonitor state 未 manage 或采集失败"
        );
        assert!(stats["memoryTotalBytes"].as_u64().unwrap() > 0);
        assert!(
            invoke_cmd(&webview, "get_voice_status_unregistered_typo").is_err(),
            "未注册的 command 必须在 IPC 层返回 Err"
        );
    }

    #[test]
    fn voice_interrupt_command_is_registered() {
        let webview = ipc_test_webview();
        let result = invoke_cmd(&webview, "voice_interrupt");
        match result {
            Ok(_) => {}
            Err(err) => {
                let msg = err.to_string();
                assert!(
                    !msg.contains("not found") && !msg.contains("unknown command"),
                    "voice_interrupt 未注册到 invoke_handler: {msg}"
                );
            }
        }
    }

    #[test]
    fn get_assistant_identity_command_is_registered() {
        let webview = ipc_test_webview();
        let result = invoke_cmd(&webview, "get_assistant_identity");
        match result {
            Ok(v) => {
                assert_eq!(v["ok"], true, "get_assistant_identity 应返回 ok:true");
                assert_eq!(v["data"]["display_name"], "雪莉", "默认身份应为雪莉");
            }
            Err(err) => {
                let msg = err.to_string();
                assert!(
                    !msg.contains("not found") && !msg.contains("unknown command"),
                    "get_assistant_identity 未注册到 invoke_handler: {msg}"
                );
            }
        }
    }

    #[test]
    fn window_mode_defaults_to_full() {
        assert_eq!(WindowMode::default(), WindowMode::Full);
    }

    #[test]
    fn mini_geometry_centers_horizontally_with_top_margin() {
        let cover = mini_geometry((0, 0), (1920, 1080));
        assert_eq!(cover.width, MINI_WIDTH, "宽度必须为 MINI_WIDTH");
        assert_eq!(cover.height, MINI_HEIGHT, "高度必须为 MINI_HEIGHT");
        assert_eq!(cover.x, 840, "x 必须水平居中");
        assert_eq!(cover.y, MINI_TOP_MARGIN_PX, "y 必须为顶部留白");
    }

    #[test]
    fn mini_geometry_respects_non_zero_monitor_origin() {
        let cover = mini_geometry((2560, 0), (1920, 1080));
        assert_eq!(cover.x, 2560 + 840, "副屏原点偏移必须叠加");
        assert_eq!(cover.y, MINI_TOP_MARGIN_PX);
    }

    #[test]
    fn mini_geometry_clamps_when_monitor_narrower_than_window() {
        let cover = mini_geometry((50, 0), (200, 1080));
        assert_eq!(cover.x, 50, "窄屏不得让浮窗跑到原点左侧");
        assert_eq!(cover.width, MINI_WIDTH);
    }

    #[test]
    fn set_window_mode_command_is_registered() {
        let webview = ipc_test_webview();
        let result = invoke_cmd_with_body(
            &webview,
            "set_window_mode",
            tauri::ipc::InvokeBody::Json(serde_json::json!({"mode": "full"})),
        );
        match result {
            Ok(_) => {}
            Err(err) => {
                let msg = err.to_string();
                assert!(
                    !msg.contains("not found") && !msg.contains("unknown command"),
                    "set_window_mode 未注册到 invoke_handler: {msg}"
                );
            }
        }
    }

    #[test]
    fn window_mode_has_wallpaper_variant_distinct_from_full_and_mini() {
        assert_ne!(WindowMode::Wallpaper, WindowMode::Full);
        assert_ne!(WindowMode::Wallpaper, WindowMode::Mini);
        let serialized = serde_json::to_string(&WindowMode::Wallpaper).unwrap();
        assert_eq!(serialized, "\"wallpaper\"");
        let deserialized: WindowMode = serde_json::from_str("\"wallpaper\"").unwrap();
        assert_eq!(deserialized, WindowMode::Wallpaper);
    }

    #[test]
    fn window_mode_default_is_full_not_wallpaper() {
        assert_eq!(WindowMode::default(), WindowMode::Full);
        assert_ne!(WindowMode::default(), WindowMode::Wallpaper);
    }

    #[test]
    #[allow(clippy::assertions_on_constants)]
    fn desktop_icon_window_level_is_negative_and_below_screensaver() {
        assert!(DESKTOP_ICON_WINDOW_LEVEL < 0, "desktopIconWindowLevel 必须为负数（沉到桌面层）");
        assert!(
            DESKTOP_ICON_WINDOW_LEVEL < 1000,
            "desktopIconWindowLevel 必须在 screenSaver level（1000）下方"
        );
        assert_eq!(DESKTOP_ICON_WINDOW_LEVEL, -2_147_483_603);
    }

    #[test]
    fn set_window_mode_accepts_wallpaper_via_ipc() {
        let webview = ipc_test_webview();
        let result = invoke_cmd_with_body(
            &webview,
            "set_window_mode",
            tauri::ipc::InvokeBody::Json(serde_json::json!({"mode": "wallpaper"})),
        );
        match result {
            Ok(_) => {}
            Err(err) => {
                let msg = err.to_string();
                assert!(
                    !msg.contains("not found") && !msg.contains("unknown command"),
                    "set_window_mode 未注册到 invoke_handler: {msg}"
                );
                assert!(
                    !msg.contains("unknown variant") && !msg.contains("invalid type"),
                    "WindowMode 反序列化未接受 \"wallpaper\" 变体: {msg}"
                );
            }
        }
    }

    #[test]
    fn shared_window_mode_round_trips_wallpaper() {
        let shared = shared_window_mode();
        {
            let mut guard = shared.lock().unwrap();
            *guard = WindowMode::Wallpaper;
        }
        let snapshot = *shared.lock().unwrap();
        assert_eq!(snapshot, WindowMode::Wallpaper);
    }
}
