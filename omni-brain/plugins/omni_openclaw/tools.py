"""omni_openclaw 工具注册与 handler 实现。"""

from __future__ import annotations

import json
from typing import Any

from omni_openclaw.aicg import AicgPipeline
from omni_openclaw.client import OpenClawClient
from omni_openclaw.cluster import ClusterChecker
from omni_openclaw.config import OpenClawConfig
from omni_openclaw.errors import error_response, success_response
from omni_openclaw.home import HomeAssistantClient

#: openclaw_health schema
OPENCLAW_HEALTH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "检查 OpenClaw 网关健康状态",
    "properties": {},
    "required": [],
}

#: openclaw_send_wechat schema
OPENCLAW_SEND_WECHAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "通过 OpenClaw 发送微信消息",
    "properties": {
        "message": {
            "type": "string",
            "description": "要发送的消息内容",
        },
        "target": {
            "type": "string",
            "description": "目标微信用户 ID，默认使用配置中的 wechat_default_target",
        },
        "account": {
            "type": "string",
            "description": "微信机器人账号，默认使用配置中的 wechat_account",
        },
    },
    "required": ["message"],
}

#: openclaw_vision_chat schema
OPENCLAW_VISION_CHAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "通过 Nemotron L1 进行单图视觉理解",
    "properties": {
        "prompt": {
            "type": "string",
            "description": "对图像的提问或指令",
        },
        "image": {
            "type": "string",
            "description": "图像 URL 或 base64 data URL",
        },
        "detail": {
            "type": "string",
            "description": "图像细节级别：auto / low / high",
            "default": "auto",
        },
    },
    "required": ["prompt", "image"],
}

#: openclaw_audio_chat schema
OPENCLAW_AUDIO_CHAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "通过 Nemotron L1 进行音频理解",
    "properties": {
        "prompt": {
            "type": "string",
            "description": "对音频的提问或指令",
        },
        "audio": {
            "type": "string",
            "description": "音频 base64 字符串",
        },
        "format": {
            "type": "string",
            "description": "音频格式：wav / mp3 / ogg",
            "default": "wav",
        },
    },
    "required": ["prompt", "audio"],
}

#: openclaw_video_chat schema
OPENCLAW_VIDEO_CHAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "通过 Nemotron L1 进行视频理解（URL 或关键帧序列）",
    "properties": {
        "prompt": {
            "type": "string",
            "description": "对视频的提问或指令",
        },
        "video": {
            "type": "string",
            "description": "视频 URL 或 base64 data URL",
        },
        "frames": {
            "type": "array",
            "description": "可选的关键帧 base64 data URL 列表，传入后优先使用帧序列",
            "items": {"type": "string"},
        },
    },
    "required": ["prompt", "video"],
}


def _handle_health(params: dict[str, Any]) -> str:
    """处理 openclaw_health 工具调用。"""
    cfg = OpenClawConfig.from_env()
    return json.dumps(
        success_response(
            gateway=cfg.gateway,
            llm_l1_endpoint=cfg.llm_l1_endpoint,
            comfyui_endpoint=cfg.comfyui_endpoint,
            tts_endpoint=cfg.tts_endpoint,
        ),
        ensure_ascii=False,
    )


def _run_async(coro: Any) -> Any:
    """在独立事件循环中运行 async coroutine。

    register(ctx) 的 handler 必须是同步函数，而 OpenClawClient 为 async，
    因此新建独立事件循环执行，避免与外部事件循环冲突。
    若当前线程已有运行中的事件循环，则在后台线程中运行新循环避免冲突。
    """
    import asyncio
    import concurrent.futures

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()


