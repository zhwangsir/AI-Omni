//! omni_music CLI 桥接（M17.10 前端 ↔ Python omni_music 工具）。
//!
//! 单个 Tauri command ``music_tool``：
//! - 前端 ``invoke('music_tool', {tool, args})`` → Rust 校验工具名白名单 → 调
//!   ``python3 -m omni_music call <tool> --args '<json>'``
//! - Python CLI 调用 omni_music tools 层（tools 层经 state_file 持久化队列/状态，
//!   跨 CLI 调用串联有状态播放），stdout 返回 ``{"ok":true,"data":...}`` 信封
//! - Rust 解析 stdout 为 ``serde_json::Value`` 透传给前端；任何失败降级为
//!   ``{"ok":false,"error":{"code":"E_CLI_FAILED",...}}``，前端呈现离线态而非报错
//!
//! 设计参考 ``status.rs`` 的 ``CliRunner`` 子进程桥模式（omni_voice/omni_home 同款）。
//! 跨 CLI 调用的状态持久化由 Python 侧 ``load_player_from_state_file`` +
//! ``_write_state_file`` 经 ``~/.ai-omni/state/music_state.json`` 完成。

use serde_json::Value;

use crate::status::CliRunner;
use crate::utils::{self, ToolValidation};

/// omni_music 允许的工具名白名单（IPC 参数校验 P1-6）。
const ALLOWED_MUSIC_TOOLS: &[&str] = &[
    "music_play",
    "music_pause",
    "music_next",
    "music_previous",
    "music_toggle",
    "music_get_player_state",
    "music_set_volume",
    "music_seek",
    "music_library_scan",
    "music_library_search",
    "music_library_status",
    "music_playlist_create",
    "music_playlist_list",
    "music_playlist_add",
    "music_decrypt_file",
];

/// 解析 omni_music CLI stdout 为 ``Value``；非 JSON / 空串降级为错误信封。
///
/// CLI 输出已是 ``{"ok":true,"data":...}`` / ``{"ok":false,"error":...}`` 信封，
/// Rust 侧原样透传为 ``Value``，前端 ``musicStore`` 负责 ``normalize_*`` 归一。
pub fn parse_music_result(stdout: &str) -> Value {
    let trimmed = stdout.trim();
    if trimmed.is_empty() {
        return error_envelope("E_CLI_EMPTY", "omni_music CLI 无输出");
    }
    match serde_json::from_str::<Value>(trimmed) {
        Ok(v) if v.is_object() => v,
        Ok(_) => error_envelope("E_CLI_SHAPE", "omni_music CLI 输出非 JSON 对象"),
        Err(e) => error_envelope("E_CLI_PARSE", &format!("omni_music CLI 输出解析失败: {e}")),
    }
}

/// 构造错误信封（与 Python ``_err`` 同构）。
fn error_envelope(code: &str, message: &str) -> Value {
    serde_json::json!({
        "ok": false,
        "error": { "code": code, "message": message }
    })
}

/// 执行 ``python3 -m omni_music call <tool> --args <json>`` 并解析 stdout。
///
/// ``args`` 为 ``null`` / 缺省时传 ``{}``。任何子进程失败降级为错误信封。
///
/// 使用 :meth:`CliRunner::run_plugin_cli_capture` 而非 :meth:`run_plugin_cli`，
/// 因为 omni_music CLI 在工具返回 ``{"ok": false, ...}`` 错误信封时以退出码 1
/// 退出，但 stdout 仍携带可解析的 JSON 信封——需要捕获 stdout 无论退出码如何。
pub fn fetch_music_tool(runner: &CliRunner, tool: &str, args: &Value) -> Value {
    if utils::validate_tool_name(tool, ALLOWED_MUSIC_TOOLS) == ToolValidation::Invalid {
        return utils::invalid_tool_envelope();
    }
    let args_json = if args.is_null() {
        "{}".to_owned()
    } else {
        serde_json::to_string(args).unwrap_or_else(|_| "{}".to_owned())
    };
    match runner.run_plugin_cli_capture("omni_music", &["call", tool, "--args", &args_json]) {
        Ok(stdout) => parse_music_result(&stdout),
        Err(e) => error_envelope("E_CLI_FAILED", &format!("omni_music CLI 不可用: {e}")),
    }
}

