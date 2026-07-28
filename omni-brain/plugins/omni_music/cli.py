"""omni_music 命令行入口：``python -m omni_music <子命令>``。

CLI 是 tools 层的薄壳：解析参数 → 调用 tools → 打印 JSON → 映射退出码
（ok:true → 0，ok:false → 1；参数解析错误由 argparse 以 2 退出）。

子命令：

- ``call <tool> [--args JSON]``  ：通用工具调用（Rust ``music_tool`` 桥接入口）
- ``search KEYWORD [--limit N] [--fake]`` ：搜索歌曲
- ``play [--song-id ID | --index N | --keyword KW] [--fake]`` ：播放
- ``pause | resume | stop | next | previous [--fake]`` ：播放控制
- ``seek POSITION_S [--fake]`` ：跳转进度
- ``repeat MODE [--fake]`` ：设置循环模式（single/list_loop/random/sequence）
- ``state [--fake]`` ：获取播放器状态
- ``login [--fake]`` ：发起扫码登录
- ``login-check KEY [--fake]`` ：轮询登录状态
- ``library-scan [--root DIR] [--fake]`` ：扫描本地音乐库写入 SQLite（M19）
- ``library-search QUERY [--limit N] [--fake]`` ：FTS5 全文搜索（M19）
- ``library-status [--fake]`` ：库状态（M19）
- ``playlist-create NAME [--fake]`` ：创建歌单（M19）
- ``playlist-add PID SID [--position N] [--fake]`` ：歌单添加歌曲（M19）
- ``playlist-remove PID SID [--fake]`` ：歌单移除歌曲（M19）
- ``playlist-list [--playlist-id N] [--fake]`` ：列歌单 / 歌单内歌曲（M19）
- ``decrypt PATH [--output PATH] --confirm [--fake]`` ：解密加密音频（M19，D19.1 合规）

跨 CLI 调用的有状态播放（队列/当前曲目）经 state_file 持久化串联：
``call`` 与具名子命令启动时调用 ``load_player_from_state_file`` 恢复上次状态，
播放控制工具执行后由 ``_write_state_file`` 原子写入——与 omni_voice
control_file/state_file 同款模式。

library 子命令经 env ``AI_OMNI_MUSIC_DB`` 控制数据库路径（跨 CLI 调用共享同一 SQLite）。

``--fake`` 使用 FakeMusicSource（3 首内置歌曲），无需真实音乐 API 即可演示完整链路。
"""

from __future__ import annotations

import argparse
import json
import time

from . import tools


def _emit(result_json: str) -> int:
    """打印工具返回的 JSON，并按 ok 字段映射退出码。"""
    print(result_json)
    try:
        return 0 if json.loads(result_json).get("ok") else 1
    except (ValueError, TypeError):
        return 1


def _load_state(fake: bool) -> None:
    """从 state_file 恢复 player 到运行时（跨 CLI 调用状态串联）。

    :param fake: 是否使用 fake 源（决定恢复时构造 FakeMusicSource 还是真实源）
    """
    tools.load_player_from_state_file(tools._runtime, fake)


def _find_tool(name: str):
    """按 name 在 TOOLS 注册表里查 handler_func；未找到返回 None。"""
    for meta in tools.TOOLS:
        if meta["name"] == name:
            return meta["handler_func"]
    return None


def _ensure_login_flow(rt: tools.Runtime, fake: bool, key: str) -> None:
    """跨 CLI 调用重建扫码登录 flow。

    QRLoginFlow 的 ``_key`` / ``_started_at`` 是 ``start()`` 时填充的内部状态，
    跨 CLI 子进程不持久化。前端轮询 ``music_check_login_status(key)`` 时每次都是
    新进程，这里按 key 重建 flow 使其可继续轮询。重建后 ``_started_at`` 刷新，
    超时窗口从当前时刻重新计（CLI 桥场景可接受，登录是短交互）。

    ``fake=True`` 时构造 :class:`FakeQRLoginFlow` 以复用 fake 状态序列
    （waiting→scanned→confirmed）；否则构造真实 :class:`QRLoginFlow`。
    """
    if rt.flow is not None:
        return
    source = tools._get_source(rt, fake)
    if source is None:
        return
    store = tools._get_store(rt, fake)
    if fake:
        from omni_music.auth.qr_login import FakeQRLoginFlow

        flow = FakeQRLoginFlow(source=source, store=store)
    else:
        from omni_music.auth.qr_login import QRLoginFlow

        flow = QRLoginFlow(source=source, store=store)
    flow._key = key  # type: ignore[attr-defined]
    flow._started_at = time.monotonic()  # type: ignore[attr-defined]
    rt.flow = flow


