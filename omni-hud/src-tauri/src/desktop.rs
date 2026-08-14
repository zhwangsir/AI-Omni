//! M33 桌面自动化模块：鼠标/键盘/屏幕截图核心能力。
//!
//! 复用 LUVU nut-js 核心模式，Rust 原生实现：
//! - 鼠标：移动、点击、双击、拖拽
//! - 键盘：文本输入、按键、组合键
//! - 屏幕：区域截图
//!
//! 所有操作支持熔断（见 circuit_breaker），操作日志记录到统一审计。

use anyhow::{Context, Result};
use enigo::{
    Direction::{Click, Press, Release},
    Enigo, Key, Keyboard, Mouse, Settings,
};
use log::{info, warn};
use serde::{Deserialize, Serialize};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

/// 鼠标按钮枚举
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum MouseButton {
    Left,
    Right,
    Middle,
}

impl From<MouseButton> for enigo::Button {
    fn from(btn: MouseButton) -> Self {
        match btn {
            MouseButton::Left => enigo::Button::Left,
            MouseButton::Right => enigo::Button::Right,
            MouseButton::Middle => enigo::Button::Middle,
        }
    }
}

/// 特殊按键枚举
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SpecialKey {
    Return,
    Escape,
    Space,
    Tab,
    Backspace,
    Delete,
    Up,
    Down,
    Left,
    Right,
    Home,
    End,
    PageUp,
    PageDown,
    F1,
    F2,
    F3,
    F4,
    F5,
    F6,
    F7,
    F8,
    F9,
    F10,
    F11,
    F12,
}

impl From<SpecialKey> for Key {
    fn from(key: SpecialKey) -> Self {
        match key {
            SpecialKey::Return => Key::Return,
            SpecialKey::Escape => Key::Escape,
            SpecialKey::Space => Key::Space,
            SpecialKey::Tab => Key::Tab,
            SpecialKey::Backspace => Key::Backspace,
            SpecialKey::Delete => Key::Delete,
            SpecialKey::Up => Key::UpArrow,
            SpecialKey::Down => Key::DownArrow,
            SpecialKey::Left => Key::LeftArrow,
            SpecialKey::Right => Key::RightArrow,
            SpecialKey::Home => Key::Home,
            SpecialKey::End => Key::End,
            SpecialKey::PageUp => Key::PageUp,
            SpecialKey::PageDown => Key::PageDown,
            SpecialKey::F1 => Key::F1,
            SpecialKey::F2 => Key::F2,
            SpecialKey::F3 => Key::F3,
            SpecialKey::F4 => Key::F4,
            SpecialKey::F5 => Key::F5,
            SpecialKey::F6 => Key::F6,
            SpecialKey::F7 => Key::F7,
            SpecialKey::F8 => Key::F8,
            SpecialKey::F9 => Key::F9,
            SpecialKey::F10 => Key::F10,
            SpecialKey::F11 => Key::F11,
            SpecialKey::F12 => Key::F12,
        }
    }
}

/// 修饰键枚举
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ModifierKey {
    Command,
    Ctrl,
    Alt,
    Shift,
}

impl From<ModifierKey> for Key {
    fn from(key: ModifierKey) -> Self {
        match key {
            ModifierKey::Command => Key::Meta,
            ModifierKey::Ctrl => Key::Control,
            ModifierKey::Alt => Key::Alt,
            ModifierKey::Shift => Key::Shift,
        }
    }
}

/// 屏幕区域
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct ScreenRegion {
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
}

/// 桌面自动化操作日志
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AutomationLog {
    pub timestamp_ms: u64,
    pub action: String,
    pub details: String,
    pub success: bool,
}

/// 桌面自动化核心结构
pub struct DesktopAutomation {
    enigo: Mutex<Enigo>,
    /// 熔断标志：true 时所有操作被拒绝
    circuit_breaker: AtomicBool,
    /// 操作日志（内存缓冲，最近 100 条）
    logs: Mutex<Vec<AutomationLog>>,
}

// Enigo 内部使用平台特定 API，但 Mutex 保证线程安全访问
unsafe impl Send for DesktopAutomation {}
unsafe impl Sync for DesktopAutomation {}

