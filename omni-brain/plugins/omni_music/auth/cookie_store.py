"""CookieStore：AES-256-GCM 加密落盘（M17.3）。

把各音乐源的登录 Cookie 加密后存储到 ``~/.ai-omni/cookies/<source>.enc``。
密钥派生优先级：
1. 环境变量 ``AI_OMNI_COOKIE_KEY``
2. 机器特征（hostname + username 派生）

安全要求：
- 明文 cookie 绝不落盘；密文文件用 AES-256-GCM 加密（含 nonce + tag）
- 密钥不硬编码到源码，从环境变量或机器特征派生
- ``cryptography`` 不可用时降级为 ``E_BACKEND_UNAVAILABLE``（不拖垮调用方）

合规说明（D17.4）：仅存储用户本人扫码登录获得的 Cookie，不破解付费内容。
仅个人学习用途。
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import socket
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 默认存储目录（用户家目录下 .ai-omni/cookies）
_DEFAULT_BASE_DIR = Path.home() / ".ai-omni" / "cookies"

# AES-256-GCM 密钥长度（32 字节）
_KEY_BYTES = 32

# GCM nonce 长度（12 字节，NIST 推荐）
_NONCE_BYTES = 12


def _derive_key(passphrase: str, salt: bytes = b"ai-omni-cookie-salt-v1") -> bytes:
    """从 passphrase + salt 派生 32 字节 AES-256 密钥。

    使用 PBKDF2-HMAC-SHA256，100k 轮迭代（兼顾安全与性能）。

    :param passphrase: 口令字符串
    :param salt: 盐值（固定常量，避免不同进程派生出不同密钥）
    :return: 32 字节密钥
    """
    # hashlib 是标准库，无需惰性导入
    kdf = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, 100_000)
    return kdf[:_KEY_BYTES]


def _machine_passphrase() -> str:
    """从机器特征（hostname + username）派生口令字符串。

    作为 ``AI_OMNI_COOKIE_KEY`` 未设置时的回退，保证同一用户在同一机器上
    可解密自己之前加密的 cookie。

    :return: 口令字符串
    """
    hostname = socket.gethostname() or "unknown-host"
    username = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown-user"
    return f"ai-omni::{hostname}::{username}"


def _resolve_passphrase(explicit: str | None = None) -> str:
    """解析密钥口令：显式传入 > 环境变量 > 机器特征。

    :param explicit: 调用方显式传入的 passphrase（优先级最高）
    :return: 口令字符串
    """
    if explicit:
        return explicit
    env_key = os.environ.get("AI_OMNI_COOKIE_KEY")
    if env_key:
        return env_key
    return _machine_passphrase()


class CookieStore:
    """AES-256-GCM 加密 Cookie 存储。

    存储路径：``<base_dir>/<source>.enc``，文件内容 = base64(nonce + ciphertext + tag)。
    不同 source 各自独立文件，互不干扰。

    :ivar base_dir: 存储目录，默认 ``~/.ai-omni/cookies``
    :ivar passphrase: 密钥口令（运行时保留用于派生密钥；不写入文件）
    """

    def __init__(
        self,
        base_dir: Path | None = None,
        passphrase: str | None = None,
    ) -> None:
        """构造 CookieStore。

        :param base_dir: 存储目录；None 时使用默认 ``~/.ai-omni/cookies``
        :param passphrase: 密钥口令；None 时按 env → 机器特征派生
        """
        self.base_dir: Path = base_dir if base_dir is not None else _DEFAULT_BASE_DIR
        self.passphrase: str = _resolve_passphrase(passphrase)
        self._key: bytes = _derive_key(self.passphrase)

    def _enc_path(self, source: str) -> Path:
        """返回指定 source 的密文文件路径。"""
        return self.base_dir / f"{source}.enc"

    def _ensure_dir(self) -> None:
        """确保 base_dir 存在（权限允许可写）。"""
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("无法创建 cookie 存储目录 %s: %s", self.base_dir, exc)

    def save(self, source: str, cookies: dict[str, str]) -> dict[str, Any] | None:
        """加密保存 cookie 到 ``<base_dir>/<source>.enc``。

        :param source: 音乐源标识（如 ``netease`` / ``qqmusic``）
        :param cookies: cookie dict
        :return: 成功返回 None；cryptography 不可用时返回错误 dict
        """
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:
            logger.warning("cryptography 不可用，无法加密保存 cookie: %s", exc)
            return {
                "ok": False,
                "error": {
                    "code": "E_BACKEND_UNAVAILABLE",
                    "message": f"cryptography 不可用: {exc}",
                },
            }

        self._ensure_dir()
        aesgcm = AESGCM(self._key)
        nonce = os.urandom(_NONCE_BYTES)
        plaintext = json.dumps(cookies, ensure_ascii=False).encode("utf-8")
        # AESGCM.encrypt 返回 ciphertext + tag（16 字节 tag 附加在尾部）
        ct_with_tag = aesgcm.encrypt(nonce, plaintext, associated_data=None)
        # 落盘格式：base64(nonce + ct_with_tag)
        blob = nonce + ct_with_tag
        encoded = base64.b64encode(blob)
        try:
            self._enc_path(source).write_bytes(encoded)
        except OSError as exc:
            logger.warning("写入 cookie 文件失败 %s: %s", source, exc)
            return {
                "ok": False,
                "error": {
                    "code": "E_IO_FAILED",
                    "message": f"写入 cookie 文件失败: {exc}",
                },
            }
        return None

    def load(self, source: str) -> dict[str, str] | None:
        """读取并解密 ``<base_dir>/<source>.enc``。

        :param source: 音乐源标识
        :return: cookie dict；文件不存在或解密失败返回 None
        """
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:
            logger.warning("cryptography 不可用，无法解密 cookie: %s", exc)
            return None

        enc_path = self._enc_path(source)
        if not enc_path.is_file():
            return None
        try:
            encoded = enc_path.read_bytes()
            blob = base64.b64decode(encoded)
        except (OSError, ValueError) as exc:
            logger.warning("读取 cookie 文件失败 %s: %s", source, exc)
            return None
        # 拆分 nonce + ct_with_tag
        if len(blob) < _NONCE_BYTES:
            logger.warning("cookie 文件内容过短: %s", source)
            return None
        nonce = blob[:_NONCE_BYTES]
        ct_with_tag = blob[_NONCE_BYTES:]
        aesgcm = AESGCM(self._key)
        try:
            plaintext = aesgcm.decrypt(nonce, ct_with_tag, associated_data=None)
        except Exception as exc:  # noqa: BLE001 - 解密失败统一返回 None
            logger.warning("cookie 解密失败 %s: %s", source, exc)
            return None
        try:
            return json.loads(plaintext.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            logger.warning("cookie JSON 解析失败 %s: %s", source, exc)
            return None

    def clear(self, source: str) -> None:
        """删除指定 source 的密文文件；不存在则静默（幂等）。

        :param source: 音乐源标识
        """
        enc_path = self._enc_path(source)
        try:
            if enc_path.is_file():
                enc_path.unlink()
        except OSError as exc:
            logger.warning("删除 cookie 文件失败 %s: %s", source, exc)


class FakeCookieStore:
    """内存版 CookieStore：不加密、不落盘，仅供测试与演示使用。

    接口与 :class:`CookieStore` 一致，但 ``save`` 返回 None（恒成功）。
    """

    def __init__(self) -> None:
        """构造空 fake store。"""
        self._store: dict[str, dict[str, str]] = {}

    def save(self, source: str, cookies: dict[str, str]) -> dict[str, Any] | None:
        """内存保存；返回 None（恒成功）。"""
        self._store[source] = dict(cookies)
        return None

    def load(self, source: str) -> dict[str, str] | None:
        """返回内存中的 cookie；不存在返回 None。"""
        return self._store.get(source)

    def clear(self, source: str) -> None:
        """从内存删除；不存在静默。"""
        self._store.pop(source, None)
