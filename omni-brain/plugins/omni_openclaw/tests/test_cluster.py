"""omni_openclaw 集群巡检与设备管家测试。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

from omni_openclaw.cluster import ClusterChecker
from omni_openclaw.config import OpenClawConfig


class FakeHttpBackend:
    """可注入的 fake HTTP backend，按完整 URL 返回响应。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: dict[str, tuple[int, Any, float]] = {}

    def add_response(
        self,
        url: str,
        status: int,
        body: Any,
        delay: float = 0.0,
    ) -> None:
        """注册对某个 URL 的响应；delay 模拟耗时（秒）。"""
        self.responses[url] = (status, body, delay)

    async def request(self, method: str, url: str, **kwargs: Any) -> tuple[int, Any]:
        """模拟 HTTP 请求。"""
        self.calls.append({"method": method.upper(), "url": url, "kwargs": kwargs})
        status, body, delay = self.responses.get(url, (404, {"error": "not found"}, 0.0))
        if delay:
            await asyncio.sleep(delay)
        return status, body


@pytest.fixture
def backend() -> FakeHttpBackend:
    return FakeHttpBackend()


@pytest.fixture
def checker(backend: FakeHttpBackend) -> ClusterChecker:
    return ClusterChecker(config=OpenClawConfig(), backend=backend)


_ENDPOINTS = {
    "gateway": "http://192.168.71.86:18789/health",
    "llm_l1": "http://192.168.71.127:8000/v1/models",
    "llm_l4": "http://192.168.71.82:8000/v1/models",
    "comfyui": "http://192.168.71.127:8188/system_stats",
    "tts": "http://192.168.71.127:9200/health",
    "embedding": "http://192.168.71.127:9301/v1/models",
}


def _register_all_ok(backend: FakeHttpBackend) -> None:
    """注册所有端点返回 200。"""
    for url in _ENDPOINTS.values():
        backend.add_response(url, 200, {"status": "ok"})