impl DesktopAutomation {
    /// 创建新的桌面自动化实例
    pub fn new() -> Result<Self> {
        let enigo = Enigo::new(&Settings::default()).context("初始化 enigo 失败")?;
        Ok(Self {
            enigo: Mutex::new(enigo),
            circuit_breaker: AtomicBool::new(false),
            logs: Mutex::new(Vec::new()),
        })
    }

    /// 触发熔断（紧急停止所有自动化操作）
    pub fn trigger_circuit_breaker(&self) {
        warn!("桌面自动化熔断已触发");
        self.circuit_breaker.store(true, Ordering::SeqCst);
    }

    /// 重置熔断
    pub fn reset_circuit_breaker(&self) {
        info!("桌面自动化熔断已重置");
        self.circuit_breaker.store(false, Ordering::SeqCst);
    }

    /// 检查熔断状态
    pub fn is_circuit_breaker_active(&self) -> bool {
        self.circuit_breaker.load(Ordering::SeqCst)
    }

    /// 记录操作日志
    fn log_action(&self, action: &str, details: &str, success: bool) {
        let log_entry = AutomationLog {
            timestamp_ms: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis() as u64,
            action: action.to_string(),
            details: details.to_string(),
            success,
        };
        let mut logs = self.logs.lock().unwrap();
        logs.push(log_entry);
        // 保留最近 100 条
        if logs.len() > 100 {
            logs.remove(0);
        }
    }

    /// 获取操作日志
    pub fn get_logs(&self) -> Vec<AutomationLog> {
        self.logs.lock().unwrap().clone()
    }

    /// 清空操作日志
    pub fn clear_logs(&self) {
        self.logs.lock().unwrap().clear();
    }

    /// 检查熔断状态，若激活则返回错误
    fn check_circuit_breaker(&self) -> Result<()> {
        if self.is_circuit_breaker_active() {
            anyhow::bail!("桌面自动化熔断已激活，所有操作被拒绝");
        }
        Ok(())
    }

    // ==================== 鼠标操作 ====================

    /// 移动鼠标到指定坐标
    pub fn mouse_move_to(&self, x: i32, y: i32) -> Result<()> {
        self.check_circuit_breaker()?;
        let mut enigo = self.enigo.lock().unwrap();
        enigo
            .move_mouse(x, y, enigo::Coordinate::Abs)
            .context("鼠标移动失败")?;
        self.log_action("mouse_move", &format!("({}, {})", x, y), true);
        Ok(())
    }

    /// 获取当前鼠标位置
    pub fn mouse_position(&self) -> Result<(i32, i32)> {
        self.check_circuit_breaker()?;
        let enigo = self.enigo.lock().unwrap();
        let pos = enigo.location().context("获取鼠标位置失败")?;
        Ok(pos)
    }

    /// 鼠标点击
    pub fn mouse_click(&self, button: MouseButton) -> Result<()> {
        self.check_circuit_breaker()?;
        let mut enigo = self.enigo.lock().unwrap();
        enigo
            .button(button.into(), Click)
            .context("鼠标点击失败")?;
        self.log_action("mouse_click", &format!("{:?}", button), true);
        Ok(())
    }

    /// 鼠标双击
    pub fn mouse_double_click(&self, button: MouseButton) -> Result<()> {
        self.check_circuit_breaker()?;
        let mut enigo = self.enigo.lock().unwrap();
        enigo
            .button(button.into(), Click)
            .context("鼠标双击失败（第一次）")?;
        enigo
            .button(button.into(), Click)
            .context("鼠标双击失败（第二次）")?;
        self.log_action("mouse_double_click", &format!("{:?}", button), true);
        Ok(())
    }

    /// 鼠标按下
    pub fn mouse_down(&self, button: MouseButton) -> Result<()> {
        self.check_circuit_breaker()?;
        let mut enigo = self.enigo.lock().unwrap();
        enigo
            .button(button.into(), Press)
            .context("鼠标按下失败")?;
        self.log_action("mouse_down", &format!("{:?}", button), true);
        Ok(())
    }