def _run_with(resource: Any, coro: Any) -> Any:
    """运行协程，并在同一事件循环内关闭 ``resource``（M32.23）。

    工具 handler 为一次性调用：客户端（OpenClawClient / HomeAssistantClient /
    AicgPipeline / ClusterChecker）用完必须在同一事件循环内 ``await close()``，
    否则长驻进程中每次工具调用都泄漏一个 httpx 连接池（GC 时触发
    ResourceWarning，真实运行时为未释放的 socket）。
    """

    async def _runner() -> Any:
        try:
            return await coro
        finally:
            close = getattr(resource, "close", None)
            if close is not None:
                await close()

    return _run_async(_runner())


def _handle_send_wechat(params: dict[str, Any]) -> str:
    """处理 openclaw_send_wechat 工具调用（M38 起弃用，由 omni_wechat 直连 iLink 替代）。"""
    message = params.get("message", "")
    if not message or not str(message).strip():
        return json.dumps(
            error_response("E_INVALID_PARAMS", "缺少必填参数 message"),
            ensure_ascii=False,
        )
    return json.dumps(
        error_response(
            "E_DEPRECATED",
            "openclaw_send_wechat 已弃用：微信链路 M38 起改为 omni_wechat 插件直连 "
            "iLink（链路更短且支持接收），请改用 wechat_send 工具",
            replacement="wechat_send",
        ),
        ensure_ascii=False,
    )


def _handle_vision_chat(params: dict[str, Any]) -> str:
    """处理 openclaw_vision_chat 工具调用。"""
    prompt = params.get("prompt", "")
    image = params.get("image", "")
    if not prompt or not str(prompt).strip():
        return json.dumps(
            error_response("E_INVALID_PARAMS", "缺少必填参数 prompt"),
            ensure_ascii=False,
        )
    if not image or not str(image).strip():
        return json.dumps(
            error_response("E_INVALID_PARAMS", "缺少必填参数 image"),
            ensure_ascii=False,
        )

    cfg = OpenClawConfig.from_env()
    client = OpenClawClient(config=cfg)
    result = _run_with(
        client,
        client.vision_chat(
            prompt=prompt,
            image_base64_or_url=image,
            detail=params.get("detail", "auto"),
        ),
    )
    return json.dumps(result, ensure_ascii=False)


def _handle_audio_chat(params: dict[str, Any]) -> str:
    """处理 openclaw_audio_chat 工具调用。"""
    prompt = params.get("prompt", "")
    audio = params.get("audio", "")
    if not prompt or not str(prompt).strip():
        return json.dumps(
            error_response("E_INVALID_PARAMS", "缺少必填参数 prompt"),
            ensure_ascii=False,
        )
    if not audio or not str(audio).strip():
        return json.dumps(
            error_response("E_INVALID_PARAMS", "缺少必填参数 audio"),
            ensure_ascii=False,
        )

    cfg = OpenClawConfig.from_env()
    client = OpenClawClient(config=cfg)
    result = _run_with(
        client,
        client.audio_chat(
            prompt=prompt,
            audio_base64=audio,
            format_=params.get("format", "wav"),
        ),
    )
    return json.dumps(result, ensure_ascii=False)


def _handle_video_chat(params: dict[str, Any]) -> str:
    """处理 openclaw_video_chat 工具调用。"""
    prompt = params.get("prompt", "")
    video = params.get("video", "")
    if not prompt or not str(prompt).strip():
        return json.dumps(
            error_response("E_INVALID_PARAMS", "缺少必填参数 prompt"),
            ensure_ascii=False,
        )
    if not video or not str(video).strip():
        return json.dumps(
            error_response("E_INVALID_PARAMS", "缺少必填参数 video"),
            ensure_ascii=False,
        )

    cfg = OpenClawConfig.from_env()
    client = OpenClawClient(config=cfg)
    frames = params.get("frames")
    if frames is not None and not isinstance(frames, list):
        return json.dumps(
            error_response("E_INVALID_PARAMS", "frames 必须是数组"),
            ensure_ascii=False,
        )
    result = _run_with(
        client,
        client.video_chat(
            prompt=prompt,
            video_base64_or_url=video,
            frames=frames,
        ),
    )
    return json.dumps(result, ensure_ascii=False)


