"""omni_weather 命令行入口：``python -m omni_weather <子命令>``。

CLI 是 tools 层的薄壳：解析参数 → 调用 tools → 打印 JSON → 映射退出码
（ok:true → 0，ok:false → 1；参数解析错误返回 E_INVALID_PARAMS JSON 并退出 1）。

子命令：

- ``status [--fake]``                          ：插件状态（cache/位置/最后更新）
- ``get [--fake]``                             ：获取当前天气 + 情绪 + 家居建议
- ``forecast [--fake]``                        ：24h 预报
- ``set-location CITY [--lat L --lon L] [--fake]``：设置城市
- ``search KEYWORD [--limit N] [--fake]``      ：搜索城市
- ``refresh [--fake]``                         ：强制刷新缓存
- ``call <tool> [--args JSON] [--fake]``       ：通用工具调用（Rust 桥接入口）

``--fake`` 仅在工具 schema 声明 fake 参数时透传（参考 omni_lyrics/cli.py）。
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


def _find_tool_meta(name: str):
    """按 name 在 TOOLS 注册表里查 meta；未找到返回 None。"""
    for meta in tools.TOOLS:
        if meta["name"] == name:
            return meta
    return None


# ---------------------------------------------------------------------------
# 通用 call 子命令（Rust weather_tool 桥接入口）
# ---------------------------------------------------------------------------
def _cmd_call(args: argparse.Namespace) -> int:
    try:
        kwargs = json.loads(args.args) if args.args else {}
    except ValueError as exc:
        return _emit(tools._err("E_INVALID_ARGS", f"--args 不是合法 JSON: {exc}"))
    if not isinstance(kwargs, dict):
        return _emit(tools._err("E_INVALID_ARGS", "--args 顶层必须是 JSON 对象"))
    # 合并 fake 标志
    fake = bool(kwargs.get("fake", False)) or args.fake
    if fake:
        tools._runtime.use_fake_backends = True
    handler = _find_tool(args.tool)
    if handler is None:
        return _emit(tools._err("E_INVALID_ARGS", f"未知工具: {args.tool}"))
    # 仅当工具 schema 声明了 fake 参数时才注入
    meta = _find_tool_meta(args.tool)
    if meta and "fake" in meta["schema"]["parameters"]["properties"]:
        kwargs["fake"] = fake
    return _emit(handler(**kwargs))


# ---------------------------------------------------------------------------
# 具名子命令
# ---------------------------------------------------------------------------
def _cmd_status(args: argparse.Namespace) -> int:
    return _emit(tools.weather_status(fake=args.fake))


def _cmd_get(args: argparse.Namespace) -> int:
    return _emit(tools.weather_get(fake=args.fake))


def _cmd_forecast(args: argparse.Namespace) -> int:
    return _emit(tools.weather_forecast(fake=args.fake))


def _cmd_set_location(args: argparse.Namespace) -> int:
    return _emit(
        tools.weather_set_location(
            city=args.city, lat=args.lat, lon=args.lon, fake=args.fake
        )
    )


def _cmd_search(args: argparse.Namespace) -> int:
    return _emit(tools.weather_search_city(keyword=args.keyword, limit=args.limit, fake=args.fake))


def _cmd_refresh(args: argparse.Namespace) -> int:
    return _emit(tools.weather_refresh(fake=args.fake))


def build_parser() -> JsonErrorArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = JsonErrorArgumentParser(
        prog="omni_weather",
        description="天气情绪电台：Open-Meteo + 情绪映射 + 视觉/音乐/家居联动建议",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # status
    p_status = sub.add_parser("status", help="打印插件状态（cache/位置/最后更新）")
    p_status.add_argument("--fake", action="store_true", help="使用 fake 后端（演示/测试）")
    p_status.set_defaults(func=_cmd_status)

    # get
    p_get = sub.add_parser("get", help="获取当前天气 + 情绪 + 家居建议")
    p_get.add_argument("--fake", action="store_true", help="使用 fake 后端（演示/测试）")
    p_get.set_defaults(func=_cmd_get)

    # forecast
    p_forecast = sub.add_parser("forecast", help="获取 24 小时预报")
    p_forecast.add_argument("--fake", action="store_true", help="使用 fake 后端（演示/测试）")
    p_forecast.set_defaults(func=_cmd_forecast)

    # set-location
    p_set = sub.add_parser("set-location", help="设置当前城市并持久化")
    p_set.add_argument("city", help="城市名（如：北京 / Shanghai）")
    p_set.add_argument("--lat", type=float, default=None, help="纬度（与 --lon 一起传入时跳过 geocoding）")
    p_set.add_argument("--lon", type=float, default=None, help="经度（与 --lat 一起传入时跳过 geocoding）")
    p_set.add_argument("--fake", action="store_true", help="使用 fake 后端（演示/测试）")
    p_set.set_defaults(func=_cmd_set_location)

    # search
    p_search = sub.add_parser("search", help="搜索城市")
    p_search.add_argument("keyword", help="城市名关键词")
    p_search.add_argument("--limit", type=int, default=5, help="返回上限（默认 5）")
    p_search.add_argument("--fake", action="store_true", help="使用 fake 后端（演示/测试）")
    p_search.set_defaults(func=_cmd_search)

    # refresh
    p_refresh = sub.add_parser("refresh", help="强制刷新天气缓存")
    p_refresh.add_argument("--fake", action="store_true", help="使用 fake 后端（演示/测试）")
    p_refresh.set_defaults(func=_cmd_refresh)

    # call（通用工具调用，Rust 桥接入口）
    p_call = sub.add_parser("call", help="通用工具调用（tool 名 + JSON 参数）")
    p_call.add_argument("tool", help="工具名，如 weather_get / weather_search_city")
    p_call.add_argument(
        "--args",
        default="",
        help='工具参数 JSON 字符串，如 \'{"keyword":"北京","fake":true}\'',
    )
    p_call.add_argument("--fake", action="store_true", help="使用 fake 后端（演示/测试）")
    p_call.set_defaults(func=_cmd_call)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：解析参数并派发到对应子命令。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "fake", False):
        tools._runtime.use_fake_backends = True
    return args.func(args)
