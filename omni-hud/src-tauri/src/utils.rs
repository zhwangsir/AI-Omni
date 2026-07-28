//! 通用工具模块：锁污染处理、子进程超时、停止句柄、Python CLI 统一调用器等。

use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

/// 后台线程停止句柄：调用 stop() 标记线程应退出。
#[derive(Debug, Clone)]
pub struct StopHandle {
    stop: Arc<AtomicBool>,
}

impl StopHandle {
    pub fn new() -> Self {
        Self {
            stop: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn stop(&self) {
        self.stop.store(true, Ordering::SeqCst);
    }

    pub fn is_stopped(&self) -> bool {
        self.stop.load(Ordering::SeqCst)
    }
}

impl Default for StopHandle {
    fn default() -> Self {
        Self::new()
    }
}

/// 统一处理 Mutex 锁污染：获取锁并在作用域内执行闭包；
/// 锁被污染（持有锁的线程 panic）时记录 warn 日志，不执行闭包。
///
/// TDD 说明：此函数避免锁污染导致整个进程崩溃，调用方在闭包内安全操作 MutexGuard。
pub fn with_lock<T, F: FnOnce(&mut T)>(
    lock: &std::sync::Mutex<T>,
    lock_name: &str,
    f: F,
) {
    match lock.lock() {
        Ok(mut guard) => f(&mut guard),
        Err(e) => {
            log::warn!("Mutex 锁污染 [{}]，跳过操作: {}", lock_name, e);
        }
    }
}

/// 获取 Mutex 锁并克隆内部值；锁污染时返回 T::default()。
pub fn lock_clone<T>(lock: &std::sync::Mutex<T>, lock_name: &str) -> T
where
    T: Clone + Default,
{
    match lock.lock() {
        Ok(guard) => guard.clone(),
        Err(e) => {
            log::warn!("Mutex 锁污染 [{}]，返回默认值: {}", lock_name, e);
            T::default()
        }
    }
}

/// 默认 CLI 超时（秒）。
pub const DEFAULT_CLI_TIMEOUT_SECS: u64 = 5;

/// 子进程执行结果：包含 stdout、stderr、退出状态。
#[derive(Debug)]
pub struct CliOutput {
    pub stdout: String,
    pub stderr: String,
    pub status: std::process::ExitStatus,
}

impl CliOutput {
    pub fn status_success(&self) -> bool {
        self.status.success()
    }

    pub fn status_code(&self) -> Option<i32> {
        self.status.code()
    }
}

/// 带超时执行子进程并捕获 stdout+stderr，无论退出码如何都返回输出。
///
/// 超时后 kill 子进程并返回 Err。
pub fn run_command_with_timeout(
    cmd: &mut Command,
    timeout_secs: u64,
) -> Result<CliOutput, String> {
    let mut child = cmd
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .map_err(|e| format!("启动进程失败: {e}"))?;

    wait_with_timeout(&mut child, timeout_secs)?;

    let output = child
        .wait_with_output()
        .map_err(|e| format!("等待进程输出失败: {e}"))?;

    Ok(CliOutput {
        stdout: String::from_utf8(output.stdout)
            .map_err(|e| format!("进程 stdout 非 UTF-8: {e}"))?,
        stderr: String::from_utf8(output.stderr)
            .map_err(|e| format!("进程 stderr 非 UTF-8: {e}"))?,
        status: output.status,
    })
}

fn wait_with_timeout(child: &mut Child, timeout_secs: u64) -> Result<(), String> {
    let start = std::time::Instant::now();
    let timeout = Duration::from_secs(timeout_secs);

    loop {
        match child.try_wait() {
            Ok(Some(_)) => return Ok(()),
            Ok(None) => {
                if start.elapsed() >= timeout {
                    let _ = child.kill();
                    return Err(format!("子进程超时（{}秒），已 kill", timeout_secs));
                }
                std::thread::sleep(Duration::from_millis(50));
            }
            Err(e) => return Err(format!("检查进程状态失败: {e}")),
        }
    }
}

/// 工具白名单校验结果。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ToolValidation {
    Valid,
    Invalid,
}

/// 校验工具名是否在白名单内。
pub fn validate_tool_name(tool: &str, allowed: &[&str]) -> ToolValidation {
    if allowed.contains(&tool) {
        ToolValidation::Valid
    } else {
        ToolValidation::Invalid
    }
}

/// 构造无效工具错误信封。
pub fn invalid_tool_envelope() -> serde_json::Value {
    serde_json::json!({
        "ok": false,
        "error": {
            "code": "E_INVALID_TOOL",
            "message": "不允许的工具名"
        }
    })
}

/// home_dir() 失败时返回 Err 而非静默降级。
pub fn home_dir() -> Result<PathBuf, String> {
    dirs::home_dir().ok_or_else(|| "无法获取用户家目录（HOME 环境变量未设置）".to_owned())
}

/// 默认仓库根：从 CARGO_MANIFEST_DIR（omni-hud/src-tauri）推导两级上 = AI-Omni 项目根。
pub fn default_repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .canonicalize()
        .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join(".."))
}

