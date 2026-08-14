"""omni_office 命令行入口：``python -m omni_office <子命令>``。

CLI 是 tools 层的薄壳：解析参数 → 调用 tools → 打印 JSON → 映射退出码
（ok:true → 0，ok:false → 1；参数解析错误返回 E_INVALID_PARAMS JSON 并退出 1）。

子命令：

- ``status``                                                       ：插件状态（文档/日程/邮件计数 + 库路径）
- ``doc-create TITLE [--content X] [--tags a,b]``                  ：创建文档
- ``doc-list``                                                     ：列出文档
- ``event-create TITLE --start S --end E [--reminder-minutes N]``  ：创建日程
- ``event-conflicts --start S --end E``                            ：冲突检查
- ``reminders [--now ISO]``                                        ：到期提醒
- ``email-send --to a@x.com --subject S --body B [--fake]``        ：发送邮件
- ``meeting-prep TITLE --start S --end E --attendees a,b [--agenda X] [--fake]``
                                                                   ：会议准备一条龙
- ``call <tool> [--args JSON] [--fake]``                           ：通用工具调用（Rust 桥接入口）

``--fake`` 把运行时切到 FakeEmailBackend（演示/测试，不访问真实 SMTP/IMAP）。
库路径默认 ``~/.ai-omni/office/office.db``，env ``AI_OMNI_OFFICE_DB`` 可覆盖。
"""

from __future__ import annotations

import argparse
import json

from omni_sdk.cli_utils import JsonErrorArgumentParser

from . import tools


def _emit(result_json: str) -> int:
    """打印工具返回的 JSON，并按 ok 字段映射退出码。"""
    print(result_json)
    try:
        return 0 if json.loads(result_json).get("ok") else 1
    except (ValueError, TypeError):
        return 1


def _find_tool(name: str):
    """按 name 在 TOOLS 注册表里查 handler_func；未找到返回 None。"""
    for meta in tools.TOOLS:
        if meta["name"] == name:
            return meta["handler_func"]
    return None


def _split_csv(value: str | None) -> list[str]:
    """逗号分隔字符串 → 去空白非空列表。"""
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


# ---------------------------------------------------------------------------
# 通用 call 子命令（Rust 桥接入口）
# ---------------------------------------------------------------------------
def _cmd_call(args: argparse.Namespace) -> int:
    try:
        kwargs = json.loads(args.args) if args.args else {}
    except ValueError as exc:
        return _emit(tools._err("E_INVALID_ARGS", f"--args 不是合法 JSON: {exc}"))
    if not isinstance(kwargs, dict):
        return _emit(tools._err("E_INVALID_ARGS", "--args 顶层必须是 JSON 对象"))
    handler = _find_tool(args.tool)
    if handler is None:
        return _emit(tools._err("E_INVALID_ARGS", f"未知工具: {args.tool}"))
    return _emit(handler(**kwargs))


# ---------------------------------------------------------------------------
# HTTP 工具桥（M36，UniHub 远程同步入口）
# ---------------------------------------------------------------------------
def _cmd_serve(args: argparse.Namespace) -> int:
    from .http_server import resolve_token, serve

    return serve(
        host=args.host,
        port=args.port,
        token=resolve_token(args.token),
        use_fake=getattr(args, "fake", False),
    )


# ---------------------------------------------------------------------------
# 具名子命令
# ---------------------------------------------------------------------------
def _cmd_status(args: argparse.Namespace) -> int:
    return _emit(tools.office_status())


def _cmd_doc_create(args: argparse.Namespace) -> int:
    return _emit(
        tools.office_doc_create(
            title=args.title,
            content=args.content or "",
            tags=_split_csv(args.tags),
        )
    )


def _cmd_doc_list(args: argparse.Namespace) -> int:
    return _emit(tools.office_doc_list())


def _cmd_event_create(args: argparse.Namespace) -> int:
    return _emit(
        tools.office_event_create(
            title=args.title,
            start=args.start,
            end=args.end,
            reminder_minutes=args.reminder_minutes,
            force=args.force,
        )
    )


def _cmd_event_conflicts(args: argparse.Namespace) -> int:
    return _emit(tools.office_event_check_conflicts(start=args.start, end=args.end))


def _cmd_reminders(args: argparse.Namespace) -> int:
    return _emit(tools.office_event_reminders(now=args.now))


def _cmd_email_send(args: argparse.Namespace) -> int:
    return _emit(
        tools.office_email_send(
            to=_split_csv(args.to),
            subject=args.subject,
            body=args.body,
            template=args.template,
        )
    )


def _cmd_meeting_prep(args: argparse.Namespace) -> int:
    return _emit(
        tools.office_meeting_prep(
            title=args.title,
            start=args.start,
            end=args.end,
            attendees=_split_csv(args.attendees),
            agenda=args.agenda,
            force=args.force,
        )
    )


