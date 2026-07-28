//! 语音状态文件监听（M5.4 W1 数据通道重构）。
//!
//! omni_voice 宿主管道把每次状态迁移原子写入
//! `~/.ai-omni/state/voice-status.json`（tmp + os.replace，见 Python 侧
//! `state_file.py`）。本模块在 Tauri setup 期挂一个 notify watcher 监听
//! 状态文件**所在目录**（原子替换会换 inode，监听目录而非文件本身），
//! 文件变化时重读、解析、去抖（负载相等不重复推送），经 Tauri event
//! `voice-status` 推送前端。
//!
//! 可靠性分层：
//! - watcher 启动失败 / 文件缺失 / 解析失败 → 推送 `available:false` 或静默，
//!   前端保留 CLI 轮询兜底（双通道共存），本模块任何失败不致命；
//! - 运行期逻辑全部抽成纯函数与注入式循环（`run_watch_loop` 的读取函数与
//!   事件通道均为参数），`cargo test` 不起真实 watcher 线程即可覆盖。

use std::path::{Path, PathBuf};
use std::sync::mpsc::Receiver;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::utils;

/// 前端订阅的 Tauri event 名（与 src/data/sources.ts VOICE_STATUS_EVENT 对齐）。
pub const VOICE_STATUS_EVENT: &str = "voice-status";

/// 已知管道状态（用于状态归一）。
pub const KNOWN_PIPELINE_STATES: &[&str] = &[
    "idle",
    "wake_listening",
    "recording",
    "transcribing",
    "thinking",
    "speaking",
    "tool_using",
    "follow_up_listening",
];

/// 80ms 事件去抖窗口（P1-7）。
const DEBOUNCE_WINDOW_MS: u64 = 80;

/// 工具调用状态快照（M13.2 Agent 可视化）。
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ToolCallPayload {
    pub id: String,
    #[serde(rename = "toolName")]
    pub tool_name: String,
    pub params: Value,
    pub result: Option<String>,
    pub status: String,
    pub timestamp: f64,
}

/// 语音状态负载（推送给前端的结构）。
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VoiceStatusPayload {
    pub available: bool,
    pub state: Option<String>,
    pub running: bool,
    pub fake_mode: bool,
    pub reply: Option<String>,
    pub reply_seq: Option<u64>,
    pub window_mode: Option<String>,
    pub tool_calls: Option<Vec<ToolCallPayload>>,
}

impl VoiceStatusPayload {
    /// 文件不可用/缺失时的降级负载。
    pub fn unavailable() -> Self {
        Self {
            available: false,
            state: None,
            running: false,
            fake_mode: false,
            reply: None,
            reply_seq: None,
            window_mode: None,
            tool_calls: None,
        }
    }
}

/// 从 JSON 解析单个 tool_call 元素（非法元素返回 None，由上层过滤）。
pub fn parse_tool_call(v: &Value) -> Option<ToolCallPayload> {
    let obj = v.as_object()?;
    let id = obj.get("id")?.as_str()?;
    let name = obj.get("name")?.as_str()?;
    let args = obj.get("args")?.as_object()?;
    let status = obj.get("status")?.as_str()?;
    let ts = obj.get("ts")?.as_f64()?;
    if !matches!(status, "pending" | "success" | "error") {
        return None;
    }
    Some(ToolCallPayload {
        id: id.to_owned(),
        tool_name: name.to_owned(),
        params: Value::Object(args.clone()),
        result: obj.get("result").and_then(Value::as_str).map(str::to_owned),
        status: status.to_owned(),
        timestamp: ts,
    })
}

/// 默认状态文件路径：`~/.ai-omni/state/voice-status.json`（与 Python 侧一致）。
///
/// P1-8：home_dir() 失败时返回 Err，而非静默降级到 "."。
pub fn default_state_file_path() -> Result<PathBuf, String> {
    utils::home_dir()
        .map(|home| {
            home.join(".ai-omni")
                .join("state")
                .join("voice-status.json")
        })
}