/// Python CLI 统一调用器。
/// 封装 cwd 设置、PYTHONPATH 设置、模块名构造、参数传递、超时执行。
#[derive(Debug, Clone)]
pub struct PythonCliRunner {
    pub python: PathBuf,
    pub omni_root: PathBuf,
    pub timeout_secs: u64,
}

impl PythonCliRunner {
    pub fn new(omni_root: PathBuf) -> Self {
        Self {
            python: PathBuf::from("python3"),
            omni_root,
            timeout_secs: 15,
        }
    }

    pub fn from_env() -> Self {
        Self {
            python: PathBuf::from("python3"),
            omni_root: default_repo_root(),
            timeout_secs: 15,
        }
    }

    pub fn with_timeout(mut self, secs: u64) -> Self {
        self.timeout_secs = secs;
        self
    }

    /// 调用 omni_<module> <args...>，返回 stdout 字符串或错误信息。
    /// 自动设置 current_dir 和 PYTHONPATH。不检查退出码——由调用方决定。
    pub fn call(&self, module: &str, args: &[&str]) -> Result<String, String> {
        let mut cmd = Command::new(&self.python);
        cmd.arg("-m").arg(format!("omni_{}", module));
        for arg in args {
            cmd.arg(arg);
        }
        self.run_captured(&mut cmd)
    }

    /// 调用 omni_<module> <args...> 并解析 JSON 结果。
    pub fn call_json(&self, module: &str, args: &[&str]) -> Result<serde_json::Value, String> {
        let stdout = self.call(module, args)?;
        serde_json::from_str(stdout.trim()).map_err(|e| format!("JSON 解析失败: {}", e))
    }

    /// 调用插件 CLI（`python3 -m <plugin> <args...>`），要求退出码 0 且 stdout 非空。
    /// 用于 voice interrupt 等场景。
    pub fn run_plugin_cli(&self, plugin: &str, args: &[&str]) -> Result<String, String> {
        let mut cmd = Command::new(&self.python);
        cmd.arg("-m").arg(plugin).args(args);
        let output = self.run_captured_output(&mut cmd)?;
        if !output.status_success() {
            return Err(format!(
                "{plugin} CLI 退出码 {:?}: {}",
                output.status_code(),
                output.stderr
            ));
        }
        let trimmed = output.stdout.trim().to_string();
        if trimmed.is_empty() {
            return Err(format!("{plugin} CLI 返回空输出"));
        }
        Ok(trimmed)
    }

    /// 调用插件 CLI 并捕获 stdout（无论退出码如何）——用于音乐/歌词/天气等
    /// 错误信封走 stdout 而非 stderr 的场景（退出码 1 但 stdout 仍是合法 JSON 信封）。
    pub fn run_plugin_cli_capture(&self, plugin: &str, args: &[&str]) -> Result<String, String> {
        let mut cmd = Command::new(&self.python);
        cmd.arg("-m").arg(plugin).args(args);
        let output = self.run_captured_output(&mut cmd)?;
        if !output.stderr.is_empty() {
            eprintln!("[omni-hud] CLI stderr [{plugin}]: {}", output.stderr);
        }
        Ok(output.stdout)
    }

