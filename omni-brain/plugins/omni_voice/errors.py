"""omni_voice 插件的异常体系。

所有可被调用方预期的错误都继承自 :class:`VoiceError`，
tools/CLI 层统一捕获并映射为 ``{"ok": false, "error": ...}`` 响应。
"""


class VoiceError(Exception):
    """语音插件所有可预期错误的基类。"""


class VoiceBackendError(VoiceError):
    """后端依赖缺失或后端初始化/调用失败时抛出（消息中附安装提示）。"""


class PipelineStateError(VoiceError):
    """管道状态非法操作时抛出（如重复启动、未启动就监听）。"""
