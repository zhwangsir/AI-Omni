"""omni_music 工具实现（M17.9 完整 12 工具）。

M17.1-M17.4 阶段注册 2 个占位工具；M17.9 扩展为完整 12 工具：

- ``music_search``              ：搜索歌曲（返回 Song 元数据列表）
- ``music_get_login_qr``        ：发起扫码登录，返回 key + qr_url
- ``music_check_login_status``  ：轮询扫码登录状态
- ``music_play``                ：播放（song_id / index / keyword / 恢复）
- ``music_pause``               ：暂停
- ``music_resume``              ：恢复
- ``music_stop``                ：停止
- ``music_next``                ：下一首
- ``music_previous``            ：上一首
- ``music_seek``                ：跳转进度
- ``music_set_repeat_mode``     ：设置循环模式
- ``music_get_player_state``    ：获取播放器状态

工具统一返回 JSON 字符串 ``{"ok": true, "data": ...}`` / ``{"ok": false, "error": {...}}``。
重型依赖（httpx 等）惰性导入，测试全用 FakeMusicSource / FakeQRLoginFlow。
MusicPlayer 为纯逻辑无音频依赖（M17.8），可直接参与测试。

播放器状态推送：每次播放控制工具调用后，把 ``player.to_state_dict()`` 原子写入
``~/.ai-omni/state/music_state.json``（参考 omni_voice/state_file.py 模式，独立实现，
不 import omni_voice）；写入失败静默吞掉，不拖垮调用方。

合规说明（D17.4）：仅免费/试听曲目，VIP 曲目提示需登录，不提供破解。
仅个人学习用途。
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

from omni_music.auth.cookie_store import FakeCookieStore
from omni_music.auth.qr_login import FakeQRLoginFlow, QRLoginFlow
from omni_music.models import Song
from omni_music.player import MusicPlayer, RepeatMode
from omni_music.sources.base import FakeMusicSource, MusicSource

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# state_file 路径（env 可覆盖，便于测试）
# ---------------------------------------------------------------------------
_DEFAULT_STATE_FILE = Path.home() / ".ai-omni" / "state" / "music_state.json"


def _state_file_path() -> Path:
    """取 state_file 路径；env ``AI_OMNI_MUSIC_STATE_FILE`` 优先。"""
    env = os.environ.get("AI_OMNI_MUSIC_STATE_FILE")
    if env:
        return Path(env)
    return _DEFAULT_STATE_FILE


def _write_state_file(player: MusicPlayer) -> None:
    """原子写入 player 状态到 state_file；失败静默。

    采用 临时文件 + ``os.replace`` 原子替换，读者不会读到半截 JSON。
    父目录不存在时自动创建；任何异常均吞掉（观察通道静默降级）。
    """
    path = _state_file_path()
    tmp: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = player.to_state_dict()
        payload["ts"] = time.time()
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001 - 观察通道静默降级
        logger.debug("music state_file 写入失败: %s", path, exc_info=True)
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def load_player_from_state_file(rt: Runtime, fake: bool) -> MusicPlayer | None:
    """从 state_file 恢复 player 到运行时；文件不存在或解析失败时返回 None。

    供 CLI 桥（``omni_music/cli.py``）在每次子进程启动时调用，使跨 CLI 调用的
    有状态播放（队列/当前曲目/循环模式）经 state_file 持久化串联——
    与 omni_voice control_file/state_file 同款模式。

    :param rt: 运行时（``rt.player`` 未预置时才加载）
    :param fake: 为 True 时确保 source 为 FakeMusicSource
    :return: 恢复后的 :class:`MusicPlayer`；文件不存在/无源/解析失败返回 None
    """
    if rt.player is not None:
        return rt.player
    source = _get_source(rt, fake)
    if source is None:
        return None
    path = _state_file_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.debug("music state_file 读取失败: %s", path, exc_info=True)
        return None
    try:
        rt.player = MusicPlayer.from_state_dict(data, source=source)
    except Exception:  # noqa: BLE001 - 状态文件损坏不拖垮 CLI
        logger.debug("music state_file 恢复失败: %s", path, exc_info=True)
        return None
    return rt.player


# ---------------------------------------------------------------------------
# 运行时单例：持有当前 MusicSource / CookieStore / QRLoginFlow / MusicPlayer
# ---------------------------------------------------------------------------
class Runtime:
    """进程内运行时：持有音乐源、Cookie 存储、扫码登录流程、播放器。

    ``source`` 可由测试/CLI 预置为 fake 或真实源；``store`` 同理。
    未预置时按 ``fake`` 参数构造默认 fake 实例。
    ``player`` 由 :func:`_get_player` 惰性构造，绑定当前 source。
    """

    def __init__(self) -> None:
        self.source: MusicSource | None = None
        self.store: Any = None
        self.flow: QRLoginFlow | None = None
        self.player: MusicPlayer | None = None
        self.fake_mode: bool = False
        self.event_publisher: Any = None
        self.volume_gain: float = 1.0


_runtime = Runtime()


def _reset_runtime(runtime: Runtime | None = None) -> Runtime:
    """替换进程内运行时（测试隔离用），返回新实例。"""
    global _runtime
    _runtime = runtime or Runtime()
    return _runtime


def _publish_event(event_type: str, payload: dict[str, Any]) -> None:
    """安全发布事件到事件总线（若已接入）。"""
    rt = _runtime
    publisher = rt.event_publisher
    if publisher is None or not callable(getattr(publisher, "publish", None)):
        return
    try:
        payload_with_meta = {
            **payload,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "source": "omni_music",
        }
        from omni_sdk.utils import sync_to_async_publish

        sync_to_async_publish(publisher.publish, event_type, payload_with_meta)
    except Exception:  # noqa: BLE001
        logger.debug("事件发布失败: %s", event_type, exc_info=True)


# ---------------------------------------------------------------------------
# JSON 响应约定
# ---------------------------------------------------------------------------
def _ok(data: Any) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False)


def _err(code: str, message: str) -> str:
    return json.dumps(
        {"ok": False, "error": {"code": code, "message": message}},
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# 后端选择
# ---------------------------------------------------------------------------
def _get_source(rt: Runtime, fake: bool) -> MusicSource | None:
    """取当前音乐源；未预置时按 fake 标志构造默认 fake 源。"""
    if fake:
        rt.fake_mode = True
    if rt.source is not None:
        return rt.source
    if fake:
        rt.source = FakeMusicSource()
        return rt.source
    # 真实源在 M17.5-M17.7 实现；当前未实现时返回 None
    logger.warning("未配置真实音乐源（M17.5-M17.7 实现）；请使用 fake=True")
    return None


def _get_store(rt: Runtime, fake: bool) -> Any:
    """取当前 CookieStore；未预置时按 fake 标志构造。"""
    if rt.store is not None:
        return rt.store
    if fake:
        rt.store = FakeCookieStore()
        return rt.store
    # 真实 CookieStore 需要 cryptography；惰性构造
    from omni_music.auth.cookie_store import CookieStore

    rt.store = CookieStore()
    return rt.store


def _get_player(rt: Runtime, fake: bool) -> MusicPlayer | None:
    """取当前播放器；未预置时用当前 source 构造 :class:`MusicPlayer`。

    :param rt: 运行时
    :param fake: 为 True 时确保 source 为 FakeMusicSource（经 :func:`_get_source`）
    :return: :class:`MusicPlayer` 实例；源不可用时返回 None
    """
    if rt.player is not None:
        return rt.player
    source = _get_source(rt, fake)
    if source is None:
        return None
    rt.player = MusicPlayer(source=source)
    return rt.player


# ---------------------------------------------------------------------------
# Tool 元数据注册表
# ---------------------------------------------------------------------------
TOOLS: list[dict[str, Any]] = []


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    required: list[str] | None = None,
    emoji: str = "",
) -> Callable:
    """@tool 装饰器：为函数附加 tool schema 元数据并登记到 TOOLS。"""

    def decorator(func: Callable) -> Callable:
        TOOLS.append(
            {
                "name": name,
                "description": description,
                "emoji": emoji,
                "schema": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": parameters,
                        "required": list(required or []),
                    },
                },
                "handler_func": func,
            }
        )
        return func

    return decorator


_FAKE_PARAM = {
    "type": "boolean",
    "description": "为 true 时使用 fake 后端（演示/测试，不访问真实音乐 API）。",
}

# RepeatMode 字符串 → 枚举映射（music_set_repeat_mode 用）
_REPEAT_MODE_MAP: dict[str, RepeatMode] = {
    "single": RepeatMode.SINGLE,
    "list_loop": RepeatMode.LIST_LOOP,
    "random": RepeatMode.RANDOM,
    "sequence": RepeatMode.SEQUENCE,
}


# ---------------------------------------------------------------------------
# Tool 1：搜索歌曲
# ---------------------------------------------------------------------------
@tool(
    name="music_search",
    description="搜索歌曲：按关键词返回歌曲元数据列表（歌曲名/艺术家/专辑/时长/URL/封面）。"
    "仅返回免费/试听曲目；VIP 曲目会标记需登录。",
    parameters={
        "keyword": {
            "type": "string",
            "description": "搜索关键词（歌曲名/歌手名/专辑名）",
        },
        "limit": {
            "type": "integer",
            "description": "返回上限，默认 20",
            "default": 20,
        },
        "fake": _FAKE_PARAM,
    },
    required=["keyword"],
    emoji="🎵",
)
def music_search(keyword: str, limit: int = 20, fake: bool = False) -> str:
    """搜索歌曲；返回 Song 元数据列表。"""
    try:
        rt = _runtime
        source = _get_source(rt, fake)
        if source is None:
            return _err("E_BACKEND_UNAVAILABLE", "未配置音乐源（M17.5-M17.7 实现）")
        songs = source.search(keyword, limit=limit)
        return _ok({"songs": [s.to_dict() for s in songs], "count": len(songs)})
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_search 失败: %s", exc)
        return _err("E_SEARCH_FAILED", str(exc))


# ---------------------------------------------------------------------------
# Tool 2：发起扫码登录
# ---------------------------------------------------------------------------
@tool(
    name="music_get_login_qr",
    description="发起音乐源扫码登录：返回二维码 key 与 qr_url。"
    "调用方展示 qr_url 给用户扫码，后续轮询 music_check_login_status 查询状态。",
    parameters={
        "fake": _FAKE_PARAM,
    },
    emoji="📱",
)
def music_get_login_qr(fake: bool = False) -> str:
    """发起扫码登录；返回 key + qr_url。"""
    try:
        rt = _runtime
        source = _get_source(rt, fake)
        if source is None:
            return _err("E_BACKEND_UNAVAILABLE", "未配置音乐源（M17.5-M17.7 实现）")
        store = _get_store(rt, fake)
        # 构造扫码登录流程
        if fake:
            rt.flow = FakeQRLoginFlow(source=source, store=store)
        else:
            rt.flow = QRLoginFlow(source=source, store=store)
        result = rt.flow.start()
        return _ok(
            {
                "key": result.get("key", ""),
                "qr_url": result.get("qr_url", ""),
                "source": source.source.value,
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_get_login_qr 失败: %s", exc)
        return _err("E_LOGIN_QR_FAILED", str(exc))


# ---------------------------------------------------------------------------
# Tool 3：轮询扫码登录状态
# ---------------------------------------------------------------------------
@tool(
    name="music_check_login_status",
    description="轮询音乐源扫码登录状态：返回 waiting/scanned/confirmed/expired/timeout。"
    "confirmed 时 cookie 已自动保存；需先调用 music_get_login_qr 获取 key。",
    parameters={
        "key": {
            "type": "string",
            "description": "music_get_login_qr 返回的二维码 key",
        },
        "fake": _FAKE_PARAM,
    },
    required=["key"],
    emoji="🔄",
)
def music_check_login_status(key: str, fake: bool = False) -> str:
    """轮询扫码登录状态；返回状态字符串。"""
    try:
        rt = _runtime
        if rt.flow is None:
            return _err("E_LOGIN_FAILED", "未发起扫码登录，请先调用 music_get_login_qr")
        flow_key = getattr(rt.flow, "_key", None)
        if not flow_key:
            return _err("E_LOGIN_FAILED", "扫码登录未启动（flow._key 为空）")
        if flow_key != key:
            return _err("E_LOGIN_FAILED", f"key 不匹配: 期望 {flow_key} 收到 {key}")
        status = rt.flow.poll()
        data: dict[str, Any] = {"status": status, "key": key}
        if status == "confirmed":
            data["cookie_saved"] = True
        return _ok(data)
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_check_login_status 失败: %s", exc)
        return _err("E_LOGIN_FAILED", str(exc))


# ---------------------------------------------------------------------------
# Tool 4：播放
# ---------------------------------------------------------------------------
@tool(
    name="music_play",
    description="播放音乐：支持四种模式——传 song_id 则追加该曲并播放；"
    "传 index 则播放队列指定索引；传 keyword 则搜索第一首追加并播放；"
    "都不传则恢复当前曲目。返回当前 Song 与 player_state。",
    parameters={
        "song_id": {
            "type": "string",
            "description": "歌曲 ID：将该曲追加到队列末尾并立即播放",
        },
        "index": {
            "type": "integer",
            "description": "播放队列中指定索引（从 0 起）；越界返回 E_INVALID_ARGS",
        },
        "keyword": {
            "type": "string",
            "description": "搜索关键词：取第一首匹配追加到队列并播放",
        },
        "fake": _FAKE_PARAM,
    },
    emoji="▶️",
)
def music_play(
    song_id: str | None = None,
    index: int | None = None,
    keyword: str | None = None,
    fake: bool = False,
) -> str:
    """播放音乐；返回当前 Song + player_state。"""
    try:
        rt = _runtime
        player = _get_player(rt, fake)
        if player is None:
            return _err("E_BACKEND_UNAVAILABLE", "未配置音乐源（M17.5-M17.7 实现）")
        if song_id is not None:
            source = _get_source(rt, fake)
            if source is None:
                return _err("E_BACKEND_UNAVAILABLE", "未配置音乐源")
            try:
                song = source.get_song_detail(song_id)
            except Exception as exc:  # noqa: BLE001 - source 故障归搜索失败
                logger.debug("music_play get_song_detail 失败: %s", exc)
                return _err("E_SEARCH_FAILED", str(exc))
            if song is None:
                return _err("E_SEARCH_FAILED", f"未找到歌曲: {song_id}")
            player.add_to_queue(song)
            player.play(player.queue_length - 1)
        elif index is not None:
            try:
                player.play(index)
            except IndexError:
                return _err(
                    "E_INVALID_ARGS",
                    f"index 越界: {index}（队列长度 {player.queue_length}）",
                )
        elif keyword is not None:
            source = _get_source(rt, fake)
            if source is None:
                return _err("E_BACKEND_UNAVAILABLE", "未配置音乐源")
            try:
                songs = source.search(keyword, limit=1)
            except Exception as exc:  # noqa: BLE001 - source 故障归搜索失败
                logger.debug("music_play search 失败: %s", exc)
                return _err("E_SEARCH_FAILED", str(exc))
            if not songs:
                return _err("E_SEARCH_FAILED", f"未找到匹配歌曲: {keyword}")
            song = songs[0]
            player.add_to_queue(song)
            player.play(player.queue_length - 1)
        else:
            # 无参：恢复当前（队列空时 play 返回 None，不算错误）
            player.play()
        _write_state_file(player)
        current = player.current_song
        if current is not None and player.is_playing:
            _publish_event(
                "music.started",
                {
                    "track_id": current.id,
                    "title": current.name,
                    "artists": current.artists,
                    "state": player.current_state.value,
                },
            )
        # 扁平返回 player 全状态（to_state_dict 已含 current_song/queue/state 等），
        # 与前端 normalizePlayerState(data) 平铺契约对齐——data.queue / data.state 直接可读。
        return _ok(player.to_state_dict())
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_play 失败: %s", exc)
        return _err("E_INVALID_ARGS", str(exc))


# ---------------------------------------------------------------------------
# Tool 5：暂停
# ---------------------------------------------------------------------------
@tool(
    name="music_pause",
    description="暂停当前播放：要求当前为播放态（playing），否则返回 E_STATE_VIOLATION。",
    parameters={"fake": _FAKE_PARAM},
    emoji="⏸️",
)
def music_pause(fake: bool = False) -> str:
    """暂停播放；返回 player_state。"""
    try:
        rt = _runtime
        player = _get_player(rt, fake)
        if player is None:
            return _err("E_PLAYER_NOT_READY", "播放器未初始化（未配置音乐源）")
        try:
            player.pause()
        except RuntimeError as exc:
            return _err("E_STATE_VIOLATION", str(exc))
        _write_state_file(player)
        current = player.current_song
        _publish_event(
            "music.paused",
            {
                "track_id": current.id if current else None,
                "state": player.current_state.value,
            },
        )
        return _ok(player.to_state_dict())
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_pause 失败: %s", exc)
        return _err("E_INVALID_ARGS", str(exc))


# ---------------------------------------------------------------------------
# Tool 6：恢复
# ---------------------------------------------------------------------------
@tool(
    name="music_resume",
    description="恢复播放：要求当前为暂停态（paused），否则返回 E_STATE_VIOLATION。",
    parameters={"fake": _FAKE_PARAM},
    emoji="⏯️",
)
def music_resume(fake: bool = False) -> str:
    """恢复播放；返回 player_state。"""
    try:
        rt = _runtime
        player = _get_player(rt, fake)
        if player is None:
            return _err("E_PLAYER_NOT_READY", "播放器未初始化（未配置音乐源）")
        try:
            player.resume()
        except RuntimeError as exc:
            return _err("E_STATE_VIOLATION", str(exc))
        _write_state_file(player)
        current = player.current_song
        if current is not None:
            _publish_event(
                "music.started",
                {
                    "track_id": current.id,
                    "title": current.name,
                    "artists": current.artists,
                    "state": player.current_state.value,
                    "resumed": True,
                },
            )
        return _ok(player.to_state_dict())
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_resume 失败: %s", exc)
        return _err("E_INVALID_ARGS", str(exc))


# ---------------------------------------------------------------------------
# Tool 7：停止
# ---------------------------------------------------------------------------
@tool(
    name="music_stop",
    description="停止播放：清空进度（position_s=0），保留队列与当前索引，状态置为 stopped。",
    parameters={"fake": _FAKE_PARAM},
    emoji="⏹️",
)
def music_stop(fake: bool = False) -> str:
    """停止播放；返回 player_state。"""
    try:
        rt = _runtime
        player = _get_player(rt, fake)
        if player is None:
            return _err("E_PLAYER_NOT_READY", "播放器未初始化（未配置音乐源）")
        player.stop()
        _write_state_file(player)
        _publish_event(
            "music.stopped",
            {"state": "stopped"},
        )
        return _ok(player.to_state_dict())
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_stop 失败: %s", exc)
        return _err("E_INVALID_ARGS", str(exc))


# ---------------------------------------------------------------------------
# Tool 8：下一首
# ---------------------------------------------------------------------------
@tool(
    name="music_next",
    description="切换到下一首：按当前循环模式（single/list_loop/random/sequence）切换。"
    "SEQUENCE 模式下到末尾会停止并返回 current_song=null。",
    parameters={"fake": _FAKE_PARAM},
    emoji="⏭️",
)
def music_next(fake: bool = False) -> str:
    """切换下一首；返回 current_song + player_state。"""
    try:
        rt = _runtime
        player = _get_player(rt, fake)
        if player is None:
            return _err("E_PLAYER_NOT_READY", "播放器未初始化（未配置音乐源）")
        song = player.next()
        _write_state_file(player)
        if song is not None:
            _publish_event(
                "music.track_changed",
                {
                    "track_id": song.id,
                    "title": song.name,
                    "artists": song.artists,
                    "state": player.current_state.value,
                    "direction": "next",
                },
            )
        # 扁平返回：to_state_dict 已含 current_song（=song 或 None）。
        return _ok(player.to_state_dict())
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_next 失败: %s", exc)
        return _err("E_INVALID_ARGS", str(exc))


# ---------------------------------------------------------------------------
# Tool 9：上一首
# ---------------------------------------------------------------------------
@tool(
    name="music_previous",
    description="切换到上一首：LIST_LOOP 模式回绕到末尾，其他模式 index-1（不小于 0）。",
    parameters={"fake": _FAKE_PARAM},
    emoji="⏮️",
)
def music_previous(fake: bool = False) -> str:
    """切换上一首；返回 current_song + player_state。"""
    try:
        rt = _runtime
        player = _get_player(rt, fake)
        if player is None:
            return _err("E_PLAYER_NOT_READY", "播放器未初始化（未配置音乐源）")
        song = player.previous()
        _write_state_file(player)
        if song is not None:
            _publish_event(
                "music.track_changed",
                {
                    "track_id": song.id,
                    "title": song.name,
                    "artists": song.artists,
                    "state": player.current_state.value,
                    "direction": "previous",
                },
            )
        # 扁平返回：to_state_dict 已含 current_song（=song 或 None）。
        return _ok(player.to_state_dict())
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_previous 失败: %s", exc)
        return _err("E_INVALID_ARGS", str(exc))


# ---------------------------------------------------------------------------
# Tool 10：跳转进度
# ---------------------------------------------------------------------------
@tool(
    name="music_seek",
    description="跳转到指定播放位置（秒）。position_s 不能为负，否则返回 E_INVALID_ARGS。",
    parameters={
        "position_s": {
            "type": "integer",
            "description": "目标播放位置（秒，非负）",
        },
        "fake": _FAKE_PARAM,
    },
    required=["position_s"],
    emoji="⏩",
)
def music_seek(position_s: int, fake: bool = False) -> str:
    """跳转进度；返回 player_state。"""
    try:
        rt = _runtime
        player = _get_player(rt, fake)
        if player is None:
            return _err("E_PLAYER_NOT_READY", "播放器未初始化（未配置音乐源）")
        if position_s < 0:
            return _err("E_INVALID_ARGS", f"position_s 不能为负: {position_s}")
        try:
            player.seek(position_s)
        except ValueError as exc:
            return _err("E_INVALID_ARGS", str(exc))
        _write_state_file(player)
        return _ok(player.to_state_dict())
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_seek 失败: %s", exc)
        return _err("E_INVALID_ARGS", str(exc))


# ---------------------------------------------------------------------------
# Tool 11：设置循环模式
# ---------------------------------------------------------------------------
@tool(
    name="music_set_repeat_mode",
    description="设置循环模式：single（单曲循环）/ list_loop（列表循环）/ "
    "random（随机播放）/ sequence（顺序播放）。未知值返回 E_INVALID_ARGS。",
    parameters={
        "mode": {
            "type": "string",
            "description": "循环模式：single / list_loop / random / sequence",
            "enum": ["single", "list_loop", "random", "sequence"],
        },
        "fake": _FAKE_PARAM,
    },
    required=["mode"],
    emoji="🔁",
)
def music_set_repeat_mode(mode: str, fake: bool = False) -> str:
    """设置循环模式；返回 repeat_mode + player_state。"""
    try:
        rt = _runtime
        player = _get_player(rt, fake)
        if player is None:
            return _err("E_PLAYER_NOT_READY", "播放器未初始化（未配置音乐源）")
        target = _REPEAT_MODE_MAP.get(mode)
        if target is None:
            return _err(
                "E_INVALID_ARGS",
                f"未知 mode: {mode}（支持 single/list_loop/random/sequence）",
            )
        player.set_repeat_mode(target)
        _write_state_file(player)
        # 扁平返回：to_state_dict 已含 repeat_mode。
        return _ok(player.to_state_dict())
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_set_repeat_mode 失败: %s", exc)
        return _err("E_INVALID_ARGS", str(exc))


# ---------------------------------------------------------------------------
# Tool 12：获取播放器状态
# ---------------------------------------------------------------------------
@tool(
    name="music_get_player_state",
    description="获取播放器完整状态：队列 / 当前索引 / 播放状态 / 循环模式 / 进度 / 当前曲目。"
    "用于前端 state_file 同步与 CLI 状态查询。",
    parameters={"fake": _FAKE_PARAM},
    emoji="📊",
)
def music_get_player_state(fake: bool = False) -> str:
    """获取播放器状态；扁平返回 to_state_dict（queue/current_index/state/
    repeat_mode/position_s/current_song 直接位于 data 顶层）。

    前端 ``normalizePlayerState(data)`` 按平铺契约读取 ``data.queue`` 等，
    故此处不再包一层 ``player_state`` 键。
    """
    try:
        rt = _runtime
        player = _get_player(rt, fake)
        if player is None:
            return _err("E_PLAYER_NOT_READY", "播放器未初始化（未配置音乐源）")
        return _ok(player.to_state_dict())
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_get_player_state 失败: %s", exc)
        return _err("E_INVALID_ARGS", str(exc))


# ===========================================================================
# M19：本地音乐库管理（library / playlist / decrypt 工具）
# ===========================================================================
# library runtime：持有 MusicLibraryDB / LibraryScanner / LibraryWatcher 单例
class _LibraryRuntime:
    """library 子系统运行时：DB / scanner / watcher 单例。

    DB 路径由 env ``AI_OMNI_MUSIC_DB`` 控制（测试指向 tmp_path）。
    scanner / watcher 懒构造；watcher 缺失 watchdog 时为 None（降级）。
    """

    def __init__(self) -> None:
        self.db: Any = None
        self.scanner: Any = None
        self.watcher: Any = None
        self.fake_scanner: Any = None  # fake 模式预置扫描器

    def close(self) -> None:
        """释放 DB 连接（幂等）。"""
        if self.db is not None:
            try:
                self.db.close()
            except Exception:  # noqa: BLE001
                pass
            self.db = None
        self.scanner = None
        self.watcher = None
        self.fake_scanner = None


_library_runtime = _LibraryRuntime()


def _reset_library_runtime() -> _LibraryRuntime:
    """替换 library runtime（测试隔离用），返回新实例。"""
    global _library_runtime
    _library_runtime.close()
    _library_runtime = _LibraryRuntime()
    return _library_runtime


def _get_library_db() -> Any:
    """取当前 MusicLibraryDB（懒构造，从 env 读路径）。"""
    from omni_music.library.db import MusicLibraryDB

    if _library_runtime.db is None:
        _library_runtime.db = MusicLibraryDB.from_env()
        _library_runtime.db.init_schema()
    return _library_runtime.db


def _make_fake_scanner() -> Any:
    """构造 fake 扫描器：预置 2 首歌，零文件依赖。

    用于 ``music_library_scan(fake=True)``：不扫描真实文件系统，
    用 FakeFileScanner + FakeMetadataReader 返回固定歌曲数据。
    """
    from omni_music.library.scanner import LibraryScanner

    files = ["/fake/music/a.mp3", "/fake/music/b.mp3"]
    metadata = {
        "/fake/music/a.mp3": {
            "title": "晴天", "artist": "周杰伦", "album": "叶惠美", "duration": 269,
        },
        "/fake/music/b.mp3": {
            "title": "稻香", "artist": "周杰伦", "album": "魔杰座", "duration": 223,
        },
    }

    class _FakeFileScanner:
        def scan(self, root: str) -> list[str]:
            return list(files)

    class _FakeMetadataReader:
        def read(self, path: str) -> dict:
            return metadata.get(path, {"title": None, "duration": 0})

    class _FakeCoverExtractor:
        def extract(self, path: str, song_id: str, mtime: float):
            return None

    class _FakeFileStat:
        def stat(self, path: str):
            return (1000.0, 1024)

    db = _get_library_db()
    return LibraryScanner(
        root_dir="/fake/music",
        file_scanner=_FakeFileScanner(),
        metadata_reader=_FakeMetadataReader(),
        cover_extractor=_FakeCoverExtractor(),
        file_stat=_FakeFileStat(),
        db=db,
    )


# ---------------------------------------------------------------------------
# Tool 13：扫描本地音乐库
# ---------------------------------------------------------------------------
@tool(
    name="music_library_scan",
    description="扫描本地音乐库目录，读取元数据并写入 SQLite 索引（增量扫描，按 mtime 跳过未变文件）。"
    "返回 scanned/added/updated/skipped/errors 统计。",
    parameters={
        "root_dir": {
            "type": "string",
            "description": "扫描根目录（默认 ~/.ai-omni/music）",
        },
        "fake": _FAKE_PARAM,
    },
    emoji="📚",
)
def music_library_scan(root_dir: str | None = None, fake: bool = False) -> str:
    """扫描本地音乐库写入 SQLite；返回统计 dict。"""
    try:
        db = _get_library_db()
        if fake:
            scanner = _library_runtime.fake_scanner or _make_fake_scanner()
            _library_runtime.fake_scanner = scanner
        else:
            from omni_music.library.scanner import LibraryScanner

            scan_root = root_dir or os.path.expanduser("~/.ai-omni/music")
            scanner = LibraryScanner(root_dir=scan_root, db=db)
        result = scanner.scan()
        return _ok(result)
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_library_scan 失败: %s", exc)
        return _err("E_SCAN_FAILED", str(exc))


# ---------------------------------------------------------------------------
# Tool 14：FTS5 全文搜索
# ---------------------------------------------------------------------------
@tool(
    name="music_library_search",
    description="全文搜索音乐库（FTS5，按 title/artist/album 匹配）。"
    "需先调用 music_library_scan 建立索引；未扫描时返回空列表。",
    parameters={
        "query": {
            "type": "string",
            "description": "搜索关键词（空字符串返回全部）",
        },
        "limit": {
            "type": "integer",
            "description": "返回上限，默认 20",
            "default": 20,
        },
        "fake": _FAKE_PARAM,
    },
    emoji="🔍",
)
def music_library_search(query: str = "", limit: int = 20, fake: bool = False) -> str:
    """FTS5 全文搜索；返回歌曲列表。"""
    try:
        db = _get_library_db()
        results = db.search(query, limit=limit)
        return _ok({"songs": results, "count": len(results)})
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_library_search 失败: %s", exc)
        return _err("E_SEARCH_FAILED", str(exc))


# ---------------------------------------------------------------------------
# Tool 15：库状态
# ---------------------------------------------------------------------------
@tool(
    name="music_library_status",
    description="查询音乐库状态：歌曲数 / 歌单数 / 上次扫描时间 / 监听状态。",
    parameters={"fake": _FAKE_PARAM},
    emoji="📊",
)
def music_library_status(fake: bool = False) -> str:
    """返回库状态。"""
    try:
        db = _get_library_db()
        status = db.get_status()
        status["watching"] = (
            _library_runtime.watcher is not None
            and _library_runtime.watcher.is_running()
        )
        return _ok(status)
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_library_status 失败: %s", exc)
        return _err("E_INVALID_ARGS", str(exc))


# ---------------------------------------------------------------------------
# Tool 16：创建歌单
# ---------------------------------------------------------------------------
@tool(
    name="music_playlist_create",
    description="创建歌单，返回自增 playlist_id。歌单名不能为空。",
    parameters={
        "name": {
            "type": "string",
            "description": "歌单名称（非空）",
        },
        "fake": _FAKE_PARAM,
    },
    required=["name"],
    emoji="📋",
)
def music_playlist_create(name: str, fake: bool = False) -> str:
    """创建歌单；返回 playlist_id。"""
    try:
        if not name or not name.strip():
            return _err("E_INVALID_ARGS", "歌单名不能为空")
        db = _get_library_db()
        pid = db.create_playlist(name.strip())
        return _ok({"playlist_id": pid, "name": name.strip()})
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_playlist_create 失败: %s", exc)
        return _err("E_INVALID_ARGS", str(exc))


# ---------------------------------------------------------------------------
# Tool 17：歌单添加歌曲
# ---------------------------------------------------------------------------
@tool(
    name="music_playlist_add",
    description="向歌单添加歌曲（按 song_id 去重，可指定 position 插入位置）。",
    parameters={
        "playlist_id": {
            "type": "integer",
            "description": "歌单 ID（music_playlist_create 返回）",
        },
        "song_id": {
            "type": "string",
            "description": "歌曲 ID（music_library_scan / music_library_search 返回）",
        },
        "position": {
            "type": "integer",
            "description": "插入位置（从 0 起）；缺省追加到末尾",
        },
        "fake": _FAKE_PARAM,
    },
    required=["playlist_id", "song_id"],
    emoji="➕",
)
def music_playlist_add(
    playlist_id: int, song_id: str, position: int | None = None, fake: bool = False
) -> str:
    """添加歌曲到歌单。"""
    try:
        db = _get_library_db()
        # 校验 song_id 存在
        if db.get_song(song_id) is None:
            return _err("E_INVALID_ARGS", f"歌曲不存在: {song_id}")
        db.add_to_playlist(playlist_id, song_id, position=position)
        return _ok({"playlist_id": playlist_id, "song_id": song_id, "added": True})
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_playlist_add 失败: %s", exc)
        return _err("E_INVALID_ARGS", str(exc))


# ---------------------------------------------------------------------------
# Tool 18：歌单移除歌曲
# ---------------------------------------------------------------------------
@tool(
    name="music_playlist_remove",
    description="从歌单移除歌曲（幂等）。",
    parameters={
        "playlist_id": {
            "type": "integer",
            "description": "歌单 ID",
        },
        "song_id": {
            "type": "string",
            "description": "要移除的歌曲 ID",
        },
        "fake": _FAKE_PARAM,
    },
    required=["playlist_id", "song_id"],
    emoji="➖",
)
def music_playlist_remove(playlist_id: int, song_id: str, fake: bool = False) -> str:
    """从歌单移除歌曲。"""
    try:
        db = _get_library_db()
        db.remove_from_playlist(playlist_id, song_id)
        return _ok({"playlist_id": playlist_id, "song_id": song_id, "removed": True})
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_playlist_remove 失败: %s", exc)
        return _err("E_INVALID_ARGS", str(exc))


# ---------------------------------------------------------------------------
# Tool 19：列歌单 / 歌单内歌曲
# ---------------------------------------------------------------------------
@tool(
    name="music_playlist_list",
    description="列出全部歌单（不传 playlist_id）或指定歌单内歌曲（传 playlist_id）。",
    parameters={
        "playlist_id": {
            "type": "integer",
            "description": "歌单 ID；缺省时列出全部歌单",
        },
        "fake": _FAKE_PARAM,
    },
    emoji="📃",
)
def music_playlist_list(playlist_id: int | None = None, fake: bool = False) -> str:
    """列歌单或歌单内歌曲。"""
    try:
        db = _get_library_db()
        if playlist_id is None:
            playlists = db.get_playlists()
            return _ok({"playlists": playlists, "count": len(playlists)})
        songs = db.get_playlist_songs(playlist_id)
        return _ok({"songs": songs, "count": len(songs), "playlist_id": playlist_id})
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_playlist_list 失败: %s", exc)
        return _err("E_INVALID_ARGS", str(exc))


# ---------------------------------------------------------------------------
# Tool 20：解密加密音频文件（confirm=true 安全门）
# ---------------------------------------------------------------------------
@tool(
    name="music_decrypt_file",
    description="解密加密音频文件（.qmc/.qmcflac/.mflac/.mgg），输出标准格式到同目录。"
    "**仅用于已合法购买内容的格式转换，不提供破解付费内容能力（D19.1 合规）**。"
    "需传 confirm=true 作为安全门；支持 .qmc0/.qmcflac（静态 seed 表）与 "
    ".mflac/.mgg（需 env AI_OMNNI_MUSIC_KEY 密钥）。",
    parameters={
        "path": {
            "type": "string",
            "description": "加密源文件路径",
        },
        "output_path": {
            "type": "string",
            "description": "自定义输出路径；缺省时输出到同目录 .decrypted.*",
        },
        "confirm": {
            "type": "boolean",
            "description": "安全门：必须为 true 才执行解密（确认已合法购买）",
        },
        "fake": _FAKE_PARAM,
    },
    required=["path"],
    emoji="🔓",
)
def music_decrypt_file(
    path: str,
    output_path: str | None = None,
    confirm: bool = False,
    fake: bool = False,
) -> str:
    """解密加密音频文件；返回输出路径 + 合规声明。"""
    try:
        if not confirm:
            return _err(
                "E_CONFIRM_REQUIRED",
                "解密需确认：传 confirm=true 确认你已合法购买该内容（D19.1 合规约束）",
            )
        from omni_music.library.decryptor import AudioDecryptor

        decryptor = AudioDecryptor()
        if not decryptor.is_supported(path):
            return _err("E_UNSUPPORTED_FORMAT", f"不支持的加密格式: {path}")
        try:
            out = decryptor.decrypt(path, output_path=output_path)
        except FileNotFoundError as exc:
            return _err("E_FILE_NOT_FOUND", str(exc))
        except RuntimeError as exc:
            return _err("E_DECRYPT_KEY_MISSING", str(exc))
        return _ok(
            {
                "output_path": out,
                "source_path": path,
                "compliance": "D19.1: 仅用于已合法购买内容的格式转换，不提供破解付费内容能力",
                "notice": "请确保你已合法购买该音频内容，解密仅作本地备份格式转换用途",
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("music_decrypt_file 失败: %s", exc)
        return _err("E_DECRYPT_FAILED", str(exc))


# ---------------------------------------------------------------------------
# 注册入口
# ---------------------------------------------------------------------------
def _make_handler(func: Callable) -> Callable:
    """把工具函数适配为 registry handler：``(args: dict, **kw) -> JSON 字符串``。"""

    def handler(args: dict[str, Any], **_: Any) -> str:
        try:
            return func(**(args or {}))
        except Exception as exc:  # noqa: BLE001
            logger.debug("music tool %s 调用失败: %s", getattr(func, "__name__", "?"), exc)
            return _err("E_INVALID_ARGS", str(exc))

    return handler


def register(ctx) -> None:
    """把 20 个 music_* tools 注册到插件上下文（M17 12 个 + M19 8 个 library/playlist/decrypt）。

    使用 M15 新式 ``ctx.register_tool(name, description, emoji, schema, handler_func)`` 签名。
    若 ctx 携带事件总线则接入，用于发布 music.* 事件和订阅 system.volume_changed。
    """
    for meta in TOOLS:
        ctx.register_tool(
            name=meta["name"],
            description=meta["description"],
            emoji=meta["emoji"],
            schema=meta["schema"],
            handler_func=_make_handler(meta["handler_func"]),
        )
    bus = getattr(ctx, "event_bus", None)
    if bus is not None and callable(getattr(bus, "publish", None)):
        _runtime.event_publisher = bus
    logger.info("omni_music 插件已注册 %d 个 tools", len(TOOLS))


def set_volume_gain(gain: float) -> None:
    """设置音量增益（由 system.volume_changed 事件触发）。"""
    _runtime.volume_gain = max(0.0, min(2.0, float(gain)))
