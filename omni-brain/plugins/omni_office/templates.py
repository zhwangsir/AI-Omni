"""omni_office 轻量模板渲染：``{{ var }}`` 占位符替换。

刻意不用 str.format / Jinja2：邮件与文档正文常含 JSON 花括号，
``{{name}}`` 双花括号语法可避免误伤，且零第三方依赖。

缺失变量抛 :class:`OfficeTemplateError`（``missing`` 列出缺失键），
由 tools 层映射为 ``E_TEMPLATE_ERROR``。
"""

from __future__ import annotations

import re
from typing import Any

from .errors import OfficeTemplateError

#: 占位符模式：{{name}} 或 {{ name }}，变量名为标识符
_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def extract_vars(text: str) -> list[str]:
    """提取模板中的全部变量名（去重，保持出现顺序）。"""
    seen: dict[str, None] = {}
    for match in _PLACEHOLDER.finditer(text):
        seen.setdefault(match.group(1))
    return list(seen)


def render_template(text: str, vars: dict[str, Any] | None = None) -> str:
    """渲染模板：把所有 ``{{ var }}`` 替换为 ``vars[var]``。

    :param text: 模板文本
    :param vars: 变量表；缺失变量抛 :class:`OfficeTemplateError`
    :return: 渲染后的文本
    """
    values = vars or {}
    missing = [name for name in extract_vars(text) if name not in values]
    if missing:
        raise OfficeTemplateError(
            f"模板缺失变量: {', '.join(missing)}", missing=missing
        )

    def _sub(match: re.Match[str]) -> str:
        return str(values[match.group(1)])

    return _PLACEHOLDER.sub(_sub, text)