# ---------------------------------------------------------------------------
# 通用 call 子命令（Rust music_tool 桥接入口）
# ---------------------------------------------------------------------------
def _cmd_call(args: argparse.Namespace) -> int:
    # 先解析 --args 以取 fake 标志：call 子命令的 fake 经 JSON 参数传入
    # （如 '{"fake":true}'），而非 --fake CLI 开关；load_state 需按真实 fake 恢复 player。
    try:
        kwargs = json.loads(args.args) if args.args else {}
    except ValueError as exc:
        return _emit(tools._err("E_INVALID_ARGS", f"--args 不是合法 JSON: {exc}"))
    if not isinstance(kwargs, dict):
        return _emit(tools._err("E_INVALID_ARGS", "--args 顶层必须是 JSON 对象"))
    fake = bool(kwargs.get("fake", False)) or args.fake
    _load_state(fake)
    handler = _find_tool(args.tool)
    if handler is None:
        return _emit(tools._err("E_INVALID_ARGS", f"未知工具: {args.tool}"))
    return _emit(handler(**kwargs))


# ---------------------------------------------------------------------------
# 具名子命令（便于人工 CLI 操作）
# ---------------------------------------------------------------------------
def _cmd_search(args: argparse.Namespace) -> int:
    _load_state(args.fake)
    return _emit(tools.music_search(keyword=args.keyword, limit=args.limit, fake=args.fake))


def _cmd_play(args: argparse.Namespace) -> int:
    _load_state(args.fake)
    return _emit(
        tools.music_play(
            song_id=args.song_id,
            index=args.index,
            keyword=args.keyword,
            fake=args.fake,
        )
    )


def _cmd_simple(action: str):
    """构造无参播放控制命令（pause/resume/stop/next/previous）的 handler。"""

    def _cmd(args: argparse.Namespace) -> int:
        _load_state(args.fake)
        handler = _find_tool(f"music_{action}")
        assert handler is not None, f"music_{action} 工具未注册"
        return _emit(handler(fake=args.fake))

    return _cmd


def _cmd_seek(args: argparse.Namespace) -> int:
    _load_state(args.fake)
    return _emit(tools.music_seek(position_s=args.position_s, fake=args.fake))


def _cmd_repeat(args: argparse.Namespace) -> int:
    _load_state(args.fake)
    return _emit(tools.music_set_repeat_mode(mode=args.mode, fake=args.fake))


def _cmd_state(args: argparse.Namespace) -> int:
    _load_state(args.fake)
    handler = _find_tool("music_get_player_state")
    assert handler is not None
    return _emit(handler(fake=args.fake))


def _cmd_login(args: argparse.Namespace) -> int:
    return _emit(tools.music_get_login_qr(fake=args.fake))


def _cmd_login_check(args: argparse.Namespace) -> int:
    _load_state(args.fake)
    # 跨 CLI 子进程重建扫码登录 flow：QRLoginFlow 的 _key/_started_at 是 start() 时
    # 填充的内存态，新子进程不持久化。前端轮询 music_check_login_status 每次都是新
    # 进程，这里按 key 重建 flow 使其可继续轮询（_started_at 刷新，超时窗口重新计）。
    _ensure_login_flow(tools._runtime, args.fake, args.key)
    handler = _find_tool("music_check_login_status")
    assert handler is not None
    return _emit(handler(key=args.key, fake=args.fake))


# ---------------------------------------------------------------------------
# M19 本地音乐库子命令（library / playlist / decrypt）
# ---------------------------------------------------------------------------
def _cmd_library_scan(args: argparse.Namespace) -> int:
    """library-scan：扫描本地音乐库写入 SQLite。"""
    return _emit(
        tools.music_library_scan(root_dir=args.root_dir, fake=args.fake)
    )