/// 前端 ↔ Python omni_music 工具桥接 command。
///
/// 前端调用：``invoke('music_tool', { tool: 'music_play', args: { song_id: '...' } })``
/// 返回值：Python 工具的 JSON 信封（``{"ok":true,"data":...}``）原样透传。
#[tauri::command]
pub async fn music_tool(tool: String, args: Option<Value>) -> Value {
    let args = args.unwrap_or(Value::Null);
    tauri::async_runtime::spawn_blocking(move || {
        let runner = CliRunner::from_env();
        fetch_music_tool(&runner, &tool, &args)
    })
    .await
    .unwrap_or_else(|_| error_envelope("E_CLI_TIMEOUT", "omni_music CLI 执行超时"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_ok_envelope_passes_through() {
        let stdout = r#"{"ok":true,"data":{"songs":[],"count":0}}"#;
        let v = parse_music_result(stdout);
        assert_eq!(v["ok"], true);
        assert_eq!(v["data"]["count"], 0);
    }

    #[test]
    fn parse_error_envelope_passes_through() {
        let stdout = r#"{"ok":false,"error":{"code":"E_INVALID_ARGS","message":"x"}}"#;
        let v = parse_music_result(stdout);
        assert_eq!(v["ok"], false);
        assert_eq!(v["error"]["code"], "E_INVALID_ARGS");
    }

    #[test]
    fn parse_empty_stdout_becomes_error_envelope() {
        let v = parse_music_result("");
        assert_eq!(v["ok"], false);
        assert_eq!(v["error"]["code"], "E_CLI_EMPTY");
    }

    #[test]
    fn parse_whitespace_only_stdout_becomes_error_envelope() {
        let v = parse_music_result("   \n  ");
        assert_eq!(v["error"]["code"], "E_CLI_EMPTY");
    }

    #[test]
    fn parse_non_json_stdout_becomes_error_envelope() {
        let v = parse_music_result("not json at all");
        assert_eq!(v["error"]["code"], "E_CLI_PARSE");
    }

    #[test]
    fn parse_non_object_json_becomes_error_envelope() {
        let v = parse_music_result("[1,2,3]");
        assert_eq!(v["error"]["code"], "E_CLI_SHAPE");
        let v = parse_music_result("42");
        assert_eq!(v["error"]["code"], "E_CLI_SHAPE");
    }

    #[test]
    fn error_envelope_shape_matches_python() {
        let v = error_envelope("E_X", "msg");
        assert_eq!(v["ok"], false);
        assert_eq!(v["error"]["code"], "E_X");
        assert_eq!(v["error"]["message"], "msg");
    }

    #[test]
    fn fetch_music_tool_rejects_invalid_tool_name() {
        let runner = CliRunner {
            python: "echo".into(),
            omni_root: crate::status::default_repo_root(),
            ..CliRunner::default()
        };
        let v = fetch_music_tool(&runner, "rm_rf_slash", &serde_json::json!({}));
        assert_eq!(v["ok"], false);
        assert_eq!(v["error"]["code"], "E_INVALID_TOOL");
    }

    #[test]
    fn fetch_music_tool_accepts_whitelisted_tool_names() {
        for tool in ["music_play", "music_pause", "music_get_player_state", "music_library_scan"] {
            assert_eq!(
                utils::validate_tool_name(tool, ALLOWED_MUSIC_TOOLS),
                ToolValidation::Valid,
                "{tool} 应在白名单内"
            );
        }
    }

    #[test]
    fn fetch_music_tool_propagates_cli_failure_as_error_envelope() {
        let runner = CliRunner {
            python: "definitely-not-a-python-binary".into(),
            omni_root: crate::status::default_repo_root(),
            ..CliRunner::default()
        };
        let v = fetch_music_tool(&runner, "music_play", &serde_json::json!({"fake": true}));
        assert_eq!(v["ok"], false);
        assert!(v["error"]["code"] == "E_CLI_FAILED" || v["error"]["code"] == "E_INVALID_TOOL");
    }

    #[test]
    fn fetch_music_tool_roundtrip_when_python_available() {
        if std::process::Command::new("python3")
            .arg("--version")
            .output()
            .is_err()
        {
            return;
        }
        let runner = CliRunner::from_env();
        let v = fetch_music_tool(
            &runner,
            "music_get_player_state",
            &serde_json::json!({"fake": true}),
        );
        assert!(
            v["ok"] == true || v["error"]["code"] == "E_CLI_FAILED",
            "真实 CLI 应返回 ok 信封或 E_CLI_FAILED（未安装时）: {v}"
        );
    }
}
