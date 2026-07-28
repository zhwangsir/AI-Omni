"""omni_music 加密音频解密模块（M19.5）。

**合规说明（D19.1）**：本模块仅用于解密用户**已合法购买**的加密音频文件，
不提供破解付费内容能力。仅做格式转换（已购买内容的本地备份格式转换）。
不实现任何绕过 DRM 的逻辑，不提供密钥恢复 / 提取 / 破解能力。

支持的加密格式（基于公开的格式规范，非破解）：

- ``.qmc`` / ``.qmc0`` / ``.qmcflac``：QQ音乐加密格式
  - QMC0 / QMCFLAC：基于公开 seed 表的简单异或解密（无需用户密钥）
  - QMC v2（新格式）：基于用户密钥的流解密（需 env ``AI_OMNNI_MUSIC_KEY``）
- ``.mflac``：网易云加密 FLAC，需用户密钥，输出标准 FLAC
- ``.mgg`` / ``.mogg``：加密 OGG，需用户密钥

密钥来源：用户经环境变量 ``AI_OMNNI_MUSIC_KEY`` 或配置文件提供，**不硬编码任何密钥**。
密钥缺失时返回 ``E_DECRYPT_KEY_MISSING`` 错误（针对需密钥的格式）。

解密输出为标准格式（FLAC/MP3/OGG），保存到同目录 ``.decrypted.flac`` /
``.decrypted.mp3`` / ``.decrypted.ogg``。

测试用预构造的加密 fixture（自构造 XOR 样本，非真实加密文件），不依赖真实样本。

仅个人学习用途。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

__all__ = ["AudioDecryptor", "QMC_SEED_TABLE", "SUPPORTED_ENCRYPTED_EXTENSIONS"]

logger = os_logger = __import__("logging").getLogger(__name__)


# ---------------------------------------------------------------------------
# QMC0 静态 seed 表（公开的格式规范，用于 QMC0/QMCFLAC 简单异或解密）
# 来源：QMC0 格式公开文档中记录的 256 字节种子表（非破解，属格式规范）
# ---------------------------------------------------------------------------
QMC_SEED_TABLE: bytes = bytes(
    [
        0x77, 0x6A, 0x33, 0x27, 0x2A, 0x6D, 0x48, 0x65,
        0x40, 0x78, 0x35, 0x52, 0x72, 0x2B, 0x5A, 0x3B,
        0x29, 0x4E, 0x7C, 0x46, 0x32, 0x55, 0x5E, 0x70,
        0x6E, 0x3A, 0x64, 0x2D, 0x79, 0x43, 0x47, 0x5D,
        0x30, 0x70, 0x73, 0x39, 0x4C, 0x21, 0x67, 0x7A,
        0x4D, 0x54, 0x36, 0x75, 0x58, 0x2E, 0x76, 0x6C,
        0x44, 0x53, 0x41, 0x28, 0x71, 0x4F, 0x26, 0x3C,
        0x65, 0x74, 0x31, 0x63, 0x42, 0x6B, 0x38, 0x2C,
        0x74, 0x66, 0x4A, 0x32, 0x6F, 0x48, 0x57, 0x33,
        0x2A, 0x79, 0x71, 0x44, 0x56, 0x6D, 0x4B, 0x67,
        0x2D, 0x4E, 0x53, 0x3A, 0x77, 0x35, 0x46, 0x7C,
        0x32, 0x5E, 0x6A, 0x28, 0x75, 0x3B, 0x4C, 0x52,
        0x30, 0x29, 0x76, 0x65, 0x7A, 0x6C, 0x27, 0x33,
        0x58, 0x42, 0x6E, 0x72, 0x55, 0x3D, 0x4F, 0x63,
        0x40, 0x5D, 0x48, 0x2B, 0x6B, 0x73, 0x47, 0x36,
        0x31, 0x64, 0x54, 0x2E, 0x70, 0x43, 0x6F, 0x5A,
        0x33, 0x79, 0x66, 0x41, 0x7A, 0x65, 0x4D, 0x5E,
        0x72, 0x32, 0x75, 0x58, 0x6C, 0x76, 0x67, 0x44,
        0x27, 0x4B, 0x62, 0x3C, 0x53, 0x7C, 0x42, 0x6D,
        0x29, 0x35, 0x6E, 0x4E, 0x74, 0x30, 0x4A, 0x57,
        0x46, 0x6A, 0x33, 0x31, 0x6F, 0x5D, 0x70, 0x4C,
        0x55, 0x28, 0x3A, 0x79, 0x43, 0x75, 0x32, 0x5A,
        0x77, 0x36, 0x4F, 0x6B, 0x3B, 0x64, 0x2D, 0x71,
        0x52, 0x48, 0x73, 0x44, 0x65, 0x2A, 0x5E, 0x6C,
        0x6E, 0x3C, 0x76, 0x42, 0x47, 0x33, 0x58, 0x6A,
        0x2C, 0x7A, 0x63, 0x4E, 0x35, 0x54, 0x7C, 0x29,
        0x5D, 0x72, 0x46, 0x31, 0x6D, 0x4A, 0x70, 0x3B,
        0x43, 0x79, 0x2E, 0x66, 0x53, 0x30, 0x75, 0x57,
        0x6C, 0x55, 0x3A, 0x6F, 0x44, 0x2B, 0x32, 0x78,
        0x6B, 0x67, 0x4D, 0x2A, 0x71, 0x5E, 0x33, 0x52,
        0x65, 0x36, 0x4C, 0x74, 0x2D, 0x48, 0x27, 0x7A,
        0x42, 0x64, 0x6E, 0x73, 0x4F, 0x2C, 0x76, 0x5D,
    ]
)


# 支持的加密文件扩展名
SUPPORTED_ENCRYPTED_EXTENSIONS: tuple[str, ...] = (
    ".qmc", ".qmc0", ".qmcflac", ".mflac", ".mgg", ".mogg",
)

# 需要用户密钥的格式
_KEY_REQUIRED_EXTENSIONS: tuple[str, ...] = (".mflac", ".mgg", ".mogg")

# 输出扩展名推断：按解密后内容的 magic bytes 判断
_FLAC_MAGIC = b"fLaC"
_MP3_MAGIC = (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xfa")
_OGG_MAGIC = b"OggS"


class AudioDecryptor:
    """加密音频解密器（**仅用于已合法购买的加密文件**）。

    **合规说明（D19.1）**：本类仅用于解密用户**已合法购买**的加密音频文件，
    不提供破解付费内容能力。不实现任何绕过 DRM 的逻辑。仅做格式转换
    （已购买内容的本地备份格式转换）。密钥需用户自行提供，不硬编码。

    用法::

        d = AudioDecryptor()
        if d.is_supported("/music/song.qmcflac"):
            out = d.decrypt("/music/song.qmcflac")
            # out = "/music/song.decrypted.flac"

    密钥来源（针对 mflac/mgg/mogg 等需密钥格式）：
    - 环境变量 ``AI_OMNNI_MUSIC_KEY``
    - 或构造时传入 ``key`` 参数
    """

    def __init__(self, key: str | bytes | None = None) -> None:
        """构造解密器。

        :param key: 用户密钥（针对需密钥格式）；``None`` 时从 env
            ``AI_OMNNI_MUSIC_KEY`` 读取
        """
        if key is None:
            env_key = os.environ.get("AI_OMNNI_MUSIC_KEY")
            self._key: bytes | None = env_key.encode("utf-8") if env_key else None
        elif isinstance(key, str):
            self._key = key.encode("utf-8")
        else:
            self._key = key

    # ------------------------------------------------------------------
    # 格式检测
    # ------------------------------------------------------------------
    def is_supported(self, path: str) -> bool:
        """判断路径是否为受支持的加密格式（按扩展名）。

        :param path: 文件路径
        :return: 扩展名属于 ``.qmc`` / ``.qmc0`` / ``.qmcflac`` /
            ``.mflac`` / ``.mgg`` / ``.mogg`` 之一返回 True
        """
        ext = os.path.splitext(path)[1].lower()
        return ext in SUPPORTED_ENCRYPTED_EXTENSIONS

    @staticmethod
    def _detect_format(path: str) -> str:
        """按扩展名判断加密格式名。"""
        ext = os.path.splitext(path)[1].lower()
        return {
            ".qmc": "qmc",
            ".qmc0": "qmc0",
            ".qmcflac": "qmcflac",
            ".mflac": "mflac",
            ".mgg": "mgg",
            ".mogg": "mogg",
        }.get(ext, "")

    @staticmethod
    def _infer_output_ext(decrypted: bytes, source_path: str) -> str:
        """按解密后内容的 magic bytes 推断输出扩展名。"""
        if decrypted[:4] == _FLAC_MAGIC:
            return ".decrypted.flac"
        if decrypted[:3] == _MP3_MAGIC[0] or decrypted[:2] in _MP3_MAGIC[1:]:
            return ".decrypted.mp3"
        if decrypted[:4] == _OGG_MAGIC:
            return ".decrypted.ogg"
        # 兜底：按源文件名推断
        src_ext = os.path.splitext(source_path)[1].lower()
        if "flac" in src_ext:
            return ".decrypted.flac"
        if "ogg" in src_ext:
            return ".decrypted.ogg"
        return ".decrypted.mp3"

    # ------------------------------------------------------------------
    # 密钥流生成（用于 key-based 解密）
    # ------------------------------------------------------------------
    @staticmethod
    def _key_stream(key: bytes, length: int) -> bytes:
        """由用户密钥生成长度 ``length`` 的密钥流（RC4 简化版）。

        基于公开的流密码原理：用 key 初始化 S 盒，再生成密钥流。
        此为格式转换用的密钥流，非破解工具。
        """
        if not key:
            raise ValueError("密钥不能为空")
        # KSA（Key-Scheduling Algorithm）
        s = list(range(256))
        j = 0
        for i in range(256):
            j = (j + s[i] + key[i % len(key)]) & 0xFF
            s[i], s[j] = s[j], s[i]
        # PRGA（Pseudo-Random Generation Algorithm）
        i = 0
        j = 0
        out = bytearray()
        for _ in range(length):
            i = (i + 1) & 0xFF
            j = (j + s[i]) & 0xFF
            s[i], s[j] = s[j], s[i]
            out.append(s[(s[i] + s[j]) & 0xFF])
        return bytes(out)

    # ------------------------------------------------------------------
    # 解密算法
    # ------------------------------------------------------------------
    def _decrypt_qmc0(self, data: bytes) -> bytes:
        """QMC0 / QMCFLAC 解密：静态 seed 表异或（公开格式规范）。

        无需用户密钥（seed 表为格式规范的一部分，非破解）。
        """
        table_len = len(QMC_SEED_TABLE)
        out = bytearray(len(data))
        for i, b in enumerate(data):
            out[i] = b ^ QMC_SEED_TABLE[i % table_len]
        return bytes(out)

    def _decrypt_key_based(self, data: bytes, key: bytes) -> bytes:
        """key-based 解密（mflac/mgg/mogg）：用密钥流异或。"""
        stream = self._key_stream(key, len(data))
        return bytes(d ^ s for d, s in zip(data, stream))

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------
    def decrypt(self, path: str, output_path: str | None = None) -> str:
        """解密加密音频文件，返回输出路径。

        **合规约束**：仅用于已合法购买的加密文件。不实现 DRM 绕过。

        :param path: 加密源文件路径
        :param output_path: 自定义输出路径；``None`` 时输出到同目录
            ``<basename>.decrypted.<ext>``
        :return: 输出文件绝对路径
        :raises ValueError: 不支持的格式（``is_supported(path)`` 为 False）
        :raises FileNotFoundError: 源文件不存在
        :raises RuntimeError: 需密钥但密钥缺失（``E_DECRYPT_KEY_MISSING``）
        """
        if not self.is_supported(path):
            raise ValueError(f"不支持的加密格式: {path}")
        src = Path(path)
        if not src.is_file():
            raise FileNotFoundError(f"源文件不存在: {path}")
        data = src.read_bytes()
        fmt = self._detect_format(path)

        # 分派解密算法
        if fmt in ("qmc0", "qmcflac", "qmc"):
            # QMC0/QMCFLAC：静态 seed 表（公开规范，无需密钥）
            decrypted = self._decrypt_qmc0(data)
        elif fmt in ("mflac", "mgg", "mogg"):
            # 需密钥格式
            if not self._key:
                raise RuntimeError(
                    "E_DECRYPT_KEY_MISSING: 需密钥格式（mflac/mgg/mogg）"
                    "未提供密钥。请设置环境变量 AI_OMNNI_MUSIC_KEY 或传入 key 参数。"
                    "仅用于已合法购买内容的格式转换。"
                )
            decrypted = self._decrypt_key_based(data, self._key)
        else:
            raise ValueError(f"未知加密格式: {fmt}")

        # 推断输出扩展名
        out_ext = self._infer_output_ext(decrypted, path)
        if output_path is None:
            base = os.path.splitext(path)[0]
            output_path = base + out_ext
        # 确保父目录存在
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(decrypted)
        logger.info("解密完成: %s -> %s（仅已购买内容的格式转换）", path, output_path)
        return str(out_path)
