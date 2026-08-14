"""omni_office 插件的异常体系。

所有可被调用方预期的错误都继承自 :class:`OfficeError`，
tools/CLI 层统一捕获并映射为 ``{"ok": false, "error": {"code", "message"}}`` 响应。
"""

from __future__ import annotations


class OfficeError(Exception):
    """办公插件所有可预期错误的基类。"""


class OfficeValidationError(OfficeError):
    """参数非法（空标题、时间区间颠倒、缺收件人等）时抛出。"""


class OfficeNotFoundError(OfficeError):
    """文档 / 版本 / 邮件 / 模板 / 规则 / 日程不存在时抛出。"""


class OfficeConflictError(OfficeError):
    """日程冲突时抛出；``conflicts`` 携带冲突事件摘要列表。"""

    def __init__(self, message: str, conflicts: list[dict] | None = None) -> None:
        super().__init__(message)
        self.conflicts: list[dict] = conflicts or []


class OfficeTemplateError(OfficeError):
    """模板渲染失败（缺失变量）时抛出；``missing`` 列出缺失变量名。"""

    def __init__(self, message: str, missing: list[str] | None = None) -> None:
        super().__init__(message)
        self.missing: list[str] = missing or []


class OfficeBackendError(OfficeError):
    """邮件后端不可用（SMTP/IMAP 未配置或连接失败）时抛出。"""