/// 解析状态文件内容为语音负载；缺失/损坏/schema 不符一律返回 None。
///
/// schema 与 Python 侧对齐：state 非空字符串、running/fake_mode 布尔、ts 数值；
/// state 无法识别时归为 None 但整体仍 available（与 parse_voice_status 同语义）。
pub fn parse_voice_state_file(content: &str) -> Option<VoiceStatusPayload> {
    let root: Value = serde_json::from_str(content.trim()).ok()?;
    let state = root.get("state")?.as_str()?;
    if state.is_empty() {
        return None;
    }
    let running = root.get("running")?.as_bool()?;
    let fake_mode = root.get("fake_mode")?.as_bool()?;
    // ts 必须是数值（as_f64 兼容 int/float，布尔返回 None）；
    // 当前不消费但 schema 强校验，为后续「过期判断」保留事实来源。
    root.get("ts")?.as_f64()?;
    // M6.3：reply 为可选字段——仅当字符串时透传，缺省/非字符串归 None，
    // M5.4 旧格式文件（无 reply 键）零改动兼容。
    let reply = root.get("reply").and_then(Value::as_str).map(str::to_owned);
    // reply_seq（轮次序号）同理：仅非负整数透传，缺省/非法归 None。
    let reply_seq = root.get("reply_seq").and_then(Value::as_u64);
    // M12：window_mode 为可选字段——仅当字符串时透传，缺省/非字符串归 None，
    // M12 之前旧格式文件（无 window_mode 键）零改动兼容（前端按 Full 缺省）。
    let window_mode = root
        .get("window_mode")
        .and_then(Value::as_str)
        .map(str::to_owned);
    // M13.2：tool_calls 为可选字段——仅当数组时透传（含空数组，表示本轮已结束）；
    // 每个元素经 parse_tool_call 解析，非法元素被过滤。非数组归 None（与旧格式兼容）。
    let tool_calls = root.get("tool_calls").and_then(Value::as_array).map(|arr| {
        arr.iter()
            .filter_map(parse_tool_call)
            .collect::<Vec<_>>()
    });
    Some(VoiceStatusPayload {
        available: true,
        state: KNOWN_PIPELINE_STATES
            .contains(&state)
            .then(|| state.to_owned()),
        running,
        fake_mode,
        reply,
        reply_seq,
        window_mode,
        tool_calls,
    })
}

/// 读取并解析状态文件；文件不可读或解析失败返回 None（调用方降级）。
pub fn read_state_file(path: &Path) -> Option<VoiceStatusPayload> {
    let content = std::fs::read_to_string(path).ok()?;
    parse_voice_state_file(&content)
}

/// 事件过滤：notify 事件是否触碰目标状态文件（rename 事件含目标路径即算）。
pub fn event_touches_path(event: &notify::Event, target: &Path) -> bool {
    event.paths.iter().any(|p| p == target)
}

/// 去抖/变更检测：与上次已推送负载比对，仅在语义变化时返回待推送副本。
///
/// `current` 为 None 表示文件缺失/损坏 → 归一为 unavailable 负载参与比对；
/// 首次调用（last 为 None）一律放行，保证启动即有一次初始同步。
pub fn detect_change(
    last: &Option<VoiceStatusPayload>,
    current: Option<VoiceStatusPayload>,
) -> Option<VoiceStatusPayload> {
    let candidate = current.unwrap_or_else(VoiceStatusPayload::unavailable);
    if last.as_ref() == Some(&candidate) {
        None
    } else {
        Some(candidate)
    }
}

/// 监听主循环（注入式，可单测）：启动先做一次初始同步，之后触碰目标文件的
/// 事件经 **80ms 去抖窗口** 合并（短时间内多次事件只处理最后一次，P1-7），
/// 再经 `detect_change` 语义去抖后调用 `emit` 推送；事件通道断开即退出。
///
/// - `read` 为文件读取函数（生产注入 `read_state_file`，测试注入脚本化假数据）；
/// - 通道里的 notify 错误事件直接跳过，不视为致命。
pub fn run_watch_loop(
    path: &Path,
    rx: &Receiver<notify::Result<notify::Event>>,
    read: &dyn Fn(&Path) -> Option<VoiceStatusPayload>,
    emit: &mut dyn FnMut(VoiceStatusPayload),
) {
    let mut last: Option<VoiceStatusPayload> = None;
    // 启动初始同步：管道可能已在运行，先推一帧当前快照。
    if let Some(payload) = detect_change(&last, read(path)) {
        emit(payload.clone());
        last = Some(payload);
    }

    let debounce_window = Duration::from_millis(DEBOUNCE_WINDOW_MS);
    // 去抖状态：None 表示空闲等待中；Some(instant) 表示自上次事件以来已累计等待
    let mut last_event_time: Option<std::time::Instant> = None;

    loop {
        let recv_result = match last_event_time {
            Some(t) => {
                let elapsed = t.elapsed();
                if elapsed >= debounce_window {
                    // 去抖窗口已过，处理事件
                    if let Some(payload) = detect_change(&last, read(path)) {
                        emit(payload.clone());
                        last = Some(payload);
                    }
                    last_event_time = None;
                    continue;
                }
                // 等待剩余窗口时间
                rx.recv_timeout(debounce_window - elapsed)
            }
            None => rx.recv().map_err(|_| std::sync::mpsc::RecvTimeoutError::Disconnected),
        };

        match recv_result {
            Ok(Ok(event)) => {
                if event_touches_path(&event, path) {
                    // 新事件到来：重置计时器（从现在起再等 80ms）
                    last_event_time = Some(std::time::Instant::now());
                }
            }
            Ok(Err(_notify_err)) => {
                // notify 错误事件，跳过
            }
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                // recv_timeout 返回 Timeout 表示去抖窗口已到，下次循环会处理
                // （因为 last_event_time.elapsed() >= debounce_window）
            }
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
                // 通道断开，退出前处理最后一次 pending 事件
                if last_event_time.is_some() {
                    if let Some(payload) = detect_change(&last, read(path)) {
                        emit(payload.clone());
                    }
                }
                break;
            }
        }
    }
}

