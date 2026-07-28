"""权限系统单元测试：白名单宽松起步、严格模式拒绝并告警、fs 路径参数解析、权限类型。"""

from __future__ import annotations

import logging

import pytest

from omni_sdk.permissions import PermissionChecker


def test_permission_checker_defaults_allow() -> None:
    """无 allowed 列表时，默认宽松模式：任意权限请求都返回 True。"""
    checker = PermissionChecker()
    assert checker.check("network") is True
    assert checker.check("voice.listen") is True
    assert checker.check("fs.read:/etc/passwd") is True


def test_check_permission_allowed() -> None:
    """在 allowed 列表中的权限返回 True，且不打印 warning。"""
    checker = PermissionChecker(allowed=["voice.listen", "tools.register"])
    assert checker.check("voice.listen") is True
    assert checker.check("tools.register") is True


def test_check_permission_denied_in_strict_mode_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """严格模式下越权返回 False 并记录 warning。"""
    checker = PermissionChecker(
        allowed=["voice.listen"], policy="strict", logger=logging.getLogger("omni_sdk.test.perm")
    )
    with caplog.at_level(logging.WARNING, logger="omni_sdk.test.perm"):
        result = checker.check("network")
    assert result is False
    assert any("network" in r.message for r in caplog.records)


def test_check_permission_denied_in_lenient_mode_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """宽松模式下越权返回 True（放行），但仍记录 warning。"""
    checker = PermissionChecker(
        allowed=["voice.listen"], policy="lenient", logger=logging.getLogger("omni_sdk.test.perm.lenient")
    )
    with caplog.at_level(logging.WARNING, logger="omni_sdk.test.perm.lenient"):
        result = checker.check("network")
    assert result is True
    assert any("network" in r.message for r in caplog.records)


def test_parse_fs_permission_with_path() -> None:
    """fs.read:<path> 权限带路径参数解析：路径精确匹配则放行。"""
    checker = PermissionChecker(
        allowed=["fs.read:./state", "fs.write:./state"], policy="strict"
    )
    assert checker.check("fs.read:./state") is True
    assert checker.check("fs.write:./state") is True
    # 路径不匹配则拒绝（严格模式）
    assert checker.check("fs.read:/etc/passwd") is False


def test_fs_permission_path_prefix_match() -> None:
    """fs.read:./state 应覆盖其子路径 fs.read:./state/voice.json。"""
    checker = PermissionChecker(
        allowed=["fs.read:./state"], policy="strict"
    )
    assert checker.check("fs.read:./state/voice.json") is True
    assert checker.check("fs.read:./state/nested/deep.json") is True
    # 完全不相关的路径拒绝
    assert checker.check("fs.read:/var/log") is False


def test_fs_permission_without_arg_grants_all_of_type() -> None:
    """allowed 中 fs.read 无路径参数时，覆盖该类型所有路径。"""
    checker = PermissionChecker(
        allowed=["fs.read"], policy="strict"
    )
    assert checker.check("fs.read:./state") is True
    assert checker.check("fs.read:/etc/passwd") is True
    # 但 fs.write 仍不在白名单
    assert checker.check("fs.write:./state") is False


def test_permission_types_supported() -> None:
    """支持多种已知权限类型：network / voice.listen / home.control / fs.* / tools.register。"""
    checker = PermissionChecker(
        allowed=[
            "network",
            "voice.listen",
            "home.control",
            "fs.read:./state",
            "fs.write:./state",
            "tools.register",
        ],
        policy="strict",
    )
    assert checker.check("network") is True
    assert checker.check("voice.listen") is True
    assert checker.check("home.control") is True
    assert checker.check("fs.read:./state") is True
    assert checker.check("fs.write:./state") is True
    assert checker.check("tools.register") is True


def test_strict_policy_default_is_lenient() -> None:
    """默认 policy 为 lenient。"""
    checker = PermissionChecker(allowed=["voice.listen"])
    assert checker.policy == "lenient"


def test_check_with_no_arg_permission_request_matches_bare_allowed() -> None:
    """allowed 含 voice.listen，请求 voice.listen（无参数）应放行。"""
    checker = PermissionChecker(allowed=["voice.listen"], policy="strict")
    assert checker.check("voice.listen") is True