#: openclaw_control_light schema
OPENCLAW_CONTROL_LIGHT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "通过 Home Assistant 控制灯光",
    "properties": {
        "entity_id": {
            "type": "string",
            "description": "HA 灯光实体 ID，例如 light.living_room",
        },
        "on": {
            "type": "boolean",
            "description": "True 开灯，False 关灯",
        },
        "brightness": {
            "type": "integer",
            "description": "亮度 0-255",
        },
        "color_temp": {
            "type": "integer",
            "description": "色温（mireds）",
        },
    },
    "required": ["entity_id", "on"],
}

#: openclaw_control_fan schema
OPENCLAW_CONTROL_FAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "通过 Home Assistant 控制风扇",
    "properties": {
        "entity_id": {
            "type": "string",
            "description": "HA 风扇实体 ID，例如 fan.bedroom",
        },
        "on": {
            "type": "boolean",
            "description": "True 开，False 关",
        },
        "speed": {
            "type": "string",
            "description": "风速档位",
        },
    },
    "required": ["entity_id", "on"],
}

#: openclaw_control_air_purifier schema
OPENCLAW_CONTROL_AIR_PURIFIER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "通过 Home Assistant 控制空气净化器",
    "properties": {
        "entity_id": {
            "type": "string",
            "description": "HA 空气净化器实体 ID",
        },
        "on": {
            "type": "boolean",
            "description": "True 开，False 关",
        },
        "mode": {
            "type": "string",
            "description": "工作模式",
        },
    },
    "required": ["entity_id", "on"],
}

#: openclaw_speaker_voice_on schema
OPENCLAW_SPEAKER_VOICE_ON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "开启扬声器语音模式",
    "properties": {},
    "required": [],
}

#: openclaw_speaker_voice_off schema
OPENCLAW_SPEAKER_VOICE_OFF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "关闭扬声器语音模式",
    "properties": {},
    "required": [],
}

#: openclaw_speaker_say schema
OPENCLAW_SPEAKER_SAY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "通过扬声器播报文本",
    "properties": {
        "text": {
            "type": "string",
            "description": "要播报的文本",
        },
    },
    "required": ["text"],
}

#: openclaw_cluster_health schema
OPENCLAW_CLUSTER_HEALTH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "执行集群健康巡检并返回 P0/P1/P2 分级报告",
    "properties": {},
    "required": [],
}

#: openclaw_device_lookup schema
OPENCLAW_DEVICE_LOOKUP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "在设备说明文档中查询设备信息",
    "properties": {
        "query": {
            "type": "string",
            "description": "查询关键字",
        },
    },
    "required": ["query"],
}

#: openclaw_chat schema
OPENCLAW_CHAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "调用 AICG 四层模型进行文本对话（L1/L4 自动路由）",
    "properties": {
        "prompt": {
            "type": "string",
            "description": "用户输入",
        },
        "level": {
            "type": "string",
            "description": "模型层级 L1 或 L4，默认 L1",
            "default": "L1",
        },
        "nsfw": {
            "type": "boolean",
            "description": "是否路由到 L4 NSFW 模型",
            "default": False,
        },
        "temperature": {
            "type": "number",
            "description": "采样温度",
            "default": 0.7,
        },
        "max_tokens": {
            "type": "integer",
            "description": "最大生成 token 数",
            "default": 1024,
        },
    },
    "required": ["prompt"],
}

#: openclaw_generate_image schema
OPENCLAW_GENERATE_IMAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "调用 ComfyUI 生成图像",
    "properties": {
        "prompt": {
            "type": "string",
            "description": "图像正向提示词",
        },
        "width": {
            "type": "integer",
            "description": "图像宽度",
            "default": 1024,
        },
        "height": {
            "type": "integer",
            "description": "图像高度",
            "default": 1024,
        },
    },
    "required": ["prompt"],
}