/// 启动状态文件监听（setup 期调用一次）。
///
/// 成功：后台线程持有 watcher，状态变化经 `voice-status` 事件推送前端。
/// 失败：返回 Err，调用方静默降级——voice 通道保留 CLI 轮询兜底。
pub fn start_voice_watcher<R: tauri::Runtime>(
    app: &tauri::AppHandle<R>,
    path: PathBuf,
) -> Result<(), String> {
    use notify::{RecursiveMode, Watcher as _};
    use tauri::Emitter as _;

    let (tx, rx) = std::sync::mpsc::channel();
    let mut watcher =
        notify::recommended_watcher(tx).map_err(|e| format!("创建 notify watcher 失败: {e}"))?;
    let dir = path
        .parent()
        .ok_or_else(|| "状态文件路径无父目录".to_owned())?
        .to_path_buf();
    // 管道首次写文件前目录可能不存在，先建目录保证 watch 可挂载。
    std::fs::create_dir_all(&dir).map_err(|e| format!("创建状态目录失败: {e}"))?;
    watcher
        .watch(&dir, RecursiveMode::NonRecursive)
        .map_err(|e| format!("监听 {} 失败: {e}", dir.display()))?;

    let handle = app.clone();
    std::thread::Builder::new()
        .name("omni-voice-watch".to_owned())
        .spawn(move || {
            // watcher 移入线程保活：析构即停 watch 并断开通道、循环退出。
            let _watcher = watcher;
            run_watch_loop(&path, &rx, &read_state_file, &mut |payload| {
                let _ = handle.emit(VOICE_STATUS_EVENT, payload);
            });
        })
        .map_err(|e| format!("启动 watcher 线程失败: {e}"))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use notify::event::{CreateKind, DataChange, ModifyKind, RenameMode};
    use notify::{Event, EventKind};
    use std::collections::VecDeque;
    use std::sync::mpsc::channel;

    fn payload(state: Option<&str>, running: bool, fake: bool) -> VoiceStatusPayload {
        VoiceStatusPayload {
            available: true,
            state: state.map(str::to_owned),
            running,
            fake_mode: fake,
            reply: None,
            reply_seq: None,
            window_mode: None,
            tool_calls: None,
        }
    }

    fn payload_with_reply(
        state: Option<&str>,
        running: bool,
        fake: bool,
        reply: &str,
    ) -> VoiceStatusPayload {
        VoiceStatusPayload {
            available: true,
            state: state.map(str::to_owned),
            running,
            fake_mode: fake,
            reply: Some(reply.to_owned()),
            reply_seq: None,
            window_mode: None,
            tool_calls: None,
        }
    }

    fn payload_with_reply_seq(
        state: Option<&str>,
        running: bool,
        fake: bool,
        reply: &str,
        reply_seq: u64,
    ) -> VoiceStatusPayload {
        VoiceStatusPayload {
            reply_seq: Some(reply_seq),
            ..payload_with_reply(state, running, fake, reply)
        }
    }

    fn touch_event(path: &Path) -> notify::Event {
        Event::new(EventKind::Modify(ModifyKind::Data(DataChange::Any))).add_path(path.to_path_buf())
    }

    // ---- parse_voice_state_file -------------------------------------------

    #[test]
    fn parse_valid_payload_maps_all_fields() {
        let parsed = parse_voice_state_file(
            r#"{"state":"speaking","running":true,"fake_mode":true,"ts":1784662800.5}"#,
        )
        .expect("合法负载必须解析成功");
        assert_eq!(
            parsed,
            payload(Some("speaking"), true, true),
            "state/running/fake_mode 必须完整映射"
        );
    }

    #[test]
    fn parse_accepts_int_ts_for_cross_language_writers() {
        let parsed = parse_voice_state_file(
            r#"{"state":"idle","running":false,"fake_mode":false,"ts":1784662800}"#,
        );
        assert_eq!(parsed, Some(payload(Some("idle"), false, false)));
    }

    #[test]
    fn parse_unknown_state_becomes_none_but_stays_available() {
        let parsed = parse_voice_state_file(
            r#"{"state":"dancing","running":true,"fake_mode":false,"ts":1.0}"#,
        )
        .expect("未知状态不应拖垮整个通道");
        assert!(parsed.available);
        assert_eq!(parsed.state, None);
        assert!(parsed.running);
    }

    #[test]
    fn parse_rejects_schema_violations() {
        // 缺 ts / ts 为布尔 / state 为空串 / running 非布尔 / 非 JSON
        for content in [
            r#"{"state":"idle","running":true,"fake_mode":false}"#,
            r#"{"state":"idle","running":true,"fake_mode":false,"ts":true}"#,
            r#"{"state":"","running":true,"fake_mode":false,"ts":1.0}"#,
            r#"{"state":"idle","running":"yes","fake_mode":false,"ts":1.0}"#,
            "not json",
            "",
        ] {
            assert_eq!(parse_voice_state_file(content), None, "应拒绝: {content}");
        }
    }

    // ---- reply 透传（M6.3） -------------------------------------------------

    #[test]
    fn parse_maps_reply_when_present() {
        let parsed = parse_voice_state_file(
            r#"{"state":"speaking","running":true,"fake_mode":false,"ts":1.0,"reply":"本轮回复"}"#,
        )
        .expect("带 reply 的合法负载必须解析成功");
        assert_eq!(
            parsed,
            payload_with_reply(Some("speaking"), true, false, "本轮回复"),
            "reply 必须完整透传"
        );
    }

    #[test]
    fn parse_tolerates_missing_reply_for_legacy_files() {
        // M5.4 旧格式（无 reply 键）必须可读，reply 归为 None。
        let parsed = parse_voice_state_file(
            r#"{"state":"thinking","running":true,"fake_mode":true,"ts":2.0}"#,
        )
        .expect("旧格式文件必须解析成功");
        assert_eq!(parsed, payload(Some("thinking"), true, true));
        assert_eq!(parsed.reply, None);
    }

    #[test]
    fn parse_tolerates_non_string_reply() {
        // reply 非字符串 → 容错归为 None，不拖垮既有 schema 校验（与 Python 侧同语义）。
        for content in [
            r#"{"state":"speaking","running":true,"fake_mode":false,"ts":1.0,"reply":42}"#,
            r#"{"state":"speaking","running":true,"fake_mode":false,"ts":1.0,"reply":true}"#,
            r#"{"state":"speaking","running":true,"fake_mode":false,"ts":1.0,"reply":["x"]}"#,
        ] {
            let parsed = parse_voice_state_file(content)
                .unwrap_or_else(|| panic!("非字符串 reply 不应拖垮解析: {content}"));
            assert_eq!(parsed.reply, None, "应容错为 None: {content}");
            assert_eq!(parsed.state.as_deref(), Some("speaking"));
        }
    }

    // ---- reply_seq 透传（M6.3 修复） ----------------------------------------

    #[test]
    fn parse_maps_reply_seq_when_present() {
        let parsed = parse_voice_state_file(
            r#"{"state":"wake_listening","running":true,"fake_mode":false,"ts":1.0,"reply":"粘性回复","reply_seq":7}"#,
        )
        .expect("带 reply_seq 的合法负载必须解析成功");
        assert_eq!(
            parsed,
            payload_with_reply_seq(Some("wake_listening"), true, false, "粘性回复", 7),
            "reply 与 reply_seq 必须完整透传（粘性快照：非 speaking 状态也携带）"
        );
    }

    #[test]
    fn parse_tolerates_missing_reply_seq() {
        // M6.3 初版格式（有 reply 无 seq）必须可读，seq 归 None。
        let parsed = parse_voice_state_file(
            r#"{"state":"speaking","running":true,"fake_mode":false,"ts":1.0,"reply":"旧格式"}"#,
        )
        .expect("初版格式文件必须解析成功");
        assert_eq!(parsed.reply.as_deref(), Some("旧格式"));
        assert_eq!(parsed.reply_seq, None);
    }

    #[test]
    fn parse_tolerates_non_u64_reply_seq() {
        // reply_seq 小数/负数/字符串/布尔 → 容错归 None（与 Python 侧 int 校验同语义）。
        for content in [
            r#"{"state":"speaking","running":true,"fake_mode":false,"ts":1.0,"reply_seq":1.5}"#,
            r#"{"state":"speaking","running":true,"fake_mode":false,"ts":1.0,"reply_seq":-1}"#,
            r#"{"state":"speaking","running":true,"fake_mode":false,"ts":1.0,"reply_seq":"3"}"#,
            r#"{"state":"speaking","running":true,"fake_mode":false,"ts":1.0,"reply_seq":true}"#,
        ] {
            let parsed = parse_voice_state_file(content)
                .unwrap_or_else(|| panic!("非法 reply_seq 不应拖垮解析: {content}"));
            assert_eq!(parsed.reply_seq, None, "应容错为 None: {content}");
        }
    }

    // ---- window_mode 透传（M12 灵动岛双形态） --------------------------------

    #[test]
    fn parse_maps_window_mode_when_present() {
        // M12：状态文件携带 window_mode 时必须透传到前端。
        let parsed = parse_voice_state_file(
            r#"{"state":"idle","running":false,"fake_mode":false,"ts":1.0,"window_mode":"mini"}"#,
        )
        .expect("带 window_mode 的合法负载必须解析成功");
        assert_eq!(parsed.window_mode.as_deref(), Some("mini"));
        assert_eq!(parsed.state.as_deref(), Some("idle"));
    }

    #[test]
    fn parse_tolerates_missing_window_mode_for_legacy_files() {
        // M12 之前旧格式（无 window_mode 键）必须可读，归 None（前端按 Full 缺省）。
        let parsed = parse_voice_state_file(
            r#"{"state":"speaking","running":true,"fake_mode":false,"ts":1.0}"#,
        )
        .expect("旧格式文件必须解析成功");
        assert_eq!(parsed.window_mode, None);
    }

    #[test]
    fn parse_tolerates_non_string_window_mode() {
        // window_mode 非字符串 → 容错归 None，不拖垮既有 schema 校验。
        for content in [
            r#"{"state":"idle","running":false,"fake_mode":false,"ts":1.0,"window_mode":42}"#,
            r#"{"state":"idle","running":false,"fake_mode":false,"ts":1.0,"window_mode":true}"#,
            r#"{"state":"idle","running":false,"fake_mode":false,"ts":1.0,"window_mode":["mini"]}"#,
        ] {
            let parsed = parse_voice_state_file(content)
                .unwrap_or_else(|| panic!("非字符串 window_mode 不应拖垮解析: {content}"));
            assert_eq!(parsed.window_mode, None, "应容错为 None: {content}");
        }
    }

    #[test]
    fn window_mode_difference_is_a_semantic_change() {
        // M12：state 相同但 window_mode 不同（形态切换）必须视为语义变化并推送，
        // 否则前端窗口形态不跟随语音状态切换。
        let last = Some(payload_with_window_mode(Some("idle"), false, false, "mini"));
        let next_mini = payload_with_window_mode(Some("idle"), false, false, "mini");
        let next_full = payload_with_window_mode(Some("idle"), false, false, "full");
        assert_eq!(detect_change(&last, Some(next_mini.clone())), None, "同形态去抖");
        assert_eq!(
            detect_change(&last, Some(next_full.clone())),
            Some(next_full),
            "形态变化必须推送"
        );
    }

    // ---- tool_calls 透传（M13.2 Agent 可视化） --------------------------------

    fn sample_tool_call_json(id: &str, name: &str, status: &str) -> String {
        format!(
            r#"{{
                "id":"{id}",
                "name":"{name}",
                "args":{{"room":"客厅"}},
                "status":"{status}",
                "result":null,
                "ts":1784662800.5
            }}"#
        )
    }

    #[test]
    fn parse_maps_tool_calls_when_present() {
        // M13.2：状态文件携带 tool_calls 数组时必须透传到前端，
        // 字段名 snake_case → camelCase 归一（name→toolName, args→params, ts→timestamp）。
        let content = format!(
            r#"{{
                "state":"tool_using","running":true,"fake_mode":false,"ts":1.0,
                "tool_calls":[{}]
            }}"#,
            sample_tool_call_json("seq1", "home_control_light", "pending")
        );
        let parsed = parse_voice_state_file(&content).expect("带 tool_calls 的合法负载必须解析成功");
        let calls = parsed
            .tool_calls
            .as_ref()
            .expect("tool_calls 数组必须透传");
        assert_eq!(calls.len(), 1);
        let call = &calls[0];
        assert_eq!(call.id, "seq1");
        assert_eq!(call.tool_name, "home_control_light");
        assert_eq!(call.params, serde_json::json!({"room": "客厅"}));
        assert_eq!(call.result, None);
        assert_eq!(call.status, "pending");
        assert!((call.timestamp - 1784662800.5).abs() < f64::EPSILON);
    }

    #[test]
    fn parse_tolerates_missing_tool_calls_for_legacy_files() {
        // M13.2 之前的旧格式（无 tool_calls 键）必须可读，tool_calls 归 None。
        let parsed = parse_voice_state_file(
            r#"{"state":"speaking","running":true,"fake_mode":false,"ts":2.0}"#,
        )
        .expect("旧格式文件必须解析成功");
        assert_eq!(parsed.tool_calls, None, "旧格式无 tool_calls 键 → None");
    }

    #[test]
    fn parse_empty_tool_calls_list_represents_round_finished() {
        // 显式空数组（进入 SPEAKING 清空）必须可读，tool_calls = Some([])，
        // 与 None 区分：Some([]) 表示「本轮工具链已结束」，None 表示「无此字段」。
        let parsed = parse_voice_state_file(
            r#"{"state":"speaking","running":true,"fake_mode":false,"ts":1.0,"tool_calls":[]}"#,
        )
        .expect("空数组 tool_calls 必须解析成功");
        assert_eq!(parsed.tool_calls, Some(Vec::new()));
    }

    #[test]
    fn parse_non_array_tool_calls_tolerated_as_none() {
        // tool_calls 非数组（字符串/对象/标量）→ 容错归 None，不拖垮 schema 校验。
        for content in [
            r#"{"state":"idle","running":false,"fake_mode":false,"ts":1.0,"tool_calls":"not array"}"#,
            r#"{"state":"idle","running":false,"fake_mode":false,"ts":1.0,"tool_calls":42}"#,
            r#"{"state":"idle","running":false,"fake_mode":false,"ts":1.0,"tool_calls":true}"#,
            r#"{"state":"idle","running":false,"fake_mode":false,"ts":1.0,"tool_calls":{"x":1}}"#,
        ] {
            let parsed = parse_voice_state_file(content)
                .unwrap_or_else(|| panic!("非数组 tool_calls 不应拖垮解析: {content}"));
            assert_eq!(parsed.tool_calls, None, "应容错为 None: {content}");
        }
    }

    #[test]
    fn parse_filters_invalid_tool_call_elements() {
        // tool_calls 数组中含非法元素（缺 id / status 非法 / args 非对象）→ 过滤掉，
        // 仅保留合法元素；不拖垮整个数组。
        let content = r#"{
            "state":"tool_using","running":true,"fake_mode":false,"ts":1.0,
            "tool_calls":[
                {},
                {"id":"x"},
                {"id":"x","name":"y"},
                {"id":"x","name":"y","args":"not obj","status":"pending","ts":1.0},
                {"id":"x","name":"y","args":{},"status":"bogus","ts":1.0},
                {"id":"x","name":"y","args":{},"status":"pending","ts":"not num"},
                {},
                "string element",
                42,
                null,
                {}
            ]
        }"#;
        let parsed = parse_voice_state_file(content).expect("含非法元素的数组不应拖垮解析");
        assert_eq!(parsed.tool_calls.as_ref().map(|v| v.len()), Some(0), "全部元素非法 → 空数组");
    }

    #[test]
    fn parse_multiple_tool_calls_preserves_order() {
        // 多个合法工具调用按数组顺序保留（前端按调用顺序垂直排列）。
        let content = format!(
            r#"{{
                "state":"thinking","running":true,"fake_mode":false,"ts":1.0,
                "tool_calls":[
                    {},
                    {},
                    {}
                ]
            }}"#,
            sample_tool_call_json("seq1", "tool_a", "success"),
            sample_tool_call_json("seq2", "tool_b", "pending"),
            sample_tool_call_json("seq3", "tool_c", "error"),
        );
        let parsed = parse_voice_state_file(&content).expect("多工具调用负载必须解析成功");
        let calls = parsed.tool_calls.expect("tool_calls 必须透传");
        assert_eq!(calls.len(), 3);
        assert_eq!(calls[0].id, "seq1");
        assert_eq!(calls[0].tool_name, "tool_a");
        assert_eq!(calls[0].status, "success");
        assert_eq!(calls[1].id, "seq2");
        assert_eq!(calls[1].status, "pending");
        assert_eq!(calls[2].id, "seq3");
        assert_eq!(calls[2].status, "error");
    }

    #[test]
    fn parse_tool_call_with_result_string() {
        // success/error 状态的工具调用携带 result 字符串。
        let content = r#"{
                "state":"thinking","running":true,"fake_mode":false,"ts":1.0,
                "tool_calls":[
                    {"id":"seq1","name":"home_query","args":{},"status":"success","result":"{\"ok\":true,\"lights\":3}","ts":1.0}
                ]
            }"#.to_string();
        let parsed = parse_voice_state_file(&content).expect("带 result 的工具调用必须解析成功");
        let call = &parsed.tool_calls.expect("tool_calls 必须透传")[0];
        assert_eq!(call.status, "success");
        assert_eq!(call.result.as_deref(), Some(r#"{"ok":true,"lights":3}"#));
    }

    #[test]
    fn tool_calls_difference_is_a_semantic_change() {
        // M13.2：state 相同但 tool_calls 不同（工具状态变化）必须视为语义变化并推送，
        // 否则前端 AgentPanel 不跟随工具调用进度更新。
        let make_payload = |calls: Vec<ToolCallPayload>| VoiceStatusPayload {
            tool_calls: Some(calls),
            ..payload(Some("tool_using"), true, false)
        };
        let empty = make_payload(vec![]);
        let with_one = make_payload(vec![ToolCallPayload {
            id: "seq1".into(),
            tool_name: "tool_a".into(),
            params: serde_json::json!({}),
            result: None,
            status: "pending".into(),
            timestamp: 1.0,
        }]);
        // None → Some([]) 是语义变化（开始新一轮，工具列表初始化为空）
        assert_eq!(
            detect_change(&Some(payload(Some("tool_using"), true, false)), Some(empty.clone())),
            Some(empty.clone()),
            "None → Some([]) 必须推送"
        );
        // Some([]) → Some([pending]) 是语义变化（工具开始执行）
        assert_eq!(
            detect_change(&Some(empty), Some(with_one.clone())),
            Some(with_one.clone()),
            "工具列表变化必须推送"
        );
        // 相同 tool_calls 去抖
        assert_eq!(
            detect_change(&Some(with_one.clone()), Some(with_one)),
            None,
            "相同 tool_calls 去抖"
        );
    }

    fn payload_with_window_mode(
        state: Option<&str>,
        running: bool,
        fake: bool,
        window_mode: &str,
    ) -> VoiceStatusPayload {
        VoiceStatusPayload {
            window_mode: Some(window_mode.to_owned()),
            ..payload(state, running, fake)
        }
    }

    // ---- read_state_file ---------------------------------------------------

    #[test]
    fn read_state_file_roundtrip_and_missing_file() {
        let dir = std::env::temp_dir().join(format!("omni-hud-vw-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("voice-status.json");

        assert_eq!(read_state_file(&path), None, "文件缺失必须降级 None");

        std::fs::write(
            &path,
            r#"{"state":"thinking","running":true,"fake_mode":true,"ts":2.0}"#,
        )
        .unwrap();
        assert_eq!(
            read_state_file(&path),
            Some(payload(Some("thinking"), true, true))
        );

        std::fs::write(&path, "{corrupted").unwrap();
        assert_eq!(read_state_file(&path), None, "损坏文件必须降级 None");

        let _ = std::fs::remove_dir_all(&dir);
    }

    // ---- event_touches_path -------------------------------------------------

    #[test]
    fn event_filter_matches_target_path() {
        let target = PathBuf::from("/tmp/state/voice-status.json");
        let hit = touch_event(&target);
        assert!(event_touches_path(&hit, &target));

        let miss = touch_event(Path::new("/tmp/state/other.json"));
        assert!(!event_touches_path(&miss, &target));
    }

    #[test]
    fn event_filter_matches_rename_destination() {
        // os.replace(tmp → target)：rename 事件同时携带源与目标路径。
        let target = PathBuf::from("/tmp/state/voice-status.json");
        let event = Event::new(EventKind::Modify(ModifyKind::Name(RenameMode::Both)))
            .add_path(PathBuf::from("/tmp/state/.voice-status.json.123.tmp"))
            .add_path(target.clone());
        assert!(event_touches_path(&event, &target));
    }

    #[test]
    fn event_filter_matches_create_of_target() {
        let target = PathBuf::from("/tmp/state/voice-status.json");
        let event =
            Event::new(EventKind::Create(CreateKind::File)).add_path(target.clone());
        assert!(event_touches_path(&event, &target));
    }

    // ---- detect_change ------------------------------------------------------

    #[test]
    fn first_call_always_emits_even_when_unavailable() {
        // 启动初始同步：即使文件缺失（→ unavailable）也要推送一次，
        // 让前端尽快脱离「未知」状态。
        let emitted = detect_change(&None, None);
        assert_eq!(emitted, Some(VoiceStatusPayload::unavailable()));
    }

    #[test]
    fn identical_payload_is_debounced() {
        let last = Some(payload(Some("idle"), true, true));
        assert_eq!(detect_change(&last, Some(payload(Some("idle"), true, true))), None);
    }

    #[test]
    fn semantic_change_passes_through() {
        let last = Some(payload(Some("idle"), true, true));
        let next = payload(Some("speaking"), true, true);
        assert_eq!(detect_change(&last, Some(next.clone())), Some(next));
    }

    #[test]
    fn reply_difference_is_a_semantic_change() {
        // M6.3：同为 speaking 但 reply 不同（新一轮回复）必须视为变化并推送，
        // 否则 OpenTalking 联动会丢轮次；reply 相同则被去抖。
        let last = Some(payload_with_reply(Some("speaking"), true, false, "第一轮回复"));
        let next = payload_with_reply(Some("speaking"), true, false, "第二轮回复");
        assert_eq!(detect_change(&last, Some(next.clone())), Some(next));
        assert_eq!(detect_change(&last, Some(payload_with_reply(Some("speaking"), true, false, "第一轮回复"))), None);
        // speaking(带 reply) → 其他状态(无 reply) 同样是语义变化
        assert_eq!(
            detect_change(&last, Some(payload(Some("wake_listening"), true, false))),
            Some(payload(Some("wake_listening"), true, false))
        );
    }

    #[test]
    fn reply_seq_difference_is_a_semantic_change() {
        // M6.3 修复：state 与 reply 文本都相同、仅 reply_seq 不同（相同文本的
        // 新一轮回复）必须视为语义变化并推送，否则前端 bridge 丢轮次。
        let last = Some(payload_with_reply_seq(
            Some("wake_listening"),
            true,
            false,
            "同一句话",
            1,
        ));
        let next = payload_with_reply_seq(Some("wake_listening"), true, false, "同一句话", 2);
        assert_eq!(detect_change(&last, Some(next.clone())), Some(next));
        // seq 相同则去抖（粘性快照的重复读取不重复推送）。
        assert_eq!(
            detect_change(
                &last,
                Some(payload_with_reply_seq(
                    Some("wake_listening"),
                    true,
                    false,
                    "同一句话",
                    1
                ))
            ),
            None
        );
    }

    #[test]
    fn file_disappearance_emits_unavailable_once() {
        let last = Some(payload(Some("speaking"), true, true));
        let gone = detect_change(&last, None);
        assert_eq!(gone, Some(VoiceStatusPayload::unavailable()));
        // 再次仍缺失 → 与上次相同，去抖不再推送。
        assert_eq!(detect_change(&gone, None), None);
    }

    // ---- run_watch_loop -----------------------------------------------------

    #[test]
    fn loop_syncs_initial_then_pushes_changes_and_debounces() {
        let target = PathBuf::from("/tmp/voice-status.json");
        let (tx, rx) = channel();
        let target_clone = target.clone();
        let script = std::sync::Arc::new(std::sync::Mutex::new(VecDeque::from(vec![
            Some(payload(Some("idle"), true, true)),     // 启动初始同步 → 推送
            Some(payload(Some("speaking"), true, true)), // 第一次变化 → 推送
            None,                                        // 文件消失 → unavailable
        ])));
        let script_clone = script.clone();
        let read = move |_: &Path| script_clone.lock().unwrap().pop_front().flatten();
        let mut emitted: Vec<VoiceStatusPayload> = Vec::new();

        // 子线程发送事件序列：
        // 1. 先发一个无关事件和错误事件（应被过滤）
        // 2. 发一个触碰事件（触发第一次去抖，等待窗口后读到 speaking）
        // 3. 等待 >80ms，再发一个触碰事件（触发第二次去抖，读到 unavailable）
        let sender = std::thread::spawn(move || {
            // 初始同步先让 loop 启动，短暂 sleep
            std::thread::sleep(std::time::Duration::from_millis(20));
            // 不触碰目标文件的事件：必须被过滤
            tx.send(Ok(touch_event(Path::new("/tmp/unrelated.json")))).unwrap();
            // 通道里的 notify 错误事件：跳过即可
            tx.send(Err(notify::Error::generic("boom"))).unwrap();
            // 第一个目标事件（此时文件内容是 speaking）
            tx.send(Ok(touch_event(&target_clone))).unwrap();
            // 等待去抖窗口通过，让第一次处理完成
            std::thread::sleep(std::time::Duration::from_millis(120));
            // 第二个目标事件（此时文件内容是 None/unavailable）
            tx.send(Ok(touch_event(&target_clone))).unwrap();
            // 等待去抖窗口通过
            std::thread::sleep(std::time::Duration::from_millis(120));
            drop(tx);
        });

        run_watch_loop(&target, &rx, &read, &mut |p| emitted.push(p));
        sender.join().unwrap();

        assert_eq!(
            emitted,
            vec![
                payload(Some("idle"), true, true),
                payload(Some("speaking"), true, true),
                VoiceStatusPayload::unavailable(),
            ],
            "初始同步 + 两次语义变化，无关事件/错误被过滤"
        );
    }

    #[test]
    fn loop_exits_on_disconnect_without_events() {
        let target = PathBuf::from("/tmp/voice-status.json");
        let (tx, rx) = channel::<notify::Result<notify::Event>>();
        drop(tx);
        let script = std::cell::RefCell::new(VecDeque::from(vec![None])); // 初始同步读一次
        let read = |_: &Path| script.borrow_mut().pop_front().flatten();
        let mut emitted = Vec::new();
        run_watch_loop(&target, &rx, &read, &mut |p| emitted.push(p));
        assert_eq!(emitted, vec![VoiceStatusPayload::unavailable()]);
    }

    // ---- P1-8: default_state_file_path 返回 Result -------------------------

    #[test]
    fn default_state_file_path_returns_result_not_pathbuf() {
        // P1-8：home_dir() 失败时应返回 Err，而不是静默降级到 "."
        let result = default_state_file_path();
        // 正常环境下应返回 Ok，且路径包含 .ai-omni/state/voice-status.json
        match result {
            Ok(path) => {
                assert!(path.ends_with(".ai-omni/state/voice-status.json") ||
                        path.ends_with(".ai-omni\\state\\voice-status.json"),
                        "路径应指向 ~/.ai-omni/state/voice-status.json");
            }
            Err(_) => {
                // home_dir 失败时返回 Err 也是正确行为（P1-8）
            }
        }
    }

    // ---- P1-7: 80ms 事件去抖 -----------------------------------------------

    #[test]
    fn debounce_coalesces_events_within_80ms_window() {
        // P1-7：80ms 内多次事件只处理最后一次
        let target = PathBuf::from("/tmp/voice-status.json");
        let (tx, rx) = channel();
        let target_clone = target.clone();
        // 模拟快速连续事件：idle → speaking → thinking → idle，间隔 <80ms
        let script = std::sync::Arc::new(std::sync::Mutex::new(VecDeque::from(vec![
            Some(payload(Some("idle"), true, true)),     // 初始同步
            Some(payload(Some("idle"), true, false)),    // 最后一次（去抖合并后读这个）
        ])));
        let script_clone = script.clone();
        let read = move |_: &Path| script_clone.lock().unwrap().pop_front().flatten();
        let mut emitted: Vec<VoiceStatusPayload> = Vec::new();

        // 子线程快速发送 3 个事件（间隔 10ms，都 <80ms）
        let sender = std::thread::spawn(move || {
            std::thread::sleep(std::time::Duration::from_millis(20));
            // 快速发送 3 个事件，间隔 10ms（都 <80ms）
            for _ in 0..3 {
                tx.send(Ok(touch_event(&target_clone))).unwrap();
                std::thread::sleep(std::time::Duration::from_millis(10));
            }
            // 等待 >80ms 让去抖窗口结束，然后断开通道
            std::thread::sleep(std::time::Duration::from_millis(120));
            drop(tx);
        });

        run_watch_loop(&target, &rx, &read, &mut |p| emitted.push(p));
        sender.join().unwrap();

        // 初始同步 + 最后一次 idle（中间的 speaking/thinking 被去抖合并）
        assert!(emitted.len() >= 2, "至少推送初始同步和最终状态，实际: {}", emitted.len());
        assert_eq!(
            emitted.last().unwrap().state.as_deref(),
            Some("idle"),
            "应只推送最后一次状态"
        );
        assert!(!emitted.last().unwrap().fake_mode, "最后一次 fake_mode=false");
    }
}