    /// 鼠标释放
    pub fn mouse_up(&self, button: MouseButton) -> Result<()> {
        self.check_circuit_breaker()?;
        let mut enigo = self.enigo.lock().unwrap();
        enigo
            .button(button.into(), Release)
            .context("鼠标释放失败")?;
        self.log_action("mouse_up", &format!("{:?}", button), true);
        Ok(())
    }

    /// 鼠标拖拽
    pub fn mouse_drag(&self, from_x: i32, from_y: i32, to_x: i32, to_y: i32) -> Result<()> {
        self.check_circuit_breaker()?;
        let mut enigo = self.enigo.lock().unwrap();
        enigo
            .move_mouse(from_x, from_y, enigo::Coordinate::Abs)
            .context("拖拽失败：移动到起点")?;
        enigo
            .button(enigo::Button::Left, Press)
            .context("拖拽失败：按下左键")?;
        enigo
            .move_mouse(to_x, to_y, enigo::Coordinate::Abs)
            .context("拖拽失败：移动到终点")?;
        enigo
            .button(enigo::Button::Left, Release)
            .context("拖拽失败：释放左键")?;
        self.log_action(
            "mouse_drag",
            &format!("({}, {}) → ({}, {})", from_x, from_y, to_x, to_y),
            true,
        );
        Ok(())
    }

    // ==================== 键盘操作 ====================

    /// 输入文本
    pub fn type_text(&self, text: &str) -> Result<()> {
        self.check_circuit_breaker()?;
        let mut enigo = self.enigo.lock().unwrap();
        enigo.text(text).context("文本输入失败")?;
        self.log_action("type_text", &format!("{} 字符", text.len()), true);
        Ok(())
    }

    /// 按下特殊键
    pub fn press_key(&self, key: SpecialKey) -> Result<()> {
        self.check_circuit_breaker()?;
        let mut enigo = self.enigo.lock().unwrap();
        enigo.key(key.into(), Click).context("按键失败")?;
        self.log_action("press_key", &format!("{:?}", key), true);
        Ok(())
    }

    /// 组合键（如 Cmd+C）
    pub fn key_combination(&self, modifiers: &[ModifierKey], key: SpecialKey) -> Result<()> {
        self.check_circuit_breaker()?;
        let mut enigo = self.enigo.lock().unwrap();
        // 按下修饰键
        for modifier in modifiers {
            enigo
                .key((*modifier).into(), Press)
                .context("组合键失败：按下修饰键")?;
        }
        // 按下主键
        enigo.key(key.into(), Click).context("组合键失败：按下主键")?;
        // 释放修饰键（逆序）
        for modifier in modifiers.iter().rev() {
            enigo
                .key((*modifier).into(), Release)
                .context("组合键失败：释放修饰键")?;
        }
        self.log_action(
            "key_combination",
            &format!("{:?} + {:?}", modifiers, key),
            true,
        );
        Ok(())
    }

    // ==================== 屏幕截图 ====================

    /// 截取屏幕区域，返回 PNG 字节
    pub fn screenshot_region(&self, region: ScreenRegion) -> Result<Vec<u8>> {
        self.check_circuit_breaker()?;
        let screens = screenshots::Screen::all().context("获取屏幕列表失败")?;
        let screen = screens
            .first()
            .context("未找到可用屏幕")?;
        let image = screen
            .capture_area(region.x, region.y, region.width, region.height)
            .context("屏幕截图失败")?;
        // 使用 image crate 编码 PNG
        let mut png_bytes = Vec::new();
        image
            .write_to(
                &mut std::io::Cursor::new(&mut png_bytes),
                screenshots::image::ImageFormat::Png,
            )
            .context("PNG 编码失败")?;
        self.log_action(
            "screenshot",
            &format!(
                "({}, {}) {}x{}",
                region.x, region.y, region.width, region.height
            ),
            true,
        );
        Ok(png_bytes)
    }

