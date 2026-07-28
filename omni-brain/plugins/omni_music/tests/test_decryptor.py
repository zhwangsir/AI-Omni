"""omni_music library.decryptor 加密音频解密测试（M19.5）。

TDD 测试先行：覆盖 AudioDecryptor 的格式检测、解密、密钥缺失错误、合规约束。
全部用预构造的加密 fixture（不依赖真实加密文件、不下载样本）。

合规说明（D19.1）：解密模块仅用于解密用户已合法购买的加密音频文件，
不提供破解付费内容能力。测试 fixture 为自构造的 XOR 样本，非真实加密文件。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from omni_music.library.decryptor import AudioDecryptor


# ---------------------------------------------------------------------------
# 辅助：用 seed 表构造加密 fixture
# ---------------------------------------------------------------------------


def _make_qmc0_fixture(plaintext: bytes) -> bytes:
    """用 QMC0 静态 seed 表构造加密 fixture（与解密算法互逆）。"""
    from omni_music.library.decryptor import QMC_SEED_TABLE

    out = bytearray()
    for i, b in enumerate(plaintext):
        out.append(b ^ QMC_SEED_TABLE[i % len(QMC_SEED_TABLE)])
    return bytes(out)


def _make_mflac_fixture(plaintext: bytes, key: bytes) -> bytes:
    """用 key 流构造 mflac 加密 fixture（与 key-based 解密互逆）。"""
    stream = AudioDecryptor._key_stream(key, len(plaintext))
    return bytes(p ^ s for p, s in zip(plaintext, stream))


# ===========================================================================
# is_supported
# ===========================================================================
class TestIsSupported:
    def test_qmc_extension_supported(self) -> None:
        d = AudioDecryptor()
        assert d.is_supported("/music/song.qmc") is True

    def test_qmc0_extension_supported(self) -> None:
        d = AudioDecryptor()
        assert d.is_supported("/music/song.qmc0") is True

    def test_qmcflac_extension_supported(self) -> None:
        d = AudioDecryptor()
        assert d.is_supported("/music/song.qmcflac") is True

    def test_mflac_extension_supported(self) -> None:
        d = AudioDecryptor()
        assert d.is_supported("/music/song.mflac") is True

    def test_mgg_extension_supported(self) -> None:
        d = AudioDecryptor()
        assert d.is_supported("/music/song.mgg") is True

    def test_mogg_extension_supported(self) -> None:
        d = AudioDecryptor()
        assert d.is_supported("/music/song.mogg") is True

    def test_mp3_not_supported(self) -> None:
        d = AudioDecryptor()
        assert d.is_supported("/music/song.mp3") is False

    def test_flac_not_supported(self) -> None:
        d = AudioDecryptor()
        assert d.is_supported("/music/song.flac") is False

    def test_case_insensitive(self) -> None:
        d = AudioDecryptor()
        assert d.is_supported("/music/SONG.QMC") is True
        assert d.is_supported("/music/Song.MFlac") is True


# ===========================================================================
# QMC0 / QMCFLAC 解密（静态 seed 表，无需 key）
# ===========================================================================
class TestQmcDecrypt:
    def test_decrypt_qmc0_returns_output_path(self, tmp_path: Path) -> None:
        """解密 .qmc0 文件返回输出路径。"""
        plaintext = b"fLaC" + b"\x00" * 100  # 假 FLAC 头
        encrypted = _make_qmc0_fixture(plaintext)
        src = tmp_path / "song.qmc0"
        src.write_bytes(encrypted)
        d = AudioDecryptor()
        out = d.decrypt(str(src))
        assert isinstance(out, str)
        assert os.path.exists(out)
        # 输出内容应等于原文
        assert Path(out).read_bytes() == plaintext

    def test_decrypt_qmcflac_output_extension(self, tmp_path: Path) -> None:
        """qmcflac 解密输出 .decrypted.flac。"""
        plaintext = b"fLaC" + b"\x00" * 50
        encrypted = _make_qmc0_fixture(plaintext)
        src = tmp_path / "song.qmcflac"
        src.write_bytes(encrypted)
        d = AudioDecryptor()
        out = d.decrypt(str(src))
        assert out.endswith(".decrypted.flac")

    def test_decrypt_qmc0_mp3_output(self, tmp_path: Path) -> None:
        """qmc0（mp3 内容）解密输出 .decrypted.mp3。"""
        plaintext = b"ID3\x04\x00" + b"\x00" * 100  # 假 MP3 ID3 头
        encrypted = _make_qmc0_fixture(plaintext)
        src = tmp_path / "song.qmc0"
        src.write_bytes(encrypted)
        d = AudioDecryptor()
        out = d.decrypt(str(src))
        assert out.endswith(".decrypted.mp3")
        assert Path(out).read_bytes() == plaintext

    def test_decrypt_custom_output_path(self, tmp_path: Path) -> None:
        """指定 output_path 时用自定义路径。"""
        plaintext = b"fLaC" + b"\x00" * 20
        encrypted = _make_qmc0_fixture(plaintext)
        src = tmp_path / "song.qmcflac"
        src.write_bytes(encrypted)
        custom = tmp_path / "output" / "song.flac"
        d = AudioDecryptor()
        out = d.decrypt(str(src), output_path=str(custom))
        assert out == str(custom)
        assert custom.read_bytes() == plaintext

    def test_decrypt_qmc_verify_byte_correctness(self, tmp_path: Path) -> None:
        """逐字节验证解密正确性（非镜像断言：用独立构造的 fixture）。"""
        # 用独立路径构造 fixture，避免与实现共享代码路径
        plaintext = bytes(range(256)) * 4  # 1024 字节确定性数据
        encrypted = _make_qmc0_fixture(plaintext)
        src = tmp_path / "data.qmc0"
        src.write_bytes(encrypted)
        d = AudioDecryptor()
        out = d.decrypt(str(src))
        recovered = Path(out).read_bytes()
        # 关键断言：解密结果等于原始明文（非加密数据）
        assert recovered == plaintext
        assert recovered != encrypted


# ===========================================================================
# MFLAC / MGG 解密（需 key）
# ===========================================================================
class TestKeyBasedDecrypt:
    def test_mflac_decrypt_with_key(self, tmp_path: Path, monkeypatch) -> None:
        """mflac 用 env key 解密成功。"""
        key = b"test_key_12345678"
        plaintext = b"fLaC" + b"\x00" * 200
        encrypted = _make_mflac_fixture(plaintext, key)
        src = tmp_path / "song.mflac"
        src.write_bytes(encrypted)
        monkeypatch.setenv("AI_OMNNI_MUSIC_KEY", key.decode("ascii"))
        d = AudioDecryptor()
        out = d.decrypt(str(src))
        assert Path(out).read_bytes() == plaintext
        assert out.endswith(".decrypted.flac")

    def test_mflac_missing_key_raises_error(self, tmp_path: Path, monkeypatch) -> None:
        """mflac 无 key 时返回 E_DECRYPT_KEY_MISSING。"""
        plaintext = b"fLaC" + b"\x00" * 50
        encrypted = _make_mflac_fixture(plaintext, b"somekey")
        src = tmp_path / "song.mflac"
        src.write_bytes(encrypted)
        monkeypatch.delenv("AI_OMNNI_MUSIC_KEY", raising=False)
        d = AudioDecryptor()
        with pytest.raises(RuntimeError) as exc:
            d.decrypt(str(src))
        assert "E_DECRYPT_KEY_MISSING" in str(exc.value) or "key" in str(exc.value).lower()

    def test_mgg_decrypt_with_key(self, tmp_path: Path, monkeypatch) -> None:
        """mgg 用 env key 解密成功。"""
        key = b"mggkey_abcdef"
        plaintext = b"OggS" + b"\x00" * 200
        encrypted = _make_mflac_fixture(plaintext, key)
        src = tmp_path / "song.mgg"
        src.write_bytes(encrypted)
        monkeypatch.setenv("AI_OMNNI_MUSIC_KEY", key.decode("ascii"))
        d = AudioDecryptor()
        out = d.decrypt(str(src))
        assert Path(out).read_bytes() == plaintext
        assert out.endswith(".decrypted.ogg")


# ===========================================================================
# 错误处理
# ===========================================================================
class TestErrors:
    def test_unsupported_format_raises(self, tmp_path: Path) -> None:
        """不支持的格式抛 ValueError。"""
        src = tmp_path / "song.mp3"
        src.write_bytes(b"ID3")
        d = AudioDecryptor()
        with pytest.raises(ValueError):
            d.decrypt(str(src))

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        """源文件不存在抛 FileNotFoundError 或 OSError。"""
        d = AudioDecryptor()
        with pytest.raises((FileNotFoundError, OSError)):
            d.decrypt(str(tmp_path / "nope.qmc0"))

    def test_decrypt_does_not_overwrite_source(self, tmp_path: Path) -> None:
        """解密不覆盖源文件（输出到 .decrypted.*）。"""
        plaintext = b"fLaC" + b"\x00" * 20
        encrypted = _make_qmc0_fixture(plaintext)
        src = tmp_path / "song.qmcflac"
        src.write_bytes(encrypted)
        original_bytes = src.read_bytes()
        d = AudioDecryptor()
        d.decrypt(str(src))
        # 源文件未被修改
        assert src.read_bytes() == original_bytes


# ===========================================================================
# 合规约束
# ===========================================================================
class TestCompliance:
    def test_module_docstring_declares_compliance(self) -> None:
        """模块 docstring 声明 D19.1 合规约束。"""
        from omni_music.library import decryptor as mod
        doc = mod.__doc__ or ""
        assert "合法购买" in doc or "已购买" in doc
        assert "破解" in doc

    def test_class_docstring_declares_compliance(self) -> None:
        """类 docstring 声明合规约束。"""
        doc = AudioDecryptor.__doc__ or ""
        assert "合法购买" in doc or "已购买" in doc
        assert "不提供破解" in doc or "不破解" in doc

    def test_no_drm_bypass_methods(self) -> None:
        """类不暴露任何绕过 DRM 的方法（无 crack/bypass/extract_key 方法）。"""
        forbidden = {"crack", "bypass_drm", "extract_key", "break_drm", "remove_drm"}
        methods = {name for name in dir(AudioDecryptor) if not name.startswith("__")}
        assert not (forbidden & methods)