class TestHealthCheck:
    """集群健康检查测试。"""

    @pytest.mark.asyncio
    async def test_all_healthy(self, checker: ClusterChecker, backend: FakeHttpBackend) -> None:
        """所有端点正常时应返回集群健康。"""
        _register_all_ok(backend)
        result = await checker.health_check()

        assert result["ok"] is True
        assert result["summary"] == "集群健康"
        report = result["report"]
        assert report["p0"] == []
        assert report["p1"] == []
        assert report["p2"] == []
        assert len(report["details"]) == len(_ENDPOINTS)
        assert len(backend.calls) == len(_ENDPOINTS)

    @pytest.mark.asyncio
    async def test_p0_gateway_failure(self, checker: ClusterChecker, backend: FakeHttpBackend) -> None:
        """网关不可用时应被标记为 P0。"""
        _register_all_ok(backend)
        backend.add_response(_ENDPOINTS["gateway"], 503, {"status": "down"})
        result = await checker.health_check()

        assert result["ok"] is True
        assert "P0" in result["summary"]
        p0_names = {r["name"] for r in result["report"]["p0"]}
        assert "gateway" in p0_names
        assert "llm_l1" not in p0_names

    @pytest.mark.asyncio
    async def test_p0_l1_exception(self, checker: ClusterChecker, backend: FakeHttpBackend) -> None:
        """L1 模型抛异常时应被标记为 P0。"""
        _register_all_ok(backend)

        async def raise_error(*args: Any, **kwargs: Any) -> Any:
            raise ConnectionError("refused")

        backend.request = raise_error  # type: ignore[assignment]
        result = await checker.health_check()

        assert "P0" in result["summary"]
        p0_names = {r["name"] for r in result["report"]["p0"]}
        assert "llm_l1" in p0_names

    @pytest.mark.asyncio
    async def test_p1_secondary_failures(self, checker: ClusterChecker, backend: FakeHttpBackend) -> None:
        """L4、ComfyUI、TTS、Embedding 不可用时应被标记为 P1。"""
        backend.add_response(_ENDPOINTS["gateway"], 200, {"status": "ok"})
        backend.add_response(_ENDPOINTS["llm_l1"], 200, {"status": "ok"})
        for name in ("llm_l4", "comfyui", "tts", "embedding"):
            backend.add_response(_ENDPOINTS[name], 503, {"status": "down"})

        result = await checker.health_check()
        assert "P1" in result["summary"]
        p1_names = {r["name"] for r in result["report"]["p1"]}
        assert p1_names == {"llm_l4", "comfyui", "tts", "embedding"}
        assert result["report"]["p0"] == []

    @pytest.mark.asyncio
    async def test_p2_non_200_also_in_p1(self, checker: ClusterChecker, backend: FakeHttpBackend) -> None:
        """P1 端点返回非 200 时同时出现在 P1 与 P2 列表。"""
        backend.add_response(_ENDPOINTS["gateway"], 200, {"status": "ok"})
        backend.add_response(_ENDPOINTS["llm_l1"], 200, {"status": "ok"})
        backend.add_response(_ENDPOINTS["llm_l4"], 500, {"status": "error"})
        for name in ("comfyui", "tts", "embedding"):
            backend.add_response(_ENDPOINTS[name], 200, {"status": "ok"})

        result = await checker.health_check()
        assert "P1" in result["summary"]
        p1_names = {r["name"] for r in result["report"]["p1"]}
        p2_names = {r["name"] for r in result["report"]["p2"]}
        assert "llm_l4" in p1_names
        assert "llm_l4" in p2_names

    @pytest.mark.asyncio
    async def test_p2_slow_response(
        self,
        checker: ClusterChecker,
        backend: FakeHttpBackend,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """响应慢（>2s）的端点应被标记为 P2。"""
        _register_all_ok(backend)

        class MockClock:
            def __init__(self) -> None:
                self._t = 0.0

            def __call__(self) -> float:
                self._t += 3.0
                return self._t

        monkeypatch.setattr(
            "omni_openclaw.cluster.time.perf_counter",
            MockClock(),
        )
        result = await checker.health_check()

        assert "降级" in result["summary"]
        assert len(result["report"]["p2"]) == len(_ENDPOINTS)
        assert all(r["elapsed_ms"] > 2000 for r in result["report"]["p2"])

    @pytest.mark.asyncio
    async def test_ssh_probe_injected(self, backend: FakeHttpBackend) -> None:
        """注入 fake SSH runner 时，健康报告应包含 SSH 结果。"""
        _register_all_ok(backend)

        async def fake_ssh(host: str) -> tuple[bool, str]:
            if host == "openclaw01":
                return True, "uptime 1 day"
            return False, "connection refused"

        checker = ClusterChecker(
            config=OpenClawConfig(),
            backend=backend,
            ssh_runner=fake_ssh,
            ssh_hosts=["openclaw01", "openclaw02"],
        )
        result = await checker.health_check()

        ssh = result["report"]["ssh"]
        assert len(ssh) == 2
        by_host = {r["host"]: r for r in ssh}
        assert by_host["openclaw01"]["ok"] is True
        assert by_host["openclaw02"]["ok"] is False

    @pytest.mark.asyncio
    async def test_ssh_default_asyncssh(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """安装 asyncssh 时默认 runner 应能执行 SSH 探测。"""

        class FakeResult:
            stdout = "uptime 1 day"

        class FakeConn:
            async def run(self, command: str, check: bool = False) -> FakeResult:
                return FakeResult()

        class FakeAsyncSSH:
            @staticmethod
            def connect(host: str) -> Any:
                class _CM:
                    async def __aenter__(self) -> FakeConn:
                        return FakeConn()

                    async def __aexit__(self, *args: Any) -> None:
                        return None

                return _CM()

        monkeypatch.setitem(sys.modules, "asyncssh", FakeAsyncSSH())
        checker = ClusterChecker(ssh_hosts=["openclaw01"])
        result = await checker.health_check()

        ssh = result["report"]["ssh"]
        assert len(ssh) == 1
        assert ssh[0]["ok"] is True
        assert "uptime" in ssh[0]["detail"]

    def test_ssh_skipped_when_asyncssh_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未安装 asyncssh 且未注入 runner 时，SSH 探测应被跳过。"""
        monkeypatch.setitem(sys.modules, "asyncssh", None)
        checker = ClusterChecker()
        assert checker._ssh_runner is None


class TestDeviceLookup:
    """设备文档查询测试。"""

    def test_file_not_exists(self) -> None:
        """设备说明文件不存在时应返回友好提示。"""
        checker = ClusterChecker(device_doc_path=Path("/nonexistent/设备说明.md"))
        result = checker.device_lookup("spark")

        assert result["ok"] is True
        assert result["found"] is False
        assert "不存在" in result["summary"]
        assert result["matches"] == []

    def test_query_matches(self, tmp_path: Path) -> None:
        """查询关键字应返回匹配行。"""
        doc = tmp_path / "设备说明.md"
        doc.write_text(
            "# 计算节点\n\n- spark01: Ray head，192.168.71.82\n- spark02: Ray worker\n",
            encoding="utf-8",
        )
        checker = ClusterChecker(device_doc_path=doc)
        result = checker.device_lookup("spark01")

        assert result["ok"] is True
        assert result["found"] is True
        assert len(result["matches"]) == 1
        assert result["matches"][0]["content"].startswith("- spark01")
        assert result["matches"][0]["section"] == "计算节点"

    def test_query_no_match(self, tmp_path: Path) -> None:
        """无匹配时应返回空列表。"""
        doc = tmp_path / "设备说明.md"
        doc.write_text("# 网络\n\n- router01\n", encoding="utf-8")
        checker = ClusterChecker(device_doc_path=doc)
        result = checker.device_lookup("spark")

        assert result["ok"] is True
        assert result["found"] is False
        assert "未找到" in result["summary"]

    def test_empty_query_returns_hint(self, tmp_path: Path) -> None:
        """空查询应提示用户输入关键字。"""
        doc = tmp_path / "设备说明.md"
        doc.write_text("# 节点\n\n- n1\n- n2\n", encoding="utf-8")
        checker = ClusterChecker(device_doc_path=doc)
        result = checker.device_lookup("")

        assert result["ok"] is True
        assert "请提供查询关键字" in result["summary"]
        assert len(result["matches"]) == len(doc.read_text(encoding="utf-8").splitlines())

    def test_read_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """文件读取异常时应返回错误结构。"""
        doc = tmp_path / "设备说明.md"
        doc.write_text("content", encoding="utf-8")

        def raise_oserror(*args: Any, **kwargs: Any) -> str:
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "read_text", raise_oserror)
        checker = ClusterChecker(device_doc_path=doc)
        result = checker.device_lookup("x")

        assert result["ok"] is False
        assert result["error"]["code"] == "E_DEVICE_DOC_READ"


class TestLifecycle:
    """生命周期测试。"""

    @pytest.mark.asyncio
    async def test_close_owns_backend(self, backend: FakeHttpBackend) -> None:
        """close 应释放由 ClusterChecker 创建的 backend。"""
        closed = []

        async def fake_close() -> None:
            closed.append(True)

        backend.close = fake_close  # type: ignore[attr-defined]
        checker = ClusterChecker(backend=backend)
        assert checker._owns_backend is False
        await checker.close()
        assert closed == []

    @pytest.mark.asyncio
    async def test_close_owned_backend(self) -> None:
        """注入的 backend 在 owns=True 时不会被 close。"""
        checker = ClusterChecker()
        assert checker._owns_backend is True
        await checker.close()
