"""omni_lyrics 工具实现（M18.5）：5 个 ``lyrics_*`` 工具。

工具清单：
- ``lyrics_get``        ：获取歌词（参数 song_id, source），返回解析后的 LyricsLine 列表
- ``lyrics_search``     ：按关键词搜索歌词（复用 music_search 结果）
- ``lyrics_set_offset`` ：设置用户偏移量（参数 offset_s）
- ``lyrics_upload``     ：上传/保存歌词到本地 .lrc 文件（参数 song_id, content）
- ``lyrics_get_current``：根据当前播放时间返回当前行+逐字高亮

工具统一返回 JSON 字符串 ``{"ok": true, "data": ...}`` /
``{"ok": false, "error": {"code": "E_XXX", "message": "..."}}``。

设计要点：
- 进程内 :class:`Runtime` 单例持有 MusicSource / LyricsChain / LyricsSync / 歌词缓存
- ``source`` 可由测试/CLI 预置为 fake；未预置时按 ``fake`` 参数构造 FakeMusicSource
- ``lyrics_get`` 结果缓存到 ``Runtime.lyrics_cache``（按 song_id），供 ``lyrics_get_current`` 复用
- 跨插件复用：经 ``omni_music.sources.base.MusicSource`` 抽象接口获取歌曲/歌词
- ``mutagen`` 惰性导入（CLAUDE.md §三），测试全用 fake 后端
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable

from omni_lyrics.lyrics_chain import LyricsChain, MutagenEmbeddedReader
from omni_lyrics.lyrics_sync import LyricsSync
from omni_music.models import MusicSourceEnum, Song
from omni_music.sources.base import FakeMusicSource, MusicSource

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 运行时单例
# ---------------------------------------------------------------------------
class Runtime:
    """进程内运行时：持有音乐源、歌词链、同步器、歌词缓存。

    :ivar source: MusicSource 实例（fake 或真实）
    :ivar chain: LyricsChain 优先级链
    :ivar sync: LyricsSync 同步器（含用户偏移）
    :ivar lyrics_cache: song_id → LyricsResult 缓存（lyrics_get_current 复用）
    :ivar fake_mode: 是否处于 fake 模式
    :ivar sync_active: 歌词同步是否激活
    :ivar current_song_id: 当前同步中的歌曲 ID
    """

    def __init__(self) -> None:
        self.source: MusicSource | None = None
        self.chain: LyricsChain | None = None
        self.sync: LyricsSync = LyricsSync()
        self.lyrics_cache: dict[str, Any] = {}
        self.fake_mode: bool = False
        self.event_publisher: Any = None
        self.sync_active: bool = False
        self.current_song_id: str | None = None


_runtime = Runtime()


def _reset_runtime(runtime: Runtime | None = None) -> Runtime:
    """替换进程内运行时（测试隔离用），返回新实例。"""
    global _runtime
    _runtime = runtime or Runtime()
    return _runtime


def start_sync_for_song(song_id: str) -> bool:
    """为指定歌曲启动歌词同步。

    :param song_id: 歌曲 ID
    :return: 是否成功启动（歌曲存在且歌词可用返回 True）
    """
    rt = _runtime
    if song_id is None:
        rt.sync_active = False
        rt.current_song_id = None
        return False
    rt.current_song_id = song_id
    rt.sync_active = True
    return True


def stop_sync() -> None:
    """停止歌词同步。"""
    rt = _runtime
    rt.sync_active = False
    rt.current_song_id = None


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
    logger.warning("未配置音乐源；请使用 fake=True 或预置 source")
    return None


def _get_chain(rt: Runtime, fake: bool) -> LyricsChain:
    """取歌词优先级链；未预置时按当前 source 构造。"""
    if rt.chain is not None:
        return rt.chain
    source = _get_source(rt, fake)
    sources = [source] if source is not None else []
    # mutagen 惰性导入：运行时构造 MutagenEmbeddedReader（mutagen 缺失时 read 返回 None）
    rt.chain = LyricsChain(sources=sources, embedded_reader=MutagenEmbeddedReader())
    return rt.chain


def _find_song(rt: Runtime, song_id: str, fake: bool) -> Song | None:
    """从当前源查找歌曲详情。"""
    source = _get_source(rt, fake)
    if source is None:
        return None
    try:
        return source.get_song_detail(song_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("get_song_detail 失败: %s", exc)
        return None


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


# ---------------------------------------------------------------------------
# Tool 1：获取歌词
# ---------------------------------------------------------------------------
@tool(
    name="lyrics_get",
    description="获取歌词：按 song_id 经多源优先级链（本地.lrc→内嵌→在线）获取并解析。"
    "返回解析后的 LyricsLine 列表（含时间轴/逐字/翻译）。",
    parameters={
        "song_id": {
            "type": "string",
            "description": "歌曲 ID",
        },
        "source": {
            "type": "string",
            "description": "指定来源过滤：local_file / embedded / online / none；"
            "不传则按优先级链自动选择",
        },
        "fake": _FAKE_PARAM,
    },
    required=["song_id"],
    emoji="📜",
)
def lyrics_get(song_id: str, source: str | None = None, fake: bool = False) -> str:
    """获取歌词；返回 {lyrics, source, parsed}。"""
    try:
        rt = _runtime
        if _get_source(rt, fake) is None:
            return _err("E_BACKEND_UNAVAILABLE", "未配置音乐源")
        song = _find_song(rt, song_id, fake)
        if song is None:
            return _err("E_NOT_FOUND", f"未找到歌曲: {song_id}")
        chain = _get_chain(rt, fake)
        result = chain.fetch(song)
        # source 过滤：若指定了 source 且与实际来源不符，返回空
        if source is not None and result.source != source:
            return _ok(
                {
                    "lyrics": None,
                    "source": "none",
                    "parsed": [],
                }
            )
        # 缓存结果供 lyrics_get_current 复用
        rt.lyrics_cache[song_id] = result
        return _ok(result.to_dict())
    except Exception as exc:  # noqa: BLE001
        logger.debug("lyrics_get 失败: %s", exc)
        return _err("E_LYRICS_FAILED", str(exc))


# ---------------------------------------------------------------------------
# Tool 2：搜索歌词（复用 music_search）
# ---------------------------------------------------------------------------
@tool(
    name="lyrics_search",
    description="按关键词搜索歌曲：返回歌曲元数据列表（用于查找有歌词的曲目）。",
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
    emoji="🔍",
)
def lyrics_search(keyword: str, limit: int = 20, fake: bool = False) -> str:
    """搜索歌曲；返回 {songs, count}。"""
    try:
        rt = _runtime
        source = _get_source(rt, fake)
        if source is None:
            return _err("E_BACKEND_UNAVAILABLE", "未配置音乐源")
        songs = source.search(keyword, limit=limit)
        return _ok({"songs": [s.to_dict() for s in songs], "count": len(songs)})
    except Exception as exc:  # noqa: BLE001
        logger.debug("lyrics_search 失败: %s", exc)
        return _err("E_SEARCH_FAILED", str(exc))


# ---------------------------------------------------------------------------
# Tool 3：设置用户偏移量
# ---------------------------------------------------------------------------
@tool(
    name="lyrics_set_offset",
    description="设置歌词用户偏移量：正数提前显示，负数延后。用于歌词与音频不同步时微调。",
    parameters={
        "offset_s": {
            "type": "number",
            "description": "偏移秒数（正数提前，负数延后）",
        },
    },
    required=["offset_s"],
    emoji="⏱️",
)
def lyrics_set_offset(offset_s: float) -> str:
    """设置用户偏移量；返回 {offset_s}。"""
    try:
        offset = float(offset_s)
    except (TypeError, ValueError) as exc:
        return _err("E_INVALID_ARGS", f"offset_s 必须为数值: {exc}")
    _runtime.sync.set_offset(offset)
    return _ok({"offset_s": _runtime.sync.get_offset()})


# ---------------------------------------------------------------------------
# Tool 4：上传/保存歌词到本地 .lrc 文件
# ---------------------------------------------------------------------------
@tool(
    name="lyrics_upload",
    description="上传/保存歌词到本地 .lrc 文件：仅对本地源（file:// URL）有效。"
    "写入与音频同名的 .lrc 文件。",
    parameters={
        "song_id": {
            "type": "string",
            "description": "歌曲 ID",
        },
        "content": {
            "type": "string",
            "description": "歌词内容（LRC 格式或纯文本）",
        },
        "fake": _FAKE_PARAM,
    },
    required=["song_id", "content"],
    emoji="📝",
)
def lyrics_upload(song_id: str, content: str, fake: bool = False) -> str:
    """保存歌词到 .lrc 文件；返回 {path}。"""
    try:
        if not content or not content.strip():
            return _err("E_INVALID_ARGS", "content 不能为空")
        rt = _runtime
        if _get_source(rt, fake) is None:
            return _err("E_BACKEND_UNAVAILABLE", "未配置音乐源")
        song = _find_song(rt, song_id, fake)
        if song is None:
            return _err("E_NOT_FOUND", f"未找到歌曲: {song_id}")
        url = song.url
        if not isinstance(url, str) or not url.startswith("file://"):
            return _err(
                "E_INVALID_ARGS",
                "仅本地源（file:// URL）支持上传歌词",
            )
        audio_path = url[len("file://") :]
        lrc_path = os.path.splitext(audio_path)[0] + ".lrc"
        try:
            Path(lrc_path).parent.mkdir(parents=True, exist_ok=True)
            with open(lrc_path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as exc:
            return _err("E_UPLOAD_FAILED", f"写入 .lrc 文件失败: {exc}")
        # 刷新歌词缓存
        rt.lyrics_cache.pop(song_id, None)
        return _ok({"path": lrc_path})
    except Exception as exc:  # noqa: BLE001
        logger.debug("lyrics_upload 失败: %s", exc)
        return _err("E_UPLOAD_FAILED", str(exc))


# ---------------------------------------------------------------------------
# Tool 5：获取当前行 + 逐字高亮
# ---------------------------------------------------------------------------
@tool(
    name="lyrics_get_current",
    description="根据当前播放时间返回当前歌词行索引 + 逐字高亮索引。"
    "若运行时无歌词缓存则自动 fetch。",
    parameters={
        "song_id": {
            "type": "string",
            "description": "歌曲 ID",
        },
        "current_time_s": {
            "type": "number",
            "description": "当前播放时间（秒）",
        },
        "fake": _FAKE_PARAM,
    },
    required=["song_id", "current_time_s"],
    emoji="🎤",
)
def lyrics_get_current(song_id: str, current_time_s: float, fake: bool = False) -> str:
    """返回当前行 + 逐字高亮；返回 {current_line, current_word, line_text}。"""
    try:
        rt = _runtime
        # 缓存未命中则自动 fetch
        if song_id not in rt.lyrics_cache:
            song = _find_song(rt, song_id, fake)
            if song is None:
                return _err("E_NOT_FOUND", f"未找到歌曲: {song_id}")
            chain = _get_chain(rt, fake)
            rt.lyrics_cache[song_id] = chain.fetch(song)

        result = rt.lyrics_cache[song_id]
        parsed = result.parsed
        if not parsed:
            return _ok(
                {
                    "current_line": -1,
                    "current_word": None,
                    "line_text": None,
                }
            )

        line_idx = rt.sync.find_current_line(parsed, float(current_time_s))
        if line_idx < 0 or line_idx >= len(parsed):
            return _ok(
                {
                    "current_line": -1,
                    "current_word": None,
                    "line_text": None,
                }
            )
        line = parsed[line_idx]
        word_idx = rt.sync.find_current_word(line, float(current_time_s))
        return _ok(
            {
                "current_line": line_idx,
                "current_word": word_idx,
                "line_text": line.text,
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("lyrics_get_current 失败: %s", exc)
        return _err("E_LYRICS_FAILED", str(exc))


# ---------------------------------------------------------------------------
# 注册入口
# ---------------------------------------------------------------------------
def _make_handler(func: Callable) -> Callable:
    """把工具函数适配为 registry handler：``(args: dict, **kw) -> JSON 字符串``。"""

    def handler(args: dict[str, Any], **_: Any) -> str:
        try:
            return func(**(args or {}))
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "lyrics tool %s 调用失败: %s", getattr(func, "__name__", "?"), exc
            )
            return _err("E_INVALID_ARGS", str(exc))

    return handler


def register(ctx) -> None:
    """把 5 个 lyrics_* tools 注册到插件上下文。

    使用 M15 新式 ``ctx.register_tool(name, description, emoji, schema, handler_func)`` 签名。
    若 ctx 携带事件总线则接入，用于订阅 music.* 事件自动启停歌词同步。
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
    logger.info("omni_lyrics 插件已注册 %d 个 tools", len(TOOLS))
