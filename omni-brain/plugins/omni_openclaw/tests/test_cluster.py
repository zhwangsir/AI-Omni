"""omni_openclaw 集群巡检与设备管家测试。"""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from omni_openclaw.cluster import (
    ClusterChecker,
    _HttpxBackend,
    _make_default_ssh_runner,
)
from omni_openclaw.config import OpenClawConfig


class _FakeHttpResponse:
    """模拟 httpx Response 的最小接口。"""

    def __init__(
        self,
        status_code: int = 200,
        json_data: Any = None,
        text: str = "",
        json_raises: bool = False,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self._json_data = json_data
        self._json_raises = json_raises

    def json(self) -> Any:
        """返回预置 JSON 数据；``json_raises`` 时模拟解析失败。"""
        if self._json_raises:
            raise ValueError("invalid json")
        return self._json_data


def _install_fake_httpx(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """向 sys.modules 注入 fake httpx，返回已创建的 AsyncClient 实例列表。"""
    created: list[Any] = []

    class FakeAsyncClient:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.requests: list[dict[str, Any]] = []
            self.responses: list[_FakeHttpResponse] = []
            self.closed = False
            created.append(self)

        async def request(
            self, method: str, url: str, **kwargs: Any
        ) -> _FakeHttpResponse:
            self.requests.append({"method": method, "url": url, "kwargs": kwargs})
            return self.responses.pop(0)

        async def aclose(self) -> None:
            self.closed = True

    monkeypatch.setitem(
        sys.modules, "httpx", types.SimpleNamespace(AsyncClient=FakeAsyncClient)
    )
    return created


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
    "embedding": "http://192.168.71.127:9302/health",
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
    async def test_ssh_default_asyncssh(
        self,
        monkeypatch: pytest.MonkeyPatch,
        backend: FakeHttpBackend,
    ) -> None:
        """安装 asyncssh 时默认 runner 应能执行 SSH 探测。

        M32.23：必须注入 fake HTTP backend——此前未注入导致 health_check
        真实探测集群 6 个端点（违反测试零依赖纪律），且 httpx client
        未关闭触发 ResourceWarning。
        """

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

        _register_all_ok(backend)
        monkeypatch.setitem(sys.modules, "asyncssh", FakeAsyncSSH())
        checker = ClusterChecker(ssh_hosts=["openclaw01"], backend=backend)
        result = await checker.health_check()

        ssh = result["report"]["ssh"]
        assert len(ssh) == 1
        assert ssh[0]["ok"] is True
        assert "uptime" in ssh[0]["detail"]
        # HTTP 探测必须走 fake backend，而非真实集群
        assert len(backend.calls) == len(_ENDPOINTS)

    def test_ssh_skipped_when_asyncssh_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未安装 asyncssh 且未注入 runner 时，SSH 探测应被跳过。"""
        monkeypatch.setitem(sys.modules, "asyncssh", None)
        checker = ClusterChecker()
        assert checker._ssh_runner is None


class TestDeviceLookup:
    """设备文档查询测试。"""

    def test_default_doc_path_is_inside_project(self) -> None:
        """M32.21：默认设备说明文档路径必须位于 AI-Omni 项目根目录，禁止跨仓库读取。"""
        from omni_openclaw.cluster import DEVICE_DOC_PATH

        project_root = Path(__file__).resolve().parents[4]
        assert DEVICE_DOC_PATH.resolve().is_relative_to(project_root)
        assert "AIHub" not in str(DEVICE_DOC_PATH)

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


# ===========================================================================
# M32.23：默认 backend 惰性创建（防 httpx client 泄漏）
# ===========================================================================
class TestLazyBackend:
    """默认 HTTP backend 必须在首次真实使用时才创建。

    回归背景：此前 ``ClusterChecker()`` 构造即创建 ``httpx.AsyncClient``，
    纯 ``device_lookup``（文件查询）场景也泄漏一个未关闭的 client，
    GC 时触发 ``ResourceWarning: unclosed transport``。
    """

    def test_default_construction_creates_no_backend(self) -> None:
        """未注入 backend 时，构造后 backend 必须为 None（尚未创建）。"""
        checker = ClusterChecker()
        assert checker._backend is None
        assert checker._owns_backend is True

    def test_device_lookup_does_not_create_backend(self, tmp_path: Path) -> None:
        """纯文件查询路径不得触发 httpx client 创建。"""
        doc = tmp_path / "设备说明.md"
        doc.write_text("# 节点\n\n- spark01\n", encoding="utf-8")
        checker = ClusterChecker(device_doc_path=doc)
        result = checker.device_lookup("spark01")
        assert result["found"] is True
        assert checker._backend is None

    @pytest.mark.asyncio
    async def test_health_check_creates_backend_on_demand(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """首次 HTTP 探测时才构造默认 backend，且仅构造一次。"""
        created: list[FakeHttpBackend] = []

        class FakeHttpxBackend(FakeHttpBackend):
            def __init__(self, timeout: float) -> None:
                super().__init__()
                created.append(self)

        monkeypatch.setattr("omni_openclaw.cluster._HttpxBackend", FakeHttpxBackend)
        checker = ClusterChecker()
        assert checker._backend is None
        await checker.health_check()
        assert len(created) == 1
        assert checker._backend is created[0]
        # 再次探测复用同一 backend，不重复创建
        await checker.health_check()
        assert len(created) == 1

    @pytest.mark.asyncio
    async def test_close_releases_lazily_created_backend(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """close 必须关闭惰性创建的自有 backend。"""
        closed: list[bool] = []

        class FakeHttpxBackend(FakeHttpBackend):
            def __init__(self, timeout: float) -> None:
                super().__init__()

            async def close(self) -> None:
                closed.append(True)

        monkeypatch.setattr("omni_openclaw.cluster._HttpxBackend", FakeHttpxBackend)
        checker = ClusterChecker()
        await checker.health_check()
        await checker.close()
        assert closed == [True]

    @pytest.mark.asyncio
    async def test_close_without_use_is_noop(self) -> None:
        """从未使用的 checker 调 close 不得创建 backend、不得报错。"""
        checker = ClusterChecker()
        await checker.close()
        assert checker._backend is None


class TestHealthUrl:
    """_health_url 探测 URL 构造测试。"""

    def test_v1_endpoint_uses_models_probe(self) -> None:
        """OpenAI 兼容端点（/v1 结尾）应使用 /v1/models 探针。"""
        url = ClusterChecker._health_url("http://host:8000/v1")
        assert url == "http://host:8000/v1/models"

    def test_non_v1_endpoint_uses_health_probe(self) -> None:
        """非 /v1 端点应使用 /health 探针，末尾斜杠不重复。"""
        assert ClusterChecker._health_url("http://host:9200") == "http://host:9200/health"
        assert ClusterChecker._health_url("http://host:9200/") == "http://host:9200/health"


class TestClusterHttpxBackend:
    """真实 _HttpxBackend 包装层测试（httpx 已 fake 注入，不触碰网络）。"""

    @pytest.mark.asyncio
    async def test_request_parses_json(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """可解析 JSON 的响应应返回 (status, 字典)，timeout 应透传。"""
        created = _install_fake_httpx(monkeypatch)
        backend = _HttpxBackend(timeout=5.0)
        created[0].responses.append(
            _FakeHttpResponse(status_code=200, json_data={"status": "ok"})
        )
        status, body = await backend.request("GET", "http://host:9200/health")
        assert status == 200
        assert body == {"status": "ok"}

        client = created[0]
        assert client.kwargs["timeout"] == 5.0
        assert client.requests[-1]["method"] == "GET"
        assert client.requests[-1]["url"] == "http://host:9200/health"

    @pytest.mark.asyncio
    async def test_request_falls_back_to_text_when_not_json(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """响应体非 JSON 时应降级返回文本。"""
        created = _install_fake_httpx(monkeypatch)
        backend = _HttpxBackend(timeout=5.0)
        created[0].responses.append(
            _FakeHttpResponse(status_code=503, text="Service Unavailable", json_raises=True)
        )
        status, body = await backend.request("GET", "http://host:9200/health")
        assert status == 503
        assert body == "Service Unavailable"

    @pytest.mark.asyncio
    async def test_close_releases_client(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """close 应关闭底层 httpx client。"""
        created = _install_fake_httpx(monkeypatch)
        backend = _HttpxBackend(timeout=5.0)
        await backend.close()
        assert created[0].closed is True


class TestDefaultSshRunner:
    """默认 SSH runner（asyncssh）异常路径测试。"""

    @pytest.mark.asyncio
    async def test_connect_failure_returns_not_healthy(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """SSH 连接失败时 runner 应返回 (False, 错误详情)，而非抛出异常。"""

        class RaisingAsyncSSH:
            @staticmethod
            def connect(host: str) -> Any:
                raise OSError("connection refused")

        monkeypatch.setitem(sys.modules, "asyncssh", RaisingAsyncSSH())
        runner = _make_default_ssh_runner()
        assert runner is not None
        healthy, detail = await runner("openclaw01")
        assert healthy is False
        assert "connection refused" in detail


class TestSshProbe:
    """_probe_ssh 边界测试。"""

    @pytest.mark.asyncio
    async def test_probe_ssh_without_runner(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """SSH runner 缺失时应返回未配置提示。"""
        monkeypatch.setitem(sys.modules, "asyncssh", None)
        checker = ClusterChecker()
        result = await checker._probe_ssh("openclaw01")
        assert result == {
            "host": "openclaw01",
            "ok": False,
            "detail": "SSH runner 未配置",
        }
