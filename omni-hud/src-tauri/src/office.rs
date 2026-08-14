//! omni_office CLI 桥接（M34 前端 ↔ Python omni_office 工具）。
//!
//! 单个 Tauri command ``office_tool``：
//! - 前端 ``invoke('office_tool', {tool, args})`` → Rust 校验工具名白名单 → 调
//!   ``python3 -m omni_office call <tool> --args '<json>'``
//! - Python CLI 调用 omni_office tools 层（文档版本 / 邮件 / 日程 / 会议准备工作流），
//!   stdout 返回 ``{"ok":true,"data":...}`` 信封
//! - Rust 解析 stdout 为 ``serde_json::Value`` 透传给前端；任何失败降级为
//!   ``{"ok":false,"error":{"code":"E_CLI_FAILED",...}}``，前端呈现离线态而非报错
//!
//! 设计参考 ``weather.rs`` / ``lyrics.rs`` 的 ``CliRunner`` 子进程桥模式。
//! 与 M33 desktop.rs 桌面自动化 command 正交：office_* 走 CLI 桥，
//! desktop_* 走真机键鼠，二者在前端工作流层组合（如会议准备后自动打开纪要文档）。

use serde_json::Value;

use crate::status::CliRunner;
use crate::utils::{self, ToolValidation};

/// omni_office 允许的工具名白名单（IPC 参数校验，与 manifest.json tools 对齐）。
const ALLOWED_OFFICE_TOOLS: &[&str] = &[
    "office_doc_create",
    "office_doc_update",
    "office_doc_get",
    "office_doc_list",
    "office_doc_versions",
    "office_doc_rollback",
    "office_email_send",
    "office_email_inbox",
    "office_email_mark_read",
    "office_email_template_save",
    "office_email_template_list",
    "office_email_auto_reply",
    "office_email_process_inbox",
    "office_event_create",
    "office_event_list",
    "office_event_reminders",
    "office_event_check_conflicts",
    "office_meeting_prep",
    "office_status",
];

/// 解析 omni_office CLI stdout 为 ``Value``；非 JSON / 空串降级为错误信封。
///
/// CLI 输出已是 ``{"ok":true,"data":...}`` / ``{"ok":false,"error":...}`` 信封，
/// Rust 侧原样透传为 ``Value``。
pub fn parse_office_result(stdout: &str) -> Value {
    let trimmed = stdout.trim();
    if trimmed.is_empty() {
        return error_envelope("E_CLI_EMPTY", "omni_office CLI 无输出");
    }
    match serde_json::from_str::<Value>(trimmed) {
        Ok(v) if v.is_object() => v,
        Ok(_) => error_envelope("E_CLI_SHAPE", "omni_office CLI 输出非 JSON 对象"),
        Err(e) => error_envelope("E_CLI_PARSE", &format!("omni_office CLI 输出解析失败: {e}")),
    }
}

/// 构造错误信封（与 Python ``_err`` 同构）。
fn error_envelope(code: &str, message: &str) -> Value {
    serde_json::json!({
        "ok": false,
        "error": { "code": code, "message": message }
    })
}

/// 执行 ``python3 -m omni_office call <tool> --args <json>`` 并解析 stdout。
///
/// ``args`` 为 ``null`` / 缺省时传 ``{}``。任何子进程失败降级为错误信封。
/// 使用 :meth:`CliRunner::run_plugin_cli_capture`：CLI 返回错误信封时以退出码 1
/// 退出，但 stdout 仍携带可解析的 JSON 信封——需要捕获 stdout 无论退出码如何。
pub fn fetch_office_tool(runner: &CliRunner, tool: &str, args: &Value) -> Value {
    if utils::validate_tool_name(tool, ALLOWED_OFFICE_TOOLS) == ToolValidation::Invalid {
        return utils::invalid_tool_envelope();
    }
    let args_json = if args.is_null() {
        "{}".to_owned()
    } else {
        serde_json::to_string(args).unwrap_or_else(|_| "{}".to_owned())
    };
    match runner.run_plugin_cli_capture("omni_office", &["call", tool, "--args", &args_json]) {
        Ok(stdout) => parse_office_result(&stdout),
        Err(e) => error_envelope("E_CLI_FAILED", &format!("omni_office CLI 不可用: {e}")),
    }
}

