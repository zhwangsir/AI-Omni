"""omni_music CookieStore + FakeCookieStore 测试（M17.3）。

覆盖：
- FakeCookieStore 内存版 save/load/clear
- CookieStore AES-256-GCM 加密落盘到 ~/.ai-omni/cookies/<source>.enc
- 密钥派生：环境变量 AI_OMNI_COOKIE_KEY 优先，回退机器特征
- 明文 cookie 绝不落盘（密文文件不含原始 cookie 字符串）
- 密钥不硬编码到源码
- cryptography 不可用时降级 E_BACKEND_UNAVAILABLE
- 多 source 互不干扰
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from omni_music.auth.cookie_store import CookieStore, FakeCookieStore

# 检测 cryptography 是否可用；不可用时跳过真实加密测试
# （CLAUDE.md §三：重型依赖可缺省，测试零依赖）
try:
    import cryptography  # noqa: F401

    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

_NEED_CRYPTO = pytest.mark.skipif(
    not HAS_CRYPTOGRAPHY, reason="cryptography 未安装，跳过真实加密测试"
)


class TestFakeCookieStore:
    def test_fake_store_in_memory(self) -> None:
        """FakeCookieStore 内存版 save 后 load 返回相同 dict。"""
        store = FakeCookieStore()
        cookies = {"MUSIC_U": "abc123", "os": "pc"}
        store.save("netease", cookies)
        loaded = store.load("netease")
        assert loaded == cookies

    def test_fake_store_unknown_source_returns_none(self) -> None:
        """未保存过的 source load 返回 None。"""
        store = FakeCookieStore()
        assert store.load("qqmusic") is None

    def test_fake_store_clear(self) -> None:
        """clear 后 load 返回 None。"""
        store = FakeCookieStore()
        store.save("netease", {"k": "v"})
        store.clear("netease")
        assert store.load("netease") is None

    def test_fake_store_clear_unknown_source_noop(self) -> None:
        """clear 不存在的 source 不报错（幂等）。"""
        store = FakeCookieStore()
        store.clear("ghost")  # 不应抛异常

    def test_fake_store_sources_isolated(self) -> None:
        """不同 source 互不干扰。"""
        store = FakeCookieStore()
        store.save("netease", {"a": "1"})
        store.save("qqmusic", {"b": "2"})
        assert store.load("netease") == {"a": "1"}
        assert store.load("qqmusic") == {"b": "2"}


@_NEED_CRYPTO
class TestCookieStoreEncryption:
    """CookieStore 真实加密路径，使用临时目录隔离文件落盘。

    需要 ``cryptography`` 可用；CI 不装该依赖时整个类跳过
    （符合 CLAUDE.md §三：重型依赖可缺省，测试零依赖）。
    """

    def _make_store(self, tmp_dir: Path, key: str = "test-key-12345") -> CookieStore:
        """构造一个使用临时目录与显式密钥的 CookieStore。"""
        return CookieStore(base_dir=tmp_dir, passphrase=key)

    def test_save_creates_enc_file(self, tmp_path: Path) -> None:
        """save 后在 base_dir/<source>.enc 生成文件。"""
        store = self._make_store(tmp_path)
        store.save("netease", {"MUSIC_U": "secret_token"})
        enc_file = tmp_path / "netease.enc"
        assert enc_file.is_file()

    def test_load_roundtrip(self, tmp_path: Path) -> None:
        """save → load 往返保持等价。"""
        store = self._make_store(tmp_path)
        original = {"MUSIC_U": "secret_token", "os": "pc", "__csrf": "abc"}
        store.save("netease", original)
        loaded = store.load("netease")
        assert loaded == original

    def test_load_unknown_source_returns_none(self, tmp_path: Path) -> None:
        """未保存的 source load 返回 None。"""
        store = self._make_store(tmp_path)
        assert store.load("ghost") is None

    def test_clear_removes_file(self, tmp_path: Path) -> None:
        """clear 删除 .enc 文件。"""
        store = self._make_store(tmp_path)
        store.save("netease", {"k": "v"})
        enc_file = tmp_path / "netease.enc"
        assert enc_file.is_file()
        store.clear("netease")
        assert not enc_file.exists()
        assert store.load("netease") is None

    def test_clear_unknown_source_noop(self, tmp_path: Path) -> None:
        """clear 不存在的 source 不报错。"""
        store = self._make_store(tmp_path)
        store.clear("ghost")

    def test_plaintext_not_in_file(self, tmp_path: Path) -> None:
        """密文文件绝不含明文 cookie 值。"""
        store = self._make_store(tmp_path)
        secret_value = "SUPER_SECRET_TOKEN_VALUE_12345"
        store.save("netease", {"MUSIC_U": secret_value})
        enc_bytes = (tmp_path / "netease.enc").read_bytes()
        # 明文 token 不应出现在密文文件中
        assert secret_value.encode() not in enc_bytes

    def test_multiple_sources_isolated(self, tmp_path: Path) -> None:
        """多个 source 各自落盘独立 .enc 文件。"""
        store = self._make_store(tmp_path)
        store.save("netease", {"a": "1"})
        store.save("qqmusic", {"b": "2"})
        assert (tmp_path / "netease.enc").is_file()
        assert (tmp_path / "qqmusic.enc").is_file()
        assert store.load("netease") == {"a": "1"}
        assert store.load("qqmusic") == {"b": "2"}

    def test_different_passphrase_cannot_decrypt(self, tmp_path: Path) -> None:
        """不同 passphrase 无法解密对方密文（返回 None 而非崩溃）。"""
        store1 = self._make_store(tmp_path, key="key-A")
        store1.save("netease", {"MUSIC_U": "token"})
        # 用不同 passphrase 构造新 store，应无法解密
        store2 = self._make_store(tmp_path, key="key-B")
        loaded = store2.load("netease")
        assert loaded is None

    def test_env_var_passphrase_preferred(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """环境变量 AI_OMNI_COOKIE_KEY 优先于机器特征派生。"""
        monkeypatch.setenv("AI_OMNI_COOKIE_KEY", "env-secret-key")
        store = CookieStore(base_dir=tmp_path)
        store.save("netease", {"k": "v"})
        # 用同 env 重新构造应能解密
        store2 = CookieStore(base_dir=tmp_path)
        assert store2.load("netease") == {"k": "v"}


class TestCookieStoreNoHardcodedKey:
    """源码静态检查：确保没有硬编码密钥（不依赖 cryptography）。"""

    def test_no_hardcoded_key_in_source(self) -> None:
        """源码中不应出现硬编码的密钥字面量（通过检查模块源文本）。"""
        import omni_music.auth.cookie_store as mod

        src = Path(mod.__file__).read_text(encoding="utf-8")
        # 不应出现明显的硬编码密钥字面量
        bad_patterns = [
            '"super-secret-key"',
            "'super-secret-key'",
            '"hardcoded-key"',
            "'hardcoded-key'",
            "b'0123456789abcdef'",
        ]
        for pat in bad_patterns:
            assert pat not in src, f"源码中出现可疑硬编码密钥: {pat}"


class TestCookieStoreBackendUnavailable:
    """cryptography 不可用时降级路径。"""

    def test_save_without_cryptography_returns_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """cryptography 不可用时 save 返回错误标识（不抛异常拖垮调用方）。"""
        # 通过 sys.modules 注入 import 失败
        import builtins

        real_import = builtins.__import__

        def _fake_import(name: str, *args, **kwargs):
            if name.startswith("cryptography"):
                raise ImportError(f"mocked: no {name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)
        # 清除已缓存的 cryptography 模块
        import sys

        for mod_name in list(sys.modules):
            if mod_name.startswith("cryptography"):
                del sys.modules[mod_name]

        store = CookieStore(base_dir=tmp_path, passphrase="test-key")
        result = store.save("netease", {"k": "v"})
        # save 应返回错误 dict（不抛异常）
        assert isinstance(result, dict)
        assert result.get("ok") is False
        assert "code" in result.get("error", {})
        assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"

    def test_load_without_cryptography_returns_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """cryptography 不可用时 load 返回 None。"""
        import builtins
        import sys

        real_import = builtins.__import__

        def _fake_import(name: str, *args, **kwargs):
            if name.startswith("cryptography"):
                raise ImportError(f"mocked: no {name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)
        for mod_name in list(sys.modules):
            if mod_name.startswith("cryptography"):
                del sys.modules[mod_name]

        store = CookieStore(base_dir=tmp_path, passphrase="test-key")
        loaded = store.load("netease")
        assert loaded is None