#: openclaw_text_to_speech schema
OPENCLAW_TEXT_TO_SPEECH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "调用 IndexTTS2 合成语音",
    "properties": {
        "text": {
            "type": "string",
            "description": "要合成的文本",
        },
        "output_path": {
            "type": "string",
            "description": "输出文件路径，为空则返回 base64 音频",
        },
    },
    "required": ["text"],
}


def _handle_control_light(params: dict[str, Any]) -> str:
    """处理 openclaw_control_light 工具调用。"""
    entity_id = params.get("entity_id", "")
    on = params.get("on")
    if not entity_id or not str(entity_id).strip():
        return json.dumps(
            error_response("E_INVALID_PARAMS", "缺少必填参数 entity_id"),
            ensure_ascii=False,
        )
    if not isinstance(on, bool):
        return json.dumps(
            error_response("E_INVALID_PARAMS", "on 必须是布尔值"),
            ensure_ascii=False,
        )

    cfg = OpenClawConfig.from_env()
    client = HomeAssistantClient(config=cfg)
    result = _run_with(
        client,
        client.control_light(
            entity_id=entity_id,
            on=on,
            brightness=params.get("brightness"),
            color_temp=params.get("color_temp"),
        ),
    )
    return json.dumps(result, ensure_ascii=False)


def _handle_control_fan(params: dict[str, Any]) -> str:
    """处理 openclaw_control_fan 工具调用。"""
    entity_id = params.get("entity_id", "")
    on = params.get("on")
    if not entity_id or not str(entity_id).strip():
        return json.dumps(
            error_response("E_INVALID_PARAMS", "缺少必填参数 entity_id"),
            ensure_ascii=False,
        )
    if not isinstance(on, bool):
        return json.dumps(
            error_response("E_INVALID_PARAMS", "on 必须是布尔值"),
            ensure_ascii=False,
        )

    cfg = OpenClawConfig.from_env()
    client = HomeAssistantClient(config=cfg)
    result = _run_with(
        client,
        client.control_fan(
            entity_id=entity_id,
            on=on,
            speed=params.get("speed"),
        ),
    )
    return json.dumps(result, ensure_ascii=False)


def _handle_control_air_purifier(params: dict[str, Any]) -> str:
    """处理 openclaw_control_air_purifier 工具调用。"""
    entity_id = params.get("entity_id", "")
    on = params.get("on")
    if not entity_id or not str(entity_id).strip():
        return json.dumps(
            error_response("E_INVALID_PARAMS", "缺少必填参数 entity_id"),
            ensure_ascii=False,
        )
    if not isinstance(on, bool):
        return json.dumps(
            error_response("E_INVALID_PARAMS", "on 必须是布尔值"),
            ensure_ascii=False,
        )

    cfg = OpenClawConfig.from_env()
    client = HomeAssistantClient(config=cfg)
    result = _run_with(
        client,
        client.control_air_purifier(
            entity_id=entity_id,
            on=on,
            mode=params.get("mode"),
        ),
    )
    return json.dumps(result, ensure_ascii=False)


def _handle_speaker_voice_on(params: dict[str, Any]) -> str:
    """处理 openclaw_speaker_voice_on 工具调用。"""
    cfg = OpenClawConfig.from_env()
    client = HomeAssistantClient(config=cfg)
    result = _run_with(client, client.speaker_voice_on())
    return json.dumps(result, ensure_ascii=False)


def _handle_speaker_voice_off(params: dict[str, Any]) -> str:
    """处理 openclaw_speaker_voice_off 工具调用。"""
    cfg = OpenClawConfig.from_env()
    client = HomeAssistantClient(config=cfg)
    result = _run_with(client, client.speaker_voice_off())
    return json.dumps(result, ensure_ascii=False)