    /// 截取全屏，返回 PNG 字节
    pub fn screenshot_full(&self) -> Result<Vec<u8>> {
        self.check_circuit_breaker()?;
        let screens = screenshots::Screen::all().context("获取屏幕列表失败")?;
        let screen = screens
            .first()
            .context("未找到可用屏幕")?;
        let image = screen.capture().context("全屏截图失败")?;
        // 使用 image crate 编码 PNG
        let mut png_bytes = Vec::new();
        image
            .write_to(
                &mut std::io::Cursor::new(&mut png_bytes),
                screenshots::image::ImageFormat::Png,
            )
            .context("PNG 编码失败")?;
        self.log_action(
            "screenshot_full",
            &format!("{}x{}", image.width(), image.height()),
            true,
        );
        Ok(png_bytes)
    }
}

// ==================== Tauri 命令接口 ====================

use tauri::State;
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut};

/// 共享桌面自动化状态（Enigo 非 Send/Sync，用 Mutex 包装）
pub type SharedDesktopAutomation = std::sync::Arc<Mutex<DesktopAutomation>>;

/// 创建共享桌面自动化实例
pub fn shared_desktop_automation() -> SharedDesktopAutomation {
    std::sync::Arc::new(Mutex::new(
        DesktopAutomation::new().expect("初始化桌面自动化失败"),
    ))
}

/// 注册全局熔断快捷键（Cmd+Shift+Esc）
pub fn register_circuit_breaker_shortcut<R: tauri::Runtime>(
    app: &tauri::AppHandle<R>,
    state: SharedDesktopAutomation,
) -> Result<(), Box<dyn std::error::Error>> {
    let shortcut = Shortcut::new(Some(Modifiers::SUPER | Modifiers::SHIFT), Code::Escape);
    // 只走 on_shortcut：其内部即完成注册并挂载 handler；
    // 先 register 再 on_shortcut 会因同一 hotkey 二次注册失败导致熔断静默失效。
    app.global_shortcut().on_shortcut(shortcut, move |_app, _shortcut, _event| {
        let automation = state.lock().unwrap();
        automation.trigger_circuit_breaker();
        log::warn!("全局熔断快捷键触发：Cmd+Shift+Esc");
    })?;
    Ok(())
}

/// 鼠标移动命令
#[tauri::command]
pub async fn desktop_mouse_move(
    x: i32,
    y: i32,
    state: State<'_, SharedDesktopAutomation>,
) -> Result<(), String> {
    state.lock().unwrap().mouse_move_to(x, y).map_err(|e| e.to_string())
}

/// 鼠标点击命令
#[tauri::command]
pub async fn desktop_mouse_click(
    button: MouseButton,
    state: State<'_, SharedDesktopAutomation>,
) -> Result<(), String> {
    state.lock().unwrap().mouse_click(button).map_err(|e| e.to_string())
}

/// 鼠标双击命令
#[tauri::command]
pub async fn desktop_mouse_double_click(
    button: MouseButton,
    state: State<'_, SharedDesktopAutomation>,
) -> Result<(), String> {
    state.lock().unwrap().mouse_double_click(button).map_err(|e| e.to_string())
}

/// 鼠标拖拽命令
#[tauri::command]
pub async fn desktop_mouse_drag(
    from_x: i32,
    from_y: i32,
    to_x: i32,
    to_y: i32,
    state: State<'_, SharedDesktopAutomation>,
) -> Result<(), String> {
    state
        .lock()
        .unwrap()
        .mouse_drag(from_x, from_y, to_x, to_y)
        .map_err(|e| e.to_string())
}

/// 文本输入命令
#[tauri::command]
pub async fn desktop_type_text(
    text: String,
    state: State<'_, SharedDesktopAutomation>,
) -> Result<(), String> {
    state.lock().unwrap().type_text(&text).map_err(|e| e.to_string())
}

/// 按键命令
#[tauri::command]
pub async fn desktop_press_key(
    key: SpecialKey,
    state: State<'_, SharedDesktopAutomation>,
) -> Result<(), String> {
    state.lock().unwrap().press_key(key).map_err(|e| e.to_string())
}

/// 组合键命令
#[tauri::command]
pub async fn desktop_key_combination(
    modifiers: Vec<ModifierKey>,
    key: SpecialKey,
    state: State<'_, SharedDesktopAutomation>,
) -> Result<(), String> {
    state
        .lock()
        .unwrap()
        .key_combination(&modifiers, key)
        .map_err(|e| e.to_string())
}

