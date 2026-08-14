"""长文本分段器（M32.30：IndexTTS2 输入规范）。

指南第四步：长文本拆分为每段 ≤70 字的短句，分段生成后拼接；
切分贴合台配说话节奏——优先句末标点，其次逗号/顿号，最后硬切。
"""

from __future__ import annotations

import re

#: 指南推荐单段上限（字）
DEFAULT_MAX_LEN = 70

#: 句末标点（切段边界，保留标点）
_SENT_END_RE = re.compile(r"[^。！？…!?]+[。！？…!?]*")
#: 次级停顿标点（长句内部回退切分）
_SUB_PAUSE = "，、；;,;"


def segment_text(text: str, max_len: int = DEFAULT_MAX_LEN) -> list[str]:
    """把长文本拆分为 ≤ ``max_len`` 字的短句列表。

    规则：
    1. 先按句末标点（。！？…!?）切句，短句在容量内合并；
    2. 单句超限时回退按逗号/顿号/分号切；
    3. 仍超限则硬切，保证每段 ≤ ``max_len`` 字。

    空文本返回空列表；``max_len`` 必须 > 0。
    """
    if max_len <= 0:
        raise ValueError("max_len 必须 > 0")
    normalized = " ".join(text.split())
    if not normalized:
        return []
    sentences = [m.group(0) for m in _SENT_END_RE.finditer(normalized) if m.group(0).strip()]
    segments: list[str] = []
    pending = ""
    for sentence in sentences:
        if not pending:
            pending = sentence
        elif len(pending) + len(sentence) <= max_len:
            pending += sentence
        else:
            segments.extend(_emit(pending, max_len))
            pending = sentence
    if pending:
        segments.extend(_emit(pending, max_len))
    return segments


def _emit(sentence: str, max_len: int) -> list[str]:
    """输出单句：≤max_len 直接返回；否则先按次级停顿切，再硬切。"""
    if len(sentence) <= max_len:
        return [sentence]
    parts: list[str] = []
    buf = ""
    for ch in sentence:
        buf += ch
        if len(buf) >= max_len or (ch in _SUB_PAUSE and len(buf) >= max_len // 2):
            parts.append(buf)
            buf = ""
    if buf:
        parts.append(buf)
    # 次级切分后仍可能超长（无停顿标点的长串）→ 硬切兜底
    final: list[str] = []
    for part in parts:
        while len(part) > max_len:
            final.append(part[:max_len])
            part = part[max_len:]
        if part:
            final.append(part)
    return final