def build_parser() -> JsonErrorArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = JsonErrorArgumentParser(
        prog="omni_office",
        description="办公自动化：文档 / 邮件 / 日程 + 会议准备跨模块工作流",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # status
    p_status = sub.add_parser("status", help="打印插件状态（文档/日程/邮件计数 + 库路径）")
    p_status.set_defaults(func=_cmd_status)

    # doc-create
    p_doc_create = sub.add_parser("doc-create", help="创建文档（初始版本 v1）")
    p_doc_create.add_argument("title", help="文档标题")
    p_doc_create.add_argument("--content", default="", help="初始内容")
    p_doc_create.add_argument("--tags", default="", help="标签，逗号分隔")
    p_doc_create.set_defaults(func=_cmd_doc_create)

    # doc-list
    p_doc_list = sub.add_parser("doc-list", help="列出全部文档")
    p_doc_list.set_defaults(func=_cmd_doc_list)

    # event-create
    p_event_create = sub.add_parser("event-create", help="创建日程")
    p_event_create.add_argument("title", help="日程标题")
    p_event_create.add_argument("--start", required=True, help="开始时间（ISO8601 或 epoch 秒）")
    p_event_create.add_argument("--end", required=True, help="结束时间（ISO8601 或 epoch 秒）")
    p_event_create.add_argument("--reminder-minutes", type=int, default=None, help="提前提醒分钟数")
    p_event_create.add_argument("--force", action="store_true", help="冲突时强制创建")
    p_event_create.set_defaults(func=_cmd_event_create)

    # event-conflicts
    p_conflicts = sub.add_parser("event-conflicts", help="检查时间段与现有日程的冲突")
    p_conflicts.add_argument("--start", required=True, help="开始时间（ISO8601 或 epoch 秒）")
    p_conflicts.add_argument("--end", required=True, help="结束时间（ISO8601 或 epoch 秒）")
    p_conflicts.set_defaults(func=_cmd_event_conflicts)

    # reminders
    p_reminders = sub.add_parser("reminders", help="取到期提醒并标记已提醒")
    p_reminders.add_argument("--now", default=None, help="当前时间（缺省取系统时间）")
    p_reminders.set_defaults(func=_cmd_reminders)

    # email-send
    p_email_send = sub.add_parser("email-send", help="发送邮件（写入本地 sent 文件夹）")
    p_email_send.add_argument("--to", required=True, help="收件人，逗号分隔")
    p_email_send.add_argument("--subject", default=None, help="主题")
    p_email_send.add_argument("--body", default=None, help="正文（与 --template 二选一）")
    p_email_send.add_argument("--template", default=None, help="模板名（与 --body 二选一）")
    p_email_send.add_argument("--fake", action="store_true", help="使用 fake 后端（演示/测试）")
    p_email_send.set_defaults(func=_cmd_email_send)

    # meeting-prep
    p_meeting = sub.add_parser("meeting-prep", help="会议准备：建档纪要 + 建日程 + 发邀请邮件")
    p_meeting.add_argument("title", help="会议标题")
    p_meeting.add_argument("--start", required=True, help="开始时间（ISO8601 或 epoch 秒）")
    p_meeting.add_argument("--end", required=True, help="结束时间（ISO8601 或 epoch 秒）")
    p_meeting.add_argument("--attendees", required=True, help="参会人邮箱，逗号分隔")
    p_meeting.add_argument("--agenda", default=None, help="议程")
    p_meeting.add_argument("--force", action="store_true", help="冲突时强制创建")
    p_meeting.add_argument("--fake", action="store_true", help="使用 fake 后端（演示/测试）")
    p_meeting.set_defaults(func=_cmd_meeting_prep)

    # call（通用工具调用，Rust 桥接入口）
    p_call = sub.add_parser("call", help="通用工具调用（tool 名 + JSON 参数）")
    p_call.add_argument("tool", help="工具名，如 office_status / office_doc_create")
    p_call.add_argument(
        "--args",
        default="",
        help='工具参数 JSON 字符串，如 \'{"title":"周报","content":"..."}\'',
    )
    p_call.add_argument("--fake", action="store_true", help="使用 fake 后端（演示/测试）")
    p_call.set_defaults(func=_cmd_call)

    # serve（HTTP 工具桥，UniHub 远程同步入口）
    from .http_server import DEFAULT_HOST, DEFAULT_PORT

    p_serve = sub.add_parser(
        "serve",
        help="启动 HTTP 工具桥（POST /v1/tools/call，供 UniHub 移动端远程同步）",
    )
    p_serve.add_argument("--host", default=DEFAULT_HOST, help=f"监听地址（默认 {DEFAULT_HOST}）")
    p_serve.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"监听端口（默认 {DEFAULT_PORT}）"
    )
    p_serve.add_argument(
        "--token",
        default=None,
        help="Bearer 鉴权 token；缺省回落 env OMNI_OFFICE_HTTP_TOKEN，再无则开放访问",
    )
    p_serve.add_argument("--fake", action="store_true", help="使用 fake 后端（演示/测试）")
    p_serve.set_defaults(func=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：解析参数并派发到对应子命令。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "fake", False):
        tools._runtime.use_fake_backends = True
    return args.func(args)