/// 屏幕截图命令（返回 base64 编码的 PNG）
#[tauri::command]
pub async fn desktop_screenshot(
    region: Option<ScreenRegion>,
    state: State<'_, SharedDesktopAutomation>,
) -> Result<String, String> {
    let png_bytes = match region {
        Some(r) => state.lock().unwrap().screenshot_region(r).map_err(|e| e.to_string())?,
        None => state.lock().unwrap().screenshot_full().map_err(|e| e.to_string())?,
    };
    use base64::Engine;
    Ok(base64::engine::general_purpose::STANDARD.encode(png_bytes))
}

/// 触发熔断命令
#[tauri::command]
pub async fn desktop_trigger_circuit_breaker(
    state: State<'_, SharedDesktopAutomation>,
) -> Result<(), String> {
    state.lock().unwrap().trigger_circuit_breaker();
    Ok(())
}

/// 重置熔断命令
#[tauri::command]
pub async fn desktop_reset_circuit_breaker(
    state: State<'_, SharedDesktopAutomation>,
) -> Result<(), String> {
    state.lock().unwrap().reset_circuit_breaker();
    Ok(())
}

/// 获取熔断状态命令
#[tauri::command]
pub async fn desktop_is_circuit_breaker_active(
    state: State<'_, SharedDesktopAutomation>,
) -> Result<bool, String> {
    Ok(state.lock().unwrap().is_circuit_breaker_active())
}

/// 获取操作日志命令
#[tauri::command]
pub async fn desktop_get_logs(
    state: State<'_, SharedDesktopAutomation>,
) -> Result<Vec<AutomationLog>, String> {
    Ok(state.lock().unwrap().get_logs())
}

/// 清空操作日志命令
#[tauri::command]
pub async fn desktop_clear_logs(
    state: State<'_, SharedDesktopAutomation>,
) -> Result<(), String> {
    state.lock().unwrap().clear_logs();
    Ok(())
}

// ==================== 单元测试 ====================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_mouse_button_conversion() {
        let btn: enigo::Button = MouseButton::Left.into();
        assert!(matches!(btn, enigo::Button::Left));
    }

    #[test]
    fn test_special_key_conversion() {
        let key: Key = SpecialKey::Return.into();
        assert!(matches!(key, Key::Return));
    }

    #[test]
    fn test_modifier_key_conversion() {
        let key: Key = ModifierKey::Command.into();
        assert!(matches!(key, Key::Meta));
    }

    #[test]
    fn test_circuit_breaker() {
        let automation = DesktopAutomation::new().unwrap();
        assert!(!automation.is_circuit_breaker_active());

        automation.trigger_circuit_breaker();
        assert!(automation.is_circuit_breaker_active());

        automation.reset_circuit_breaker();
        assert!(!automation.is_circuit_breaker_active());
    }

    #[test]
    fn test_operation_logging() {
        let automation = DesktopAutomation::new().unwrap();
        automation.log_action("test", "details", true);

        let logs = automation.get_logs();
        assert_eq!(logs.len(), 1);
        assert_eq!(logs[0].action, "test");
        assert_eq!(logs[0].details, "details");
        assert!(logs[0].success);
    }

    #[test]
    fn test_log_buffer_limit() {
        let automation = DesktopAutomation::new().unwrap();
        // 添加 150 条日志
        for i in 0..150 {
            automation.log_action("test", &format!("log {}", i), true);
        }

        let logs = automation.get_logs();
        // 应只保留最近 100 条
        assert_eq!(logs.len(), 100);
        assert_eq!(logs[0].details, "log 50");
        assert_eq!(logs[99].details, "log 149");
    }

    #[test]
    fn test_clear_logs() {
        let automation = DesktopAutomation::new().unwrap();
        automation.log_action("test", "details", true);
        assert_eq!(automation.get_logs().len(), 1);

        automation.clear_logs();
        assert_eq!(automation.get_logs().len(), 0);
    }
}