def _cmd_library_search(args: argparse.Namespace) -> int:
    """library-search：FTS5 全文搜索。"""
    return _emit(
        tools.music_library_search(query=args.query, limit=args.limit, fake=args.fake)
    )


def _cmd_library_status(args: argparse.Namespace) -> int:
    """library-status：库状态。"""
    return _emit(tools.music_library_status(fake=args.fake))


def _cmd_playlist_create(args: argparse.Namespace) -> int:
    """playlist-create：创建歌单。"""
    return _emit(tools.music_playlist_create(name=args.name, fake=args.fake))


def _cmd_playlist_add(args: argparse.Namespace) -> int:
    """playlist-add：歌单添加歌曲。"""
    return _emit(
        tools.music_playlist_add(
            playlist_id=args.playlist_id,
            song_id=args.song_id,
            position=args.position,
            fake=args.fake,
        )
    )


def _cmd_playlist_remove(args: argparse.Namespace) -> int:
    """playlist-remove：歌单移除歌曲。"""
    return _emit(
        tools.music_playlist_remove(
            playlist_id=args.playlist_id, song_id=args.song_id, fake=args.fake
        )
    )


def _cmd_playlist_list(args: argparse.Namespace) -> int:
    """playlist-list：列歌单 / 歌单内歌曲。"""
    return _emit(
        tools.music_playlist_list(playlist_id=args.playlist_id, fake=args.fake)
    )


