"""omni_office 模板渲染（templates.py）单元测试。

``{{ var }}`` 占位符替换契约：
- 支持 ``{{name}}`` / ``{{ name }}`` 两种写法
- 缺失变量抛 :class:`OfficeTemplateError`，``missing`` 字段列出缺失键
- 无占位符时原样返回
"""

from __future__ import annotations

import pytest

from omni_office.errors import OfficeTemplateError
from omni_office.templates import extract_vars, render_template


class TestRenderTemplate:
    def test_basic_substitution(self) -> None:
        assert render_template("你好 {{name}}", {"name": "雪莉"}) == "你好 雪莉"

    def test_placeholder_with_spaces(self) -> None:
        assert render_template("{{ name }} 您好", {"name": "王工"}) == "王工 您好"

    def test_multiple_vars(self) -> None:
        out = render_template("{{greet}}，{{name}}！", {"greet": "早上好", "name": "A"})
        assert out == "早上好，A！"

    def test_repeated_placeholder_replaced_everywhere(self) -> None:
        out = render_template("{{x}}-{{x}}-{{x}}", {"x": "7"})
        assert out == "7-7-7"

    def test_no_placeholder_returns_as_is(self) -> None:
        assert render_template("纯文本", {}) == "纯文本"

    def test_non_str_value_coerced(self) -> None:
        assert render_template("数量：{{n}}", {"n": 42}) == "数量：42"

    def test_missing_var_raises(self) -> None:
        with pytest.raises(OfficeTemplateError) as exc_info:
            render_template("你好 {{name}}，来自 {{dept}}", {"name": "A"})
        assert exc_info.value.missing == ["dept"]

    def test_missing_multiple_vars_all_listed(self) -> None:
        with pytest.raises(OfficeTemplateError) as exc_info:
            render_template("{{a}} {{b}}", {})
        assert sorted(exc_info.value.missing) == ["a", "b"]

    def test_extra_vars_ignored(self) -> None:
        assert render_template("{{a}}", {"a": "1", "b": "2"}) == "1"


class TestExtractVars:
    def test_extracts_names(self) -> None:
        assert extract_vars("{{a}} 与 {{ b }}") == ["a", "b"]

    def test_deduplicates(self) -> None:
        assert extract_vars("{{x}}{{x}}") == ["x"]

    def test_empty_when_no_placeholder(self) -> None:
        assert extract_vars("没有占位符") == []
