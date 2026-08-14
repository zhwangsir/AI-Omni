"""omni_voice 命令行入口：``python -m omni_voice <子命令>``。

CLI 是 tools 层的薄壳：解析参数 → 调用 tools → 打印 JSON → 映射退出码
（ok:true → 0，ok:false → 1；参数解析错误返回 E_INVALID_PARAMS JSON 并退出 1）。

子命令：

- ``status``                          ：打印管道状态与配置摘要
- ``identity``                        ：获取助手身份信息（名字、唤醒词等）
- ``speak TEXT [--fake]``             ：一次性 TTS 播报
- ``listen-once [--fake] [--timeout S] [--no-speak]`` ：一次性 听→想→说
- ``run [--fake] [--duration S]``     ：启动常驻管道（Ctrl-C 或到时停止）
- ``config get`` / ``config set KEY VALUE`` ：配置读写
- ``interrupt``                       ：写控制文件打断宿主管道当前播报（M7.5）

``--fake`` 使用可编程 fake 后端，并由 CLI 预置演示脚本，
无需音频硬件/模型/网络即可演示完整交互链路。
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from omni_sdk.cli_utils import JsonErrorArgumentParser

from . import tools


# ---------------------------------------------------------------------------
# fake 演示脚本
# ---------------------------------------------------------------------------
def _script_fake_demo(rt: tools.Runtime, *, scenario: str) -> None:
    """为 --fake 演示预置脚本化组件：让演示输出完整、确定的交互内容。"""
    from .agent_bridge import FakeAgentBridge
    from .backends.fakes import FakeASR, FakePlayer, FakeTTS, FakeVAD, FakeWakeWord

    silence = rt.config.vad_silence_ms // rt.config.frame_ms
    if scenario == "listen":
        wake = FakeWakeWord()
        vad = FakeVAD(results=[True] * 5 + [False] * (silence + 5))
        asr = FakeASR(transcripts=["你好，Omni"])
        agent = FakeAgentBridge(replies=["你好！我是 Omni，很高兴为你服务。"])
    else:  # run：先唤醒一帧，再走完整 录音→转写→思考→播报
        wake = FakeWakeWord(confidences=[0.95])
        vad = FakeVAD(results=[True, True] + [False] * (silence + 5))
        asr = FakeASR(transcripts=["今天天气怎么样？"])
        agent = FakeAgentBridge(
            replies=["我这边没有实时天气数据，建议看看窗外或天气应用。"]
        )
    rt.components = {
        "wake": wake,
        "vad": vad,
        "asr": asr,
        "tts": FakeTTS(),
        "player": FakePlayer(),
        "agent": agent,
    }


class _EventPrinter:
    """事件打印器：满足 publish(event_type, payload) 鸭子类型，逐行输出。"""

    def __init__(self):
        self._lock = threading.Lock()

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        line = f"[event] {event_type} {json.dumps(payload, ensure_ascii=False)}"
        with self._lock:
            print(line, flush=True)


# ---------------------------------------------------------------------------
# 输出辅助
# ---------------------------------------------------------------------------
def _emit(result_json: str) -> int:
    """打印工具返回的 JSON，并按 ok 字段映射退出码。"""
    print(result_json)
    return 0 if json.loads(result_json).get("ok") else 1


# ---------------------------------------------------------------------------
# 子命令处理
# ---------------------------------------------------------------------------
def _cmd_status(args: argparse.Namespace) -> int:
    return _emit(tools.voice_status())


def _cmd_speak(args: argparse.Namespace) -> int:
    return _emit(tools.voice_speak(args.text, fake=args.fake))


def _cmd_listen_once(args: argparse.Namespace) -> int:
    rt = tools._runtime
    if args.fake:
        _script_fake_demo(rt, scenario="listen")
    return _emit(
        tools.voice_listen_once(
            timeout_s=args.timeout, speak=not args.no_speak, fake=args.fake
        )
    )


def _cmd_run(args: argparse.Namespace) -> int:
    rt = tools._runtime
    if args.fake:
        _script_fake_demo(rt, scenario="run")
    rt.event_publisher = _EventPrinter()
    started = json.loads(tools.voice_pipeline_start(fake=args.fake))
    if not started["ok"]:
        return _emit(json.dumps(started, ensure_ascii=False))
    print(f"语音管道已启动（state={started['data']['state']}），等待唤醒中…… Ctrl-C 停止")
    try:
        if args.duration is None:
            while True:  # 常驻模式：直到 Ctrl-C
                time.sleep(0.5)
        else:
            time.sleep(args.duration)
    except KeyboardInterrupt:
        print("收到中断，正在停止管道……")
    tools.voice_pipeline_stop()
    return _emit(tools.voice_status())


def _cmd_config(args: argparse.Namespace) -> int:
    if args.config_action == "get":
        return _emit(tools.voice_config(action="get"))
    return _emit(tools.voice_config(action="set", key=args.key, value=args.value))


def _cmd_interrupt(args: argparse.Namespace) -> int:
    return _emit(tools.voice_interrupt())


def _cmd_identity(args: argparse.Namespace) -> int:
    return _emit(tools.voice_identity())


# ---------------------------------------------------------------------------
# 解析器
# ---------------------------------------------------------------------------
def build_parser() -> JsonErrorArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = JsonErrorArgumentParser(
        prog="omni_voice",
        description="本地语音交互 MVP：唤醒 → VAD → ASR → LLM Agent → TTS",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="打印管道状态与配置摘要")
    p_status.set_defaults(func=_cmd_status)

    p_speak = sub.add_parser("speak", help="一次性 TTS 播报文本")
    p_speak.add_argument("text", help="要播报的文本")
    p_speak.add_argument("--fake", action="store_true", help="使用 fake 后端演示")
    p_speak.set_defaults(func=_cmd_speak)

    p_listen = sub.add_parser("listen-once", help="一次性 听→转写→对话→播报")
    p_listen.add_argument("--fake", action="store_true", help="使用 fake 后端演示")
    p_listen.add_argument(
        "--timeout", type=float, default=10.0, help="最长录音秒数（默认 10）"
    )
    p_listen.add_argument(
        "--no-speak", action="store_true", help="只转写与对话，不播报回复"
    )
    p_listen.set_defaults(func=_cmd_listen_once)

    p_run = sub.add_parser("run", help="启动常驻语音管道（唤醒循环）")
    p_run.add_argument("--fake", action="store_true", help="使用 fake 后端演示")
    p_run.add_argument(
        "--duration",
        type=float,
        default=None,
        help="运行秒数；缺省时常驻直到 Ctrl-C",
    )
    p_run.set_defaults(func=_cmd_run)

    p_config = sub.add_parser("config", help="配置读写")
    config_sub = p_config.add_subparsers(dest="config_action", required=True)
    p_config_get = config_sub.add_parser("get", help="打印配置摘要")
    p_config_get.set_defaults(func=_cmd_config)
    p_config_set = config_sub.add_parser("set", help="修改运行时可调配置项")
    p_config_set.add_argument("key", help="配置项名（须在可调名单内）")
    p_config_set.add_argument("value", help="新值（数值型自动转换与校验）")
    p_config_set.set_defaults(func=_cmd_config)

    p_interrupt = sub.add_parser(
        "interrupt", help="打断宿主管道当前播报（写控制文件，M7.5）"
    )
    p_interrupt.set_defaults(func=_cmd_interrupt)

    p_identity = sub.add_parser(
        "identity", help="获取助手身份信息（名字、唤醒词、人设等）"
    )
    p_identity.set_defaults(func=_cmd_identity)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：解析参数并分发到子命令，返回进程退出码。"""
    args = build_parser().parse_args(argv)
    return args.func(args)