def _handle_speaker_say(params: dict[str, Any]) -> str:
    """处理 openclaw_speaker_say 工具调用。"""
    text = params.get("text", "")
    if not text or not str(text).strip():
        return json.dumps(
            error_response("E_INVALID_PARAMS", "缺少必填参数 text"),
            ensure_ascii=False,
        )

    cfg = OpenClawConfig.from_env()
    client = HomeAssistantClient(config=cfg)
    result = _run_with(client, client.speaker_say(text=text))
    return json.dumps(result, ensure_ascii=False)


def _handle_cluster_health(params: dict[str, Any]) -> str:
    """处理 openclaw_cluster_health 工具调用。"""
    cfg = OpenClawConfig.from_env()
    checker = ClusterChecker(config=cfg)
    result = _run_with(checker, checker.health_check())
    return json.dumps(result, ensure_ascii=False)


def _handle_device_lookup(params: dict[str, Any]) -> str:
    """处理 openclaw_device_lookup 工具调用。"""
    query = params.get("query", "")
    if not query or not str(query).strip():
        return json.dumps(
            error_response("E_INVALID_PARAMS", "缺少必填参数 query"),
            ensure_ascii=False,
        )

    cfg = OpenClawConfig.from_env()
    checker = ClusterChecker(config=cfg)
    result = checker.device_lookup(query=query)
    return json.dumps(result, ensure_ascii=False)


def _handle_chat(params: dict[str, Any]) -> str:
    """处理 openclaw_chat 工具调用。"""
    prompt = params.get("prompt", "")
    if not prompt or not str(prompt).strip():
        return json.dumps(
            error_response("E_INVALID_PARAMS", "缺少必填参数 prompt"),
            ensure_ascii=False,
        )

    cfg = OpenClawConfig.from_env()
    pipeline = AicgPipeline(config=cfg)
    result = _run_with(
        pipeline,
        pipeline.chat(
            prompt=prompt,
            level=params.get("level", "L1"),
            nsfw=params.get("nsfw", False),
            temperature=params.get("temperature", 0.7),
            max_tokens=params.get("max_tokens", 1024),
        ),
    )
    return json.dumps(result, ensure_ascii=False)


def _handle_generate_image(params: dict[str, Any]) -> str:
    """处理 openclaw_generate_image 工具调用。"""
    prompt = params.get("prompt", "")
    if not prompt or not str(prompt).strip():
        return json.dumps(
            error_response("E_INVALID_PARAMS", "缺少必填参数 prompt"),
            ensure_ascii=False,
        )

    cfg = OpenClawConfig.from_env()
    pipeline = AicgPipeline(config=cfg)
    result = _run_with(
        pipeline,
        pipeline.generate_image(
            prompt=prompt,
            width=params.get("width", 1024),
            height=params.get("height", 1024),
        ),
    )
    return json.dumps(result, ensure_ascii=False)


def _handle_text_to_speech(params: dict[str, Any]) -> str:
    """处理 openclaw_text_to_speech 工具调用。"""
    text = params.get("text", "")
    if not text or not str(text).strip():
        return json.dumps(
            error_response("E_INVALID_PARAMS", "缺少必填参数 text"),
            ensure_ascii=False,
        )

    cfg = OpenClawConfig.from_env()
    pipeline = AicgPipeline(config=cfg)
    result = _run_with(
        pipeline,
        pipeline.text_to_speech(
            text=text,
            output_path=params.get("output_path"),
        ),
    )
    return json.dumps(result, ensure_ascii=False)


