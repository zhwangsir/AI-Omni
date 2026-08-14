"""omni_lyrics 命令行入口：``python -m omni_lyrics <子命令>``。

CLI 是 tools 层的薄壳：解析参数 → 调用 tools → 打印 JSON → 映射退出码
（ok:true → 0，ok:false → 1；参数解析错误返回 E_INVALID_PARAMS JSON 并退出 1）。

子命令：

- ``call <tool> [--args JSON] [--fake]``  ：通用工具调用（Rust ``lyrics_tool`` 桥接入口）
- ``get --song-id ID [--source S] [--fake]`` ：获取歌词
- ``search KEYWORD [--limit N] [--fake]``   ：搜索歌曲
- ``offset OFFSET_S [--fake]``              ：设置用户偏移
- ``current --song-id ID --time T [--fake]``：获取当前行 + 逐字高亮

``--fake`` 使用 FakeMusicSource（内置 3 首歌曲），无需真实音乐 API 即可演示完整链路。
``call`` 子命令的 ``fake`` 也可经 ``--args`` JSON 内 ``"fake": true`` 传入（与 omni_music 同款模式）。
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


# ---------------------------------------------------------------------------
# 通用 call 子命令（Rust lyrics_tool 桥接入口）
# ---------------------------------------------------------------------------
def _cmd_call(args: argparse.Namespace) -> int:
    # fake 标志可经 --args JSON 内 "fake": true 传入，也可经 --fake CLI 开关传入
    try:
        kwargs = json.loads(args.args) if args.args else {}
    except ValueError as exc:
        return _emit(tools._err("E_INVALID_ARGS", f"--args 不是合法 JSON: {exc}"))
    if not isinstance(kwargs, dict):
        return _emit(tools._err("E_INVALID_ARGS", "--args 顶层必须是 JSON 对象"))
    # 合并 fake 标志：CLI --fake 或 JSON 内 fake:true
    fake = bool(kwargs.get("fake", False)) or args.fake
    handler = _find_tool(args.tool)
    if handler is None:
        return _emit(tools._err("E_INVALID_ARGS", f"未知工具: {args.tool}"))
    # 仅当工具 schema 声明了 fake 参数时才注入（lyrics_set_offset 不接受 fake）
    tool_meta = next((m for m in tools.TOOLS if m["name"] == args.tool), None)
    if tool_meta and "fake" in tool_meta["schema"]["parameters"]["properties"]:
        kwargs["fake"] = fake
    return _emit(handler(**kwargs))


# ---------------------------------------------------------------------------
# 具名子命令（便于人工 CLI 操作）
# ---------------------------------------------------------------------------
def _cmd_get(args: argparse.Namespace) -> int:
    return _emit(
        tools.lyrics_get(song_id=args.song_id, source=args.source, fake=args.fake)
    )


def _cmd_search(args: argparse.Namespace) -> int:
    return _emit(
        tools.lyrics_search(keyword=args.keyword, limit=args.limit, fake=args.fake)
    )


def _cmd_offset(args: argparse.Namespace) -> int:
    return _emit(tools.lyrics_set_offset(offset_s=args.offset_s))


def _cmd_current(args: argparse.Namespace) -> int:
    return _emit(
        tools.lyrics_get_current(
            song_id=args.song_id, current_time_s=args.time, fake=args.fake
        )
    )


def build_parser() -> JsonErrorArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = JsonErrorArgumentParser(
        prog="omni_lyrics",
        description="歌词多源匹配：LRC解析/优先级链/同步/上传",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # call：通用工具调用（Rust 桥接入口）
    p_call = sub.add_parser("call", help="通用工具调用（tool 名 + JSON 参数）")
    p_call.add_argument("tool", help="工具名，如 lyrics_get / lyrics_search")
    p_call.add_argument(
        "--args",
        default="",
        help='工具参数 JSON 字符串，如 \'{"song_id":"s1","fake":true}\'',
    )
    p_call.add_argument("--fake", action="store_true", help="使用 fake 音乐源（演示）")
    p_call.set_defaults(func=_cmd_call)

    # get
    p_get = sub.add_parser("get", help="获取歌词")
    p_get.add_argument("--song-id", dest="song_id", required=True, help="歌曲 ID")
    p_get.add_argument("--source", default=None, help="来源过滤：local_file/embedded/online/none")
    p_get.add_argument("--fake", action="store_true", help="使用 fake 音乐源")
    p_get.set_defaults(func=_cmd_get)

    # search
    p_search = sub.add_parser("search", help="搜索歌曲")
    p_search.add_argument("keyword", help="搜索关键词")
    p_search.add_argument("--limit", type=int, default=20, help="返回上限（默认 20）")
    p_search.add_argument("--fake", action="store_true", help="使用 fake 音乐源")
    p_search.set_defaults(func=_cmd_search)

    # offset
    p_offset = sub.add_parser("offset", help="设置用户偏移量（秒）")
    p_offset.add_argument("offset_s", type=float, help="偏移秒数（正数提前，负数延后）")
    p_offset.set_defaults(func=_cmd_offset)

    # current
    p_current = sub.add_parser("current", help="获取当前歌词行")
    p_current.add_argument("--song-id", dest="song_id", required=True, help="歌曲 ID")
    p_current.add_argument("--time", type=float, required=True, help="当前播放时间（秒）")
    p_current.add_argument("--fake", action="store_true", help="使用 fake 音乐源")
    p_current.set_defaults(func=_cmd_current)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：解析参数并派发到对应子命令。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
