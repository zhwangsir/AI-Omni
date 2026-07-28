//! 状态轮询：语音、智能家居、系统资源（电量/CPU/内存/磁盘/网络）。
//!
//! 三种采集源：
//! 1. Python CLI：`omni_cli.py voice status` / `home summary`（已有成熟逻辑与状态文件
//!    回退，不在 Rust 里重写）；
//! 2. 文件轮询：`state/voice-state.json`（独立 watcher 见 `voice_watch.rs`，这里不重复读）；
//! 3. 原生 sysinfo：CPU/内存/磁盘/网络，走 `sysinfo` crate 本地采集，无 Python 依赖。
//!
//! Tauri command 统一返回信封：成功 `{ok:true,...}`；失败 `{ok:false,error:{code,message}}`。
//! CLI 调用失败不 reject，返回 ok=false 信封（前端容错显示，不崩整个 HUD）。

use std::sync::{Arc, Mutex};

use serde_json::{json, Value};
use sysinfo::{CpuRefreshKind, Disks, MemoryRefreshKind, Networks, RefreshKind, System};

use crate::utils;

const CLI_TIMEOUT_SECS: u64 = 5;

fn error_envelope(code: &str, message: &str) -> Value {
    json!({"ok": false, "error": {"code": code, "message": message}})
}

/// Re-exports for backward compatibility.
pub use utils::{default_repo_root, CliRunner};

fn run_python_cli(module: &str, args: &[&str]) -> Result<Value, String> {
    let runner = CliRunner::from_env().with_timeout(CLI_TIMEOUT_SECS);
    let stdout = runner.run_plugin_cli_capture(module, args)?;
    serde_json::from_str(stdout.trim())
        .map_err(|e| format!("CLI {module} JSON 解析失败: {e}"))
}

/// 系统资源采集器：持有 sysinfo::System 实例，每次调用 refresh() 增量刷新。
///
/// 通过 `tauri::State<Arc<Mutex<SystemMonitor>>>` 注入 command，避免每个请求重新扫描
/// 进程列表（sysinfo 首次扫描成本高）。
pub struct SystemMonitor {
    sys: System,
}

impl SystemMonitor {
    pub fn new() -> Self {
        Self {
            sys: System::new_with_specifics(
                RefreshKind::new()
                    .with_cpu(CpuRefreshKind::new().with_cpu_usage())
                    .with_memory(MemoryRefreshKind::new().with_ram()),
            ),
        }
    }

    fn collect(&mut self) -> Value {
        self.sys.refresh_cpu();
        self.sys.refresh_memory();

        let cpu_usage = if self.sys.cpus().is_empty() {
            0.0
        } else {
            let sum: f32 = self.sys.cpus().iter().map(|c| c.cpu_usage()).sum();
            sum / self.sys.cpus().len() as f32
        };

        let memory_total = self.sys.total_memory();
        let memory_used = self.sys.used_memory();
        let memory_available = self.sys.available_memory();

        let disks = Disks::new_with_refreshed_list();
        let disk_total: u64 = disks.iter().map(|d| d.total_space()).sum();
        let disk_available: u64 = disks.iter().map(|d| d.available_space()).sum();

        let networks = Networks::new_with_refreshed_list();
        let mut net_rx_bytes: u64 = 0;
        let mut net_tx_bytes: u64 = 0;
        for net in networks.iter() {
            net_rx_bytes += net.1.received();
            net_tx_bytes += net.1.transmitted();
        }

        let battery_life = json!(null);

        json!({
            "available": true,
            "cpuUsagePercent": f64::from(cpu_usage),
            "memoryTotalBytes": memory_total,
            "memoryUsedBytes": memory_used,
            "memoryAvailableBytes": memory_available,
            "diskTotalBytes": disk_total,
            "diskAvailableBytes": disk_available,
            "netRxBytes": net_rx_bytes,
            "netTxBytes": net_tx_bytes,
            "battery": battery_life,
        })
    }
}

impl Default for SystemMonitor {
    fn default() -> Self {
        Self::new()
    }
}

fn call_cli(module: &str, tool: &str) -> Value {
    match run_python_cli(module, &[tool]) {
        Ok(v) => v,
        Err(e) => error_envelope("E_CLI_UNAVAILABLE", &e),
    }
}

#[tauri::command]
pub fn get_voice_status() -> Value {
    call_cli("omni_voice", "status")
}

#[tauri::command]
pub fn get_home_summary() -> Value {
    call_cli("omni_home", "status")
}

#[tauri::command]
pub fn get_system_stats(state: tauri::State<'_, Arc<Mutex<SystemMonitor>>>) -> Value {
    let mut result = SystemMonitor::new().collect();
    utils::with_lock(&state, "system_monitor", |monitor| {
        result = monitor.collect();
    });
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn error_envelope_has_correct_shape() {
        let v = error_envelope("E_TEST", "hello");
        assert_eq!(v["ok"], false);
        assert_eq!(v["error"]["code"], "E_TEST");
        assert_eq!(v["error"]["message"], "hello");
    }

    #[test]
    fn system_monitor_collects_valid_stats() {
        let mut m = SystemMonitor::new();
        let v = m.collect();
        assert_eq!(v["available"], true);
        assert!(v["memoryTotalBytes"].as_u64().unwrap() > 0);
        assert!(v["memoryAvailableBytes"].as_u64().unwrap() > 0);
    }

    #[test]
    fn system_monitor_default_and_new_are_equivalent() {
        let m1 = SystemMonitor::default();
        let m2 = SystemMonitor::new();
        assert_eq!(m1.sys.total_memory(), m2.sys.total_memory());
        assert_eq!(m1.sys.cpus().len(), m2.sys.cpus().len());
    }

    #[test]
    fn cli_runner_default_has_python3() {
        let runner = CliRunner::from_env();
        assert_eq!(runner.python, PathBuf::from("python3"));
    }

    #[test]
    fn cli_runner_sets_pythonpath_to_plugins_dir() {
        let runner = CliRunner::from_env();
        let plugins_dir = runner.omni_root.join("omni-brain").join("plugins");
        assert!(
            plugins_dir.exists(),
            "plugins_dir should exist: {:?}",
            plugins_dir
        );
        let result = runner.run_plugin_cli("omni_voice", &["--help"]);
        assert!(result.is_ok(), "omni_voice --help should succeed: {:?}", result.err());
    }

    #[test]
    fn cli_timeout_is_5_seconds() {
        assert_eq!(CLI_TIMEOUT_SECS, 5);
    }
}
