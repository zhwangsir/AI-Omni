"""omni_home 命令行入口：``python -m omni_home <子命令>``。

CLI 是 tools 层的薄壳：解析参数 → 调用 tools → 打印 JSON → 映射退出码
（ok:true → 0，ok:false → 1；参数解析错误返回 E_INVALID_PARAMS JSON 并退出 1）。

子命令：

- ``status [--fake]``                       ：插件状态与配置摘要
- ``refresh [--fake]``                      ：拉取实体并重建知识图谱
- ``control TEXT [--fake]``                 ：自然语言控制指令
- ``query TEXT [--fake]``                   ：自然语言状态查询
- ``list [--room R] [--domain D] [--fake]`` ：家庭结构 / 设备清单
- ``config get`` / ``config set KEY VALUE`` ：配置读写

``--fake`` 使用演示家庭 fake 客户端，无需真实 Home Assistant 即可演示完整链路。
"""

from __future__ import annotations

import json

from omni_sdk.cli_utils import JsonErrorArgumentParser

from . import tools


def _emit(result_json: str) -> int:
    """打印工具返回的 JSON，并按 ok 字段映射退出码。"""
    print(result_json)
    return 0 if json.loads(result_json).get("ok") else 1


def _cmd_status(args: argparse.Namespace) -> int:
    return _emit(tools.home_status(fake=args.fake))


def _cmd_refresh(args: argparse.Namespace) -> int:
    return _emit(tools.home_refresh(fake=args.fake))


def _cmd_control(args: argparse.Namespace) -> int:
    return _emit(tools.home_control(args.text, fake=args.fake))


def _cmd_query(args: argparse.Namespace) -> int:
    return _emit(tools.home_query(args.text, fake=args.fake))


def _cmd_list(args: argparse.Namespace) -> int:
    return _emit(tools.home_list(room=args.room, domain=args.domain, fake=args.fake))


def _cmd_config(args: argparse.Namespace) -> int:
    if args.config_action == "get":
        return _emit(tools.home_config(action="get"))
    return _emit(tools.home_config(action="set", key=args.key, value=args.value))


def build_parser() -> JsonErrorArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = JsonErrorArgumentParser(
        prog="omni_home",
        description="智能家居控制：Home Assistant 桥接 + 自然语言设备控制",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="打印插件状态与配置摘要")
    p_status.add_argument("--fake", action="store_true", help="使用演示家庭 fake 客户端")
    p_status.set_defaults(func=_cmd_status)

    p_refresh = sub.add_parser("refresh", help="拉取实体并重建知识图谱缓存")
    p_refresh.add_argument("--fake", action="store_true", help="使用演示家庭 fake 客户端")
    p_refresh.set_defaults(func=_cmd_refresh)

    p_control = sub.add_parser("control", help="执行自然语言控制指令")
    p_control.add_argument("text", help="中文控制指令，如：把客厅空调调到26度")
    p_control.add_argument("--fake", action="store_true", help="使用演示家庭 fake 客户端")
    p_control.set_defaults(func=_cmd_control)

    p_query = sub.add_parser("query", help="执行自然语言状态查询")
    p_query.add_argument("text", help="中文查询指令，如：客厅灯开着吗")
    p_query.add_argument("--fake", action="store_true", help="使用演示家庭 fake 客户端")
    p_query.set_defaults(func=_cmd_query)

    p_list = sub.add_parser("list", help="列出家庭结构 / 设备清单")
    p_list.add_argument("--room", default="", help="按房间过滤（如 客厅）")
    p_list.add_argument("--domain", default="", help="按品类过滤（如 light）")
    p_list.add_argument("--fake", action="store_true", help="使用演示家庭 fake 客户端")
    p_list.set_defaults(func=_cmd_list)

    p_config = sub.add_parser("config", help="配置读写")
    config_sub = p_config.add_subparsers(dest="config_action", required=True)
    p_config_get = config_sub.add_parser("get", help="打印配置摘要")
    p_config_get.set_defaults(func=_cmd_config)
    p_config_set = config_sub.add_parser("set", help="修改运行时可调配置项")
    p_config_set.add_argument("key", help="配置项名（须在可调名单内）")
    p_config_set.add_argument("value", help="新值（数值型自动转换与校验）")
    p_config_set.set_defaults(func=_cmd_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：解析参数并分发到子命令，返回进程退出码。"""
    args = build_parser().parse_args(argv)
    return args.func(args)
