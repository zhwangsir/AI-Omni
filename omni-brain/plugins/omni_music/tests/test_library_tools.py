"""omni_music library/playlist/decrypt 工具测试（M19.7）。

TDD 测试先行：覆盖 8 个新工具：
- ``music_library_scan``     ：扫描本地音乐库写入 SQLite
- ``music_library_search``   ：FTS5 全文搜索
- ``music_library_status``   ：库状态
- ``music_playlist_create``  ：创建歌单
- ``music_playlist_add``     ：歌单添加歌曲
- ``music_playlist_remove``  ：歌单移除歌曲
- ``music_playlist_list``    ：列歌单 / 歌单内歌曲
- ``music_decrypt_file``     ：解密加密音频（confirm=true 安全门）

env ``AI_OMNI_MUSIC_DB`` 指向 tmp_path，避免污染用户家目录。
fake 模式用预置 fake file_scanner / metadata_reader，不碰真实文件。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from omni_music import tools
from omni_music.library.db import MusicLibraryDB


def _parse(result: str) -> dict:
    assert isinstance(result, str)
    return json.loads(result)


@pytest.fixture(autouse=True)
def fresh_library_runtime(tmp_path: Path, monkeypatch) -> Any:
    """每个测试前重置 library runtime + DB 指向 tmp_path。"""
    db_path = tmp_path / "library.db"
    monkeypatch.setenv("AI_OMNI_MUSIC_DB", str(db_path))
    # 重置主 runtime（避免 music 工具干扰）
    tools._reset_runtime()
    # 重置 library runtime
    tools._reset_library_runtime()
    yield


# ===========================================================================
# music_library_scan
# ===========================================================================
class TestLibraryScan:
    def test_scan_fake_returns_counts(self) -> None:
        """fake 模式扫描返回统计 dict。"""
        data = _parse(tools.music_library_scan(fake=True))
        assert data["ok"] is True
        result = data["data"]
        assert "scanned" in result
        assert "added" in result
        assert "updated" in result
        assert "skipped" in result
        assert "errors" in result
        # fake 模式预置 2 首歌
        assert result["scanned"] >= 1

    def test_scan_fake_writes_to_db(self) -> None:
        """fake 扫描后 DB 有歌曲。"""
        tools.music_library_scan(fake=True)
        db = tools._get_library_db()
        assert db.get_status()["song_count"] > 0

    def test_scan_custom_root_dir(self, tmp_path: Path) -> None:
        """指定 root_dir 扫描（fake 模式忽略真实目录，用预置 fake）。"""
        data = _parse(tools.music_library_scan(root_dir=str(tmp_path), fake=True))
        assert data["ok"] is True

    def test_scan_rescan_skips_unchanged(self) -> None:
        """重复扫描 skipped 计数 > 0。"""
        tools.music_library_scan(fake=True)
        data = _parse(tools.music_library_scan(fake=True))
        assert data["data"]["skipped"] >= 1


# ===========================================================================
# music_library_search
# ===========================================================================
class TestLibrarySearch:
    def test_search_returns_results(self) -> None:
        """扫描后搜索返回匹配结果。"""
        tools.music_library_scan(fake=True)
        # fake 预置歌曲含"晴天"
        data = _parse(tools.music_library_search(query="晴天", fake=True))
        assert data["ok"] is True
        results = data["data"]["songs"]
        assert len(results) >= 1
        assert any("晴天" in s["title"] for s in results)

    def test_search_no_match_returns_empty(self) -> None:
        """无匹配返回空列表。"""
        tools.music_library_scan(fake=True)
        data = _parse(tools.music_library_search(query="不存在的歌XXX", fake=True))
        assert data["ok"] is True
        assert data["data"]["songs"] == []

    def test_search_limit(self) -> None:
        """limit 截断。"""
        tools.music_library_scan(fake=True)
        data = _parse(tools.music_library_search(query="", limit=1, fake=True))
        assert len(data["data"]["songs"]) <= 1

    def test_search_without_scan_returns_empty(self) -> None:
        """未扫描直接搜索返回空。"""
        data = _parse(tools.music_library_search(query="晴天", fake=True))
        assert data["ok"] is True
        assert data["data"]["songs"] == []


# ===========================================================================
# music_library_status
# ===========================================================================
class TestLibraryStatus:
    def test_status_empty_before_scan(self) -> None:
        """未扫描时 song_count=0。"""
        data = _parse(tools.music_library_status(fake=True))
        assert data["ok"] is True
        status = data["data"]
        assert status["song_count"] == 0
        assert "playlist_count" in status
        assert "last_scan_at" in status
        assert "watching" in status

    def test_status_after_scan(self) -> None:
        """扫描后 song_count > 0。"""
        tools.music_library_scan(fake=True)
        data = _parse(tools.music_library_status(fake=True))
        assert data["data"]["song_count"] > 0
        assert data["data"]["last_scan_at"] is not None


# ===========================================================================
# music_playlist_create
# ===========================================================================
class TestPlaylistCreate:
    def test_create_returns_playlist_id(self) -> None:
        data = _parse(tools.music_playlist_create(name="我的歌单", fake=True))
        assert data["ok"] is True
        assert "playlist_id" in data["data"]
        assert isinstance(data["data"]["playlist_id"], int)

    def test_create_empty_name_returns_error(self) -> None:
        """空歌单名返回 E_INVALID_ARGS。"""
        data = _parse(tools.music_playlist_create(name="", fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_INVALID_ARGS"


# ===========================================================================
# music_playlist_add / remove / list
# ===========================================================================
class TestPlaylistOps:
    def test_add_song_to_playlist(self) -> None:
        """添加歌曲到歌单。"""
        tools.music_library_scan(fake=True)
        songs = tools._get_library_db().get_all_songs()
        song_id = songs[0]["id"]
        pid = _parse(tools.music_playlist_create(name="my", fake=True))["data"]["playlist_id"]
        data = _parse(
            tools.music_playlist_add(playlist_id=pid, song_id=song_id, fake=True)
        )
        assert data["ok"] is True
        # 列歌单内歌曲
        listed = _parse(tools.music_playlist_list(playlist_id=pid, fake=True))
        assert listed["ok"] is True
        assert len(listed["data"]["songs"]) == 1

    def test_add_nonexistent_song_returns_error(self) -> None:
        """添加不存在歌曲返回 E_INVALID_ARGS。"""
        pid = _parse(tools.music_playlist_create(name="my", fake=True))["data"]["playlist_id"]
        data = _parse(
            tools.music_playlist_add(playlist_id=pid, song_id="nonexistent", fake=True)
        )
        assert data["ok"] is False

    def test_remove_song_from_playlist(self) -> None:
        """从歌单移除歌曲。"""
        tools.music_library_scan(fake=True)
        songs = tools._get_library_db().get_all_songs()
        song_id = songs[0]["id"]
        pid = _parse(tools.music_playlist_create(name="my", fake=True))["data"]["playlist_id"]
        tools.music_playlist_add(playlist_id=pid, song_id=song_id, fake=True)
        data = _parse(
            tools.music_playlist_remove(playlist_id=pid, song_id=song_id, fake=True)
        )
        assert data["ok"] is True
        listed = _parse(tools.music_playlist_list(playlist_id=pid, fake=True))
        assert len(listed["data"]["songs"]) == 0

    def test_list_playlists(self) -> None:
        """不传 playlist_id 时列出全部歌单。"""
        tools.music_playlist_create(name="a", fake=True)
        tools.music_playlist_create(name="b", fake=True)
        data = _parse(tools.music_playlist_list(fake=True))
        assert data["ok"] is True
        assert len(data["data"]["playlists"]) == 2

    def test_list_nonexistent_playlist_returns_empty(self) -> None:
        """列不存在的歌单返回空 songs。"""
        data = _parse(tools.music_playlist_list(playlist_id=99999, fake=True))
        assert data["ok"] is True
        assert data["data"]["songs"] == []


# ===========================================================================
# music_decrypt_file（confirm=true 安全门）
# ===========================================================================
class TestDecryptFile:
    def test_decrypt_without_confirm_returns_error(self) -> None:
        """未确认返回 E_CONFIRM_REQUIRED（安全门）。"""
        data = _parse(tools.music_decrypt_file(path="/x.qmc0", confirm=False, fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_CONFIRM_REQUIRED"

    def test_decrypt_unsupported_format_returns_error(self, tmp_path: Path) -> None:
        """不支持的格式返回 E_UNSUPPORTED_FORMAT。"""
        src = tmp_path / "song.mp3"
        src.write_bytes(b"ID3")
        data = _parse(tools.music_decrypt_file(path=str(src), confirm=True, fake=True))
        assert data["ok"] is False
        assert data["error"]["code"] == "E_UNSUPPORTED_FORMAT"

    def test_decrypt_qmc0_success(self, tmp_path: Path) -> None:
        """qmc0 解密成功返回输出路径。"""
        from omni_music.library.decryptor import QMC_SEED_TABLE

        plaintext = b"fLaC" + b"\x00" * 50
        encrypted = bytes(
            b ^ QMC_SEED_TABLE[i % len(QMC_SEED_TABLE)] for i, b in enumerate(plaintext)
        )
        src = tmp_path / "song.qmc0"
        src.write_bytes(encrypted)
        data = _parse(tools.music_decrypt_file(path=str(src), confirm=True, fake=True))
        assert data["ok"] is True
        out_path = data["data"]["output_path"]
        assert os.path.exists(out_path)
        assert Path(out_path).read_bytes() == plaintext

    def test_decrypt_nonexistent_file_returns_error(self) -> None:
        """源文件不存在返回 E_FILE_NOT_FOUND。"""
        data = _parse(
            tools.music_decrypt_file(path="/nonexistent.qmc0", confirm=True, fake=True)
        )
        assert data["ok"] is False
        assert data["error"]["code"] in ("E_FILE_NOT_FOUND", "E_DECRYPT_FAILED")

    def test_decrypt_compliance_notice_in_success(self, tmp_path: Path) -> None:
        """解密成功返回含合规声明字段。"""
        from omni_music.library.decryptor import QMC_SEED_TABLE

        plaintext = b"fLaC" + b"\x00" * 20
        encrypted = bytes(
            b ^ QMC_SEED_TABLE[i % len(QMC_SEED_TABLE)] for i, b in enumerate(plaintext)
        )
        src = tmp_path / "song.qmcflac"
        src.write_bytes(encrypted)
        data = _parse(tools.music_decrypt_file(path=str(src), confirm=True, fake=True))
        assert data["ok"] is True
        # 成功响应含合规声明
        assert data["data"].get("compliance") or data["data"].get("notice")


# ===========================================================================
# 工具注册
# ===========================================================================
class TestRegistration:
    def test_tools_list_has_eight_new_tools(self) -> None:
        """TOOLS 注册表含 8 个新工具。"""
        names = {t["name"] for t in tools.TOOLS}
        new_tools = {
            "music_library_scan",
            "music_library_search",
            "music_library_status",
            "music_playlist_create",
            "music_playlist_add",
            "music_playlist_remove",
            "music_playlist_list",
            "music_decrypt_file",
        }
        assert new_tools.issubset(names)

    def test_total_tools_count_is_twenty(self) -> None:
        """12 旧 + 8 新 = 20 个工具。"""
        assert len(tools.TOOLS) == 20

    def test_decrypt_tool_schema_has_confirm_param(self) -> None:
        """music_decrypt_file schema 含 confirm 参数。"""
        tool = next(t for t in tools.TOOLS if t["name"] == "music_decrypt_file")
        props = tool["schema"]["parameters"]["properties"]
        assert "confirm" in props
        assert "path" in props

    def test_register_registers_twenty_tools(self) -> None:
        """register(ctx) 注册 20 个工具。"""

        class _Ctx:
            def __init__(self):
                self.tools = []

            def register_tool(self, **kw):
                self.tools.append(kw)

        ctx = _Ctx()
        tools.register(ctx)
        assert len(ctx.tools) == 20