def register(ctx) -> None:
    """把 openclaw_* 工具注册到插件上下文。"""
    ctx.register_tool(
        name="openclaw_health",
        description="检查 OpenClaw 网关健康状态",
        emoji="🐾",
        schema=OPENCLAW_HEALTH_SCHEMA,
        handler_func=_handle_health,
    )
    ctx.register_tool(
        name="openclaw_send_wechat",
        description="【已弃用】请改用 omni_wechat 插件的 wechat_send（直连 iLink）",
        emoji="💬",
        schema=OPENCLAW_SEND_WECHAT_SCHEMA,
        handler_func=_handle_send_wechat,
    )
    ctx.register_tool(
        name="openclaw_vision_chat",
        description="通过 Nemotron L1 进行单图视觉理解",
        emoji="🖼️",
        schema=OPENCLAW_VISION_CHAT_SCHEMA,
        handler_func=_handle_vision_chat,
    )
    ctx.register_tool(
        name="openclaw_audio_chat",
        description="通过 Nemotron L1 进行音频理解",
        emoji="🎧",
        schema=OPENCLAW_AUDIO_CHAT_SCHEMA,
        handler_func=_handle_audio_chat,
    )
    ctx.register_tool(
        name="openclaw_video_chat",
        description="通过 Nemotron L1 进行视频理解",
        emoji="🎬",
        schema=OPENCLAW_VIDEO_CHAT_SCHEMA,
        handler_func=_handle_video_chat,
    )
    ctx.register_tool(
        name="openclaw_control_light",
        description="通过 Home Assistant 控制灯光",
        emoji="💡",
        schema=OPENCLAW_CONTROL_LIGHT_SCHEMA,
        handler_func=_handle_control_light,
    )
    ctx.register_tool(
        name="openclaw_control_fan",
        description="通过 Home Assistant 控制风扇",
        emoji="🌀",
        schema=OPENCLAW_CONTROL_FAN_SCHEMA,
        handler_func=_handle_control_fan,
    )
    ctx.register_tool(
        name="openclaw_control_air_purifier",
        description="通过 Home Assistant 控制空气净化器",
        emoji="🌬️",
        schema=OPENCLAW_CONTROL_AIR_PURIFIER_SCHEMA,
        handler_func=_handle_control_air_purifier,
    )
    ctx.register_tool(
        name="openclaw_speaker_voice_on",
        description="开启扬声器语音模式",
        emoji="🔊",
        schema=OPENCLAW_SPEAKER_VOICE_ON_SCHEMA,
        handler_func=_handle_speaker_voice_on,
    )
    ctx.register_tool(
        name="openclaw_speaker_voice_off",
        description="关闭扬声器语音模式",
        emoji="🔇",
        schema=OPENCLAW_SPEAKER_VOICE_OFF_SCHEMA,
        handler_func=_handle_speaker_voice_off,
    )
    ctx.register_tool(
        name="openclaw_speaker_say",
        description="通过扬声器播报文本",
        emoji="📢",
        schema=OPENCLAW_SPEAKER_SAY_SCHEMA,
        handler_func=_handle_speaker_say,
    )
    ctx.register_tool(
        name="openclaw_cluster_health",
        description="执行集群健康巡检并返回 P0/P1/P2 分级报告",
        emoji="🩺",
        schema=OPENCLAW_CLUSTER_HEALTH_SCHEMA,
        handler_func=_handle_cluster_health,
    )
    ctx.register_tool(
        name="openclaw_device_lookup",
        description="在设备说明文档中查询设备信息",
        emoji="📖",
        schema=OPENCLAW_DEVICE_LOOKUP_SCHEMA,
        handler_func=_handle_device_lookup,
    )
    ctx.register_tool(
        name="openclaw_chat",
        description="调用 AICG 四层模型进行文本对话",
        emoji="🤖",
        schema=OPENCLAW_CHAT_SCHEMA,
        handler_func=_handle_chat,
    )
    ctx.register_tool(
        name="openclaw_generate_image",
        description="调用 ComfyUI 生成图像",
        emoji="🎨",
        schema=OPENCLAW_GENERATE_IMAGE_SCHEMA,
        handler_func=_handle_generate_image,
    )
    ctx.register_tool(
        name="openclaw_text_to_speech",
        description="调用 IndexTTS2 合成语音",
        emoji="🗣️",
        schema=OPENCLAW_TEXT_TO_SPEECH_SCHEMA,
        handler_func=_handle_text_to_speech,
    )