/// 前端 ↔ Python omni_office 工具桥接 command。
///
/// 前端调用：``invoke('office_tool', { tool: 'office_doc_list', args: {} })``
/// 返回值：Python 工具的 JSON 信封（``{"ok":true,"data":...}``）原样透传。
#[tauri::command]
pub async fn office_tool(tool: String, args: Option<Value>) -> Value {
    let args = args.unwrap_or(Value::Null);
    tauri::async_runtime::spawn_blocking(move || {
        let runner = CliRunner::from_env();
        fetch_office_tool(&runner, &tool, &args)
    })
    .await
    .unwrap_or_else(|_| error_envelope("E_CLI_TIMEOUT", "omni_office CLI 执行超时"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_ok_envelope_passes_through() {
        let stdout = r##"{"ok":true,"data":{"doc_id":"doc_abc123"}}"##;
        let v = parse_office_result(stdout);
        assert_eq!(v["ok"], true);
        assert_eq!(v["data"]["doc_id"], "doc_abc123");
    }

    #[test]
    fn parse_error_envelope_passes_through() {
        let stdout = r#"{"ok":false,"error":{"code":"E_EVENT_CONFLICT","message":"日程冲突"}}"#;
        let v = parse_office_result(stdout);
        assert_eq!(v["ok"], false);
        assert_eq!(v["error"]["code"], "E_EVENT_CONFLICT");
    }

    #[test]
    fn parse_empty_stdout_becomes_error_envelope() {
        let v = parse_office_result("");
        assert_eq!(v["ok"], false);
        assert_eq!(v["error"]["code"], "E_CLI_EMPTY");
    }

    #[test]
    fn parse_non_json_stdout_becomes_error_envelope() {
        let v = parse_office_result("not json");
        assert_eq!(v["error"]["code"], "E_CLI_PARSE");
    }

    #[test]
    fn parse_non_object_json_becomes_error_envelope() {
        let v = parse_office_result("[1,2,3]");
        assert_eq!(v["error"]["code"], "E_CLI_SHAPE");
        let v = parse_office_result("null");
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
    fn fetch_office_tool_rejects_invalid_tool_name() {
        let runner = CliRunner {
            python: "echo".into(),
            omni_root: crate::status::default_repo_root(),
            ..CliRunner::default()
        };
        let v = fetch_office_tool(&runner, "steal_password", &serde_json::json!({}));
        assert_eq!(v["ok"], false);
        assert_eq!(v["error"]["code"], "E_INVALID_TOOL");
    }

    #[test]
    fn fetch_office_tool_accepts_whitelisted_tool_names() {
        for tool in [
            "office_doc_create",
            "office_email_send",
            "office_event_create",
            "office_meeting_prep",
            "office_status",
        ] {
            assert_eq!(
                utils::validate_tool_name(tool, ALLOWED_OFFICE_TOOLS),
                ToolValidation::Valid,
                "{tool} 应在白名单内"
            );
        }
    }

    #[test]
    fn whitelist_covers_all_19_manifest_tools() {
        assert_eq!(ALLOWED_OFFICE_TOOLS.len(), 19, "白名单必须与 manifest.tools 数量一致");
    }

    #[test]
    fn fetch_office_tool_propagates_cli_failure_as_error_envelope() {
        let runner = CliRunner {
            python: "definitely-not-a-python-binary".into(),
            omni_root: crate::status::default_repo_root(),
            ..CliRunner::default()
        };
        let v = fetch_office_tool(&runner, "office_status", &serde_json::json!({}));
        assert_eq!(v["ok"], false);
        assert!(v["error"]["code"] == "E_CLI_FAILED" || v["error"]["code"] == "E_INVALID_TOOL");
    }
}
