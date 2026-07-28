//! omni_voice 打断桥（M7.4 HUD 侧，接续 M7.5 Python 侧遗留）。
//!
//! 常驻语音管道跑在宿主进程内，HUD（Tauri 进程）无法直达——M7.5 落地的
//! 控制文件通道（`~/.ai-omni/state/voice-control.json`）是跨进程唯一反向
//! 通道。本模块的 `voice_interrupt` Tauri command 薄壳 spawn
//! `python3 -m omni_voice interrupt` CLI 写控制文件，沿用 utils.rs 的
//! `CliRunner` 模式；任何失败返回 Err 供前端 `interruptSpeaking()` 静默吞掉。
//!
//! 可靠性分层：CLI 退出码非零 / spawn 失败 / Python 缺失一律 Err——
//! 打断是「尽力而为」通道，失败时管道自身超时会自然迁态，不致命。

use crate::utils::CliRunner;
use serde_json::{json, Value};

/// 执行 `python -m omni_voice interrupt` 写控制文件；非零退出或 spawn 失败即 Err。
///
/// 抽成纯函数（无 tauri::State 依赖）便于 cargo test 直接覆盖；
/// `voice_interrupt` command 仅 spawn_blocking 包一层委托。
pub fn run_voice_interrupt(runner: &CliRunner) -> Result<(), String> {
    // CLI 输出本身不消费——只关心退出码；run_plugin_cli 已把非零退出映射为 Err。
    let _stdout = runner.run_plugin_cli("omni_voice", &["interrupt"])?;
    Ok(())
}

/// 打断宿主语音管道当前播报（M7.4 + M7.5）。
///
/// 前端经 `interruptSpeaking()` invoke；任何失败返回 Err，前端静默吞掉。
/// spawn_blocking 把子进程执行搬出 async 运行时，避免阻塞 IPC 线程。
#[tauri::command]
pub async fn voice_interrupt() -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(|| run_voice_interrupt(&CliRunner::from_env()))
        .await
        .map_err(|e| format!("voice_interrupt 任务 join 失败: {e}"))?
}

fn default_assistant_identity() -> Value {
    json!({
        "display_name": "雪莉",
        "english_name": "Sherry",
        "wake_aliases": ["雪莉", "sherry"],
        "wake_response": "我在",
        "idle_label": "雪莉 · 待命"
    })
}

fn fetch_assistant_identity(runner: &CliRunner) -> Value {
    match runner.call_json("voice", &["identity"]) {
        Ok(v) => {
            if let Some(data) = v.get("data").cloned() {
                if data.is_object() {
                    return data;
                }
            }
            default_assistant_identity()
        }
        Err(_) => default_assistant_identity(),
    }
}

#[tauri::command]
pub fn get_assistant_identity() -> Value {
    let runner = CliRunner::from_env().with_timeout(5);
    let data = fetch_assistant_identity(&runner);
    json!({
        "ok": true,
        "data": data
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::status::default_repo_root;

    // ---- run_voice_interrupt（纯函数：CLI 桥 spawn 逻辑） -------------------

    #[test]
    fn run_voice_interrupt_propagates_spawn_error_for_missing_interpreter() {
        let runner = CliRunner {
            python: "definitely-not-a-python-binary".into(),
            omni_root: default_repo_root(),
            ..CliRunner::default()
        };
        let err = run_voice_interrupt(&runner).unwrap_err();
        assert!(
            err.contains("启动") || err.contains("omni_voice"),
            "spawn 失败信息应包含上下文: {err}"
        );
    }

    #[test]
    fn run_voice_interrupt_roundtrip_when_python_available() {
        // 环境静默跳过：无 python3 的开发机不强制（spawn 逻辑已由缺失解释器测试覆盖）。
        if std::process::Command::new("python3")
            .arg("--version")
            .output()
            .is_err()
        {
            return;
        }
        let runner = CliRunner::from_env();
        // 真实 CLI 写真实控制文件 ~/.ai-omni/state/voice-control.json；
        // M7.5 CLI 真机冒烟已验证 schema 正确，这里只锚定 spawn 退出码 0。
        run_voice_interrupt(&runner).expect("omni_voice interrupt 应能执行（退出码 0）");
    }

    // ---- default_assistant_identity（默认身份） ------------------------------

    #[test]
    fn default_identity_has_correct_name() {
        let identity = default_assistant_identity();
        assert_eq!(identity["display_name"], "雪莉");
        assert_eq!(identity["english_name"], "Sherry");
    }

    #[test]
    fn default_identity_wake_aliases_include_xueli_not_weinasi() {
        let identity = default_assistant_identity();
        let aliases = identity["wake_aliases"].as_array().unwrap();
        let alias_strs: Vec<&str> = aliases.iter().filter_map(|v| v.as_str()).collect();
        assert!(alias_strs.contains(&"雪莉"), "唤醒别名应包含\"雪莉\"");
        assert!(alias_strs.contains(&"sherry"), "唤醒别名应包含\"sherry\"");
        assert!(!alias_strs.iter().any(|a| a.contains("维纳斯")), "唤醒别名不应包含\"维纳斯\"");
    }

    #[test]
    fn default_identity_has_correct_idle_label() {
        let identity = default_assistant_identity();
        assert_eq!(identity["idle_label"], "雪莉 · 待命");
    }

    #[test]
    fn default_identity_has_wake_response() {
        let identity = default_assistant_identity();
        assert_eq!(identity["wake_response"], "我在");
    }

    #[test]
    fn fetch_identity_returns_default_on_cli_failure() {
        let runner = CliRunner {
            python: "definitely-not-a-python-binary".into(),
            omni_root: default_repo_root(),
            ..CliRunner::default()
        };
        let identity = fetch_assistant_identity(&runner);
        assert_eq!(identity["display_name"], "雪莉");
    }
}