def _cmd_decrypt(args: argparse.Namespace) -> int:
    """decrypt：解密加密音频文件（需 --confirm 安全门）。"""
    return _emit(
        tools.music_decrypt_file(
            path=args.path, output_path=args.output, confirm=args.confirm, fake=args.fake
        )
    )


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="omni_music",
        description="音乐源接入：多源搜索/扫码登录/Cookie加密/播放控制",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # call：通用工具调用（Rust 桥接入口）
    p_call = sub.add_parser("call", help="通用工具调用（tool 名 + JSON 参数）")
    p_call.add_argument("tool", help="工具名，如 music_play / music_search")
    p_call.add_argument(
        "--args",
        default="",
        help="工具参数 JSON 字符串，如 '{\"keyword\":\"晴天\",\"fake\":true}'",
    )
    p_call.add_argument("--fake", action="store_true", help="使用 fake 音乐源（演示）")
    p_call.set_defaults(func=_cmd_call)

    # search
    p_search = sub.add_parser("search", help="搜索歌曲")
    p_search.add_argument("keyword", help="搜索关键词")
    p_search.add_argument("--limit", type=int, default=20, help="返回上限（默认 20）")
    p_search.add_argument("--fake", action="store_true", help="使用 fake 音乐源")
    p_search.set_defaults(func=_cmd_search)

    # play
    p_play = sub.add_parser("play", help="播放（song_id / index / keyword / 恢复）")
    p_play.add_argument("--song-id", dest="song_id", help="按 song_id 播放")
    p_play.add_argument("--index", type=int, help="按队列索引播放")
    p_play.add_argument("--keyword", help="按关键词搜索后播放第一首")
    p_play.add_argument("--fake", action="store_true", help="使用 fake 音乐源")
    p_play.set_defaults(func=_cmd_play)

    # pause / resume / stop / next / previous
    for action in ("pause", "resume", "stop", "next", "previous"):
        p = sub.add_parser(action, help=f"{action} 播放")
        p.add_argument("--fake", action="store_true", help="使用 fake 音乐源")
        p.set_defaults(func=_cmd_simple(action))

    # seek
    p_seek = sub.add_parser("seek", help="跳转播放进度")
    p_seek.add_argument("position_s", type=int, help="目标进度（秒）")
    p_seek.add_argument("--fake", action="store_true", help="使用 fake 音乐源")
    p_seek.set_defaults(func=_cmd_seek)

    # repeat
    p_repeat = sub.add_parser("repeat", help="设置循环模式")
    p_repeat.add_argument(
        "mode",
        choices=["single", "list_loop", "random", "sequence"],
        help="循环模式",
    )
    p_repeat.add_argument("--fake", action="store_true", help="使用 fake 音乐源")
    p_repeat.set_defaults(func=_cmd_repeat)

    # state
    p_state = sub.add_parser("state", help="获取播放器状态")
    p_state.add_argument("--fake", action="store_true", help="使用 fake 音乐源")
    p_state.set_defaults(func=_cmd_state)

    # login
    p_login = sub.add_parser("login", help="发起扫码登录")
    p_login.add_argument("--fake", action="store_true", help="使用 fake 音乐源")
    p_login.set_defaults(func=_cmd_login)

    # login-check
    p_check = sub.add_parser("login-check", help="轮询扫码登录状态")
    p_check.add_argument("key", help="login 返回的 key")
    p_check.add_argument("--fake", action="store_true", help="使用 fake 音乐源")
    p_check.set_defaults(func=_cmd_login_check)

    # ------------------------------------------------------------------
    # M19 本地音乐库子命令
    # ------------------------------------------------------------------
    # library-scan
    p_lscan = sub.add_parser("library-scan", help="扫描本地音乐库写入 SQLite 索引")
    p_lscan.add_argument("--root", dest="root_dir", default=None, help="扫描根目录")
    p_lscan.add_argument("--fake", action="store_true", help="使用 fake 扫描器")
    p_lscan.set_defaults(func=_cmd_library_scan)

    # library-search
    p_lsearch = sub.add_parser("library-search", help="FTS5 全文搜索音乐库")
    p_lsearch.add_argument("query", help="搜索关键词")
    p_lsearch.add_argument("--limit", type=int, default=20, help="返回上限")
    p_lsearch.add_argument("--fake", action="store_true", help="使用 fake 模式")
    p_lsearch.set_defaults(func=_cmd_library_search)

    # library-status
    p_lstatus = sub.add_parser("library-status", help="查询音乐库状态")
    p_lstatus.add_argument("--fake", action="store_true", help="使用 fake 模式")
    p_lstatus.set_defaults(func=_cmd_library_status)

    # playlist-create
    p_pcreate = sub.add_parser("playlist-create", help="创建歌单")
    p_pcreate.add_argument("name", help="歌单名称")
    p_pcreate.add_argument("--fake", action="store_true", help="使用 fake 模式")
    p_pcreate.set_defaults(func=_cmd_playlist_create)

    # playlist-add
    p_padd = sub.add_parser("playlist-add", help="向歌单添加歌曲")
    p_padd.add_argument("playlist_id", type=int, help="歌单 ID")
    p_padd.add_argument("song_id", help="歌曲 ID")
    p_padd.add_argument("--position", type=int, default=None, help="插入位置")
    p_padd.add_argument("--fake", action="store_true", help="使用 fake 模式")
    p_padd.set_defaults(func=_cmd_playlist_add)

    # playlist-remove
    p_premove = sub.add_parser("playlist-remove", help="从歌单移除歌曲")
    p_premove.add_argument("playlist_id", type=int, help="歌单 ID")
    p_premove.add_argument("song_id", help="歌曲 ID")
    p_premove.add_argument("--fake", action="store_true", help="使用 fake 模式")
    p_premove.set_defaults(func=_cmd_playlist_remove)

    # playlist-list
    p_plist = sub.add_parser("playlist-list", help="列出歌单或歌单内歌曲")
    p_plist.add_argument("--playlist-id", type=int, default=None, help="歌单 ID（缺省列全部歌单）")
    p_plist.add_argument("--fake", action="store_true", help="使用 fake 模式")
    p_plist.set_defaults(func=_cmd_playlist_list)

    # decrypt
    p_dec = sub.add_parser("decrypt", help="解密加密音频文件（仅已购买内容，D19.1 合规）")
    p_dec.add_argument("path", help="加密源文件路径")
    p_dec.add_argument("--output", default=None, help="自定义输出路径")
    p_dec.add_argument(
        "--confirm",
        action="store_true",
        help="确认已合法购买该内容（安全门，必须传）",
    )
    p_dec.add_argument("--fake", action="store_true", help="使用 fake 模式")
    p_dec.set_defaults(func=_cmd_decrypt)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：解析参数并派发到对应子命令。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
