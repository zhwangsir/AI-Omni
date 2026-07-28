"""权限系统：插件运行时能力校验。

D15.3 决策：白名单宽松起步——manifest 未声明的权限请求，宽松模式返回 True 但记录 warning；
严格模式返回 False 并记录 warning。后续按需收紧为默认严格。
支持带参数权限 ``fs.read:<path>`` / ``fs.write:<path>``：路径前缀匹配。
"""

from __future__ import annotations

import logging
from typing import Iterable

# 已知权限前缀清单（与 manifest.validate_manifest 一致）
_KNOWN_PERMISSIONS: frozenset[str] = frozenset(
    {"network", "voice.listen", "home.control", "fs.read", "fs.write", "tools.register"}
)


def _split_permission(permission: str) -> tuple[str, str]:
    """拆分权限字符串为 (type, arg)。

    ``fs.read:./state`` -> ``("fs.read", "./state")``
    ``voice.listen`` -> ``("voice.listen", "")``
    """
    if ":" in permission:
        perm_type, _, arg = permission.partition(":")
        return perm_type, arg
    return permission, ""


def _path_matches(allowed_arg: str, requested_arg: str) -> bool:
    """路径前缀匹配：allowed_arg 是 requested_arg 的前缀（按 path 分隔符对齐）。"""
    if not allowed_arg:
        return True
    if not requested_arg:
        return False
    if requested_arg == allowed_arg:
        return True
    # 子路径匹配：./state 应覆盖 ./state/voice.json
    return requested_arg.startswith(allowed_arg.rstrip("/") + "/")


class PermissionChecker:
    """权限校验器：基于白名单 + 策略（宽松/严格）。

    宽松策略（默认）：未授予的权限返回 True 但记录 warning。
    严格策略：未授予的权限返回 False 并记录 warning。
    """

    def __init__(
        self,
        allowed: Iterable[str] | None = None,
        policy: str = "lenient",
        logger: logging.Logger | None = None,
    ) -> None:
        """构造权限校验器。

        :param allowed: 允许的权限白名单；None 表示空（宽松模式下仍放行所有请求）
        :param policy: ``lenient`` (默认) 或 ``strict``
        :param logger: 可选 logger；默认 ``omni.sdk.permissions``
        """
        if policy not in ("lenient", "strict"):
            raise ValueError(f"未知 policy: {policy!r}")
        self.allowed: set[str] = set(allowed or [])
        self.policy: str = policy
        self._logger = logger or logging.getLogger("omni.sdk.permissions")

    def check(self, permission: str) -> bool:
        """检查权限是否被授予。

        :param permission: 权限字符串，可带参数（如 ``fs.read:./state``）
        :return: 宽松模式恒返回 True（仅记录 warning）；严格模式下未授予返回 False
        """
        if self._is_granted(permission):
            return True
        if self.policy == "lenient":
            self._logger.warning(
                "越权告警：插件请求未授予的权限 %s（宽松模式，已放行）", permission
            )
            return True
        self._logger.warning(
            "越权拒绝：插件请求未授予的权限 %s（严格模式，已拒绝）", permission
        )
        return False

    def _is_granted(self, permission: str) -> bool:
        """判断 permission 是否落在 allowed 白名单内。

        - 同类型无参数 allowed 项覆盖该类型所有参数
        - 同类型有参数 allowed 项按路径前缀匹配
        """
        perm_type, perm_arg = _split_permission(permission)
        for allowed_perm in self.allowed:
            allowed_type, allowed_arg = _split_permission(allowed_perm)
            if allowed_type != perm_type:
                continue
            if not allowed_arg:
                return True  # allowed 无参数 → 覆盖该类型所有请求
            if not perm_arg:
                continue  # allowed 有参数但请求无参数 → 不匹配
            if _path_matches(allowed_arg, perm_arg):
                return True
        return False