    fn run_captured(&self, cmd: &mut Command) -> Result<String, String> {
        let output = self.run_captured_output(cmd)?;
        if !output.stderr.is_empty() {
            eprintln!("[omni_cli] stderr: {}", output.stderr);
        }
        if !output.status_success() {
            return Err(format!(
                "CLI exited with code {:?}: {}",
                output.status_code(),
                output.stderr
            ));
        }
        Ok(output.stdout)
    }

    fn run_captured_output(&self, cmd: &mut Command) -> Result<CliOutput, String> {
        cmd.current_dir(&self.omni_root);
        let plugins_dir = self.omni_root.join("omni-brain").join("plugins");
        if plugins_dir.exists() {
            cmd.env("PYTHONPATH", &plugins_dir);
        }
        run_command_with_timeout(cmd, self.timeout_secs)
    }
}

impl Default for PythonCliRunner {
    fn default() -> Self {
        Self::from_env()
    }
}

/// Backward compatibility: CliRunner is now an alias for PythonCliRunner.
pub use PythonCliRunner as CliRunner;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stop_handle_works() {
        let handle = StopHandle::new();
        assert!(!handle.is_stopped());
        handle.stop();
        assert!(handle.is_stopped());
    }

    #[test]
    fn with_lock_executes_closure_on_valid_lock() {
        let mutex = std::sync::Mutex::new(42);
        let mut result = 0;
        with_lock(&mutex, "test", |val| {
            result = *val;
        });
        assert_eq!(result, 42);
    }

    #[test]
    fn lock_clone_returns_cloned_value() {
        let mutex = std::sync::Mutex::new(vec![1, 2, 3]);
        let val = lock_clone(&mutex, "test");
        assert_eq!(val, vec![1, 2, 3]);
    }

    #[test]
    fn lock_clone_returns_default_on_poison() {
        let mutex = Arc::new(std::sync::Mutex::new(vec![1, 2, 3]));
        let mutex_clone = mutex.clone();
        let _ = std::panic::catch_unwind(move || {
            let _guard = mutex_clone.lock().unwrap();
            panic!("intentional panic to poison mutex");
        });
        assert!(mutex.is_poisoned());
        let val = lock_clone(&mutex, "test");
        assert_eq!(val, Vec::<i32>::default());
    }

    #[test]
    fn validate_tool_name_accepts_allowed() {
        assert_eq!(validate_tool_name("music_play", &["music_play", "music_pause"]), ToolValidation::Valid);
    }

    #[test]
    fn validate_tool_name_rejects_disallowed() {
        assert_eq!(validate_tool_name("rm_rf", &["music_play"]), ToolValidation::Invalid);
    }

    #[test]
    fn invalid_tool_envelope_has_correct_code() {
        let v = invalid_tool_envelope();
        assert_eq!(v["ok"], false);
        assert_eq!(v["error"]["code"], "E_INVALID_TOOL");
    }

    #[test]
    fn run_command_with_timeout_succeeds_for_fast_command() {
        if std::process::Command::new("echo").arg("test").output().is_err() {
            return;
        }
        let mut cmd = Command::new("echo");
        cmd.arg("hello");
        let out = run_command_with_timeout(&mut cmd, 5).unwrap();
        assert!(out.stdout.contains("hello"));
        assert!(out.status_success());
    }

    #[test]
    fn home_dir_returns_path_or_error() {
        let result = home_dir();
        if let Ok(path) = result {
            assert!(path.is_absolute(), "home_dir 应返回绝对路径");
        }
    }

    #[test]
    fn default_repo_root_returns_absolute_path() {
        let root = default_repo_root();
        assert!(root.is_absolute(), "default_repo_root 应返回绝对路径");
    }

    #[test]
    fn python_cli_runner_default_has_python3() {
        let runner = PythonCliRunner::from_env();
        assert_eq!(runner.python, PathBuf::from("python3"));
    }

    #[test]
    fn python_cli_runner_default_timeout_is_15() {
        let runner = PythonCliRunner::from_env();
        assert_eq!(runner.timeout_secs, 15);
    }

    #[test]
    fn python_cli_runner_with_timeout_changes_timeout() {
        let runner = PythonCliRunner::from_env().with_timeout(5);
        assert_eq!(runner.timeout_secs, 5);
    }

    #[test]
    fn cli_runner_alias_works() {
        let runner = CliRunner::from_env();
        assert_eq!(runner.python, PathBuf::from("python3"));
    }
}
