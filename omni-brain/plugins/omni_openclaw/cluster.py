"""omni_openclaw 集群巡检与设备管家。

提供 ``ClusterChecker`` 用于并行探测 OpenClaw 网关、LLM、ComfyUI、TTS、Embedding
等集群端点，并支持读取 ``AIHub/设备说明.md`` 进行设备信息查询。

所有网络访问均通过可注入的 HTTP backend 完成；SSH 探测通过可注入的 runner
完成，便于单元测试使用 fake 依赖。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from omni_openclaw.config import OpenClawConfig
from omni_openclaw.errors import error_response, success_response


#: AIHub 设备说明文档路径（只读）
DEVICE_DOC_PATH: Path = Path(
    "/Users/wangzhenyu/Desktop/ALLProject/AIHub/设备说明.md"
)

#: 默认 SSH 探测主机名列表（仅 hostname，不含 IP/密钥）
DEFAULT_SSH_HOSTS: list[str] = [
    "openclaw01",
    "openclaw02",
    "openclaw03",
    "openclaw04",
]

#: 慢响应阈值（毫秒）
SLOW_THRESHOLD_MS: float = 2000.0


class HttpBackend(Protocol):
    """HTTP backend 抽象协议，支持按完整 URL 请求。"""

    async def request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> tuple[int, Any]:
        """执行 HTTP 请求，返回 (status_code, body)。"""
        ...


class SshRunner(Protocol):
    """SSH runner 抽象协议。"""

    async def __call__(self, host: str) -> tuple[bool, str]:
        """探测单个主机，返回 (is_healthy, detail)。"""
        ...


class _HttpxBackend:
    """基于 httpx 的真实 HTTP backend，按需创建。"""

    def __init__(self, timeout: float) -> None:
        import httpx

        self._client = httpx.AsyncClient(timeout=timeout)

    async def request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> tuple[int, Any]:
        """执行 HTTP 请求。"""
        response = await self._client.request(method, url, **kwargs)
        body: Any
        try:
            body = response.json()
        except Exception:
            body = response.text
        return response.status_code, body

    async def close(self) -> None:
        """关闭底层连接。"""
        await self._client.aclose()


def _make_default_ssh_runner() -> SshRunner | None:
    """若安装 ``asyncssh`` 则构造默认 SSH runner，否则返回 ``None``。

    使用函数内惰性导入，避免在缺少 ``asyncssh`` 的环境拖慢模块加载。
    """
    try:
        import asyncssh
    except Exception:
        return None

    async def _runner(host: str) -> tuple[bool, str]:
        try:
            async with asyncssh.connect(host) as conn:
                result = await conn.run("uptime", check=True)
                return True, result.stdout.strip()
        except Exception as exc:
            return False, str(exc)

    return _runner


class ClusterChecker:
    """集群巡检器：并行健康检查 + 设备文档查询。"""

    def __init__(
        self,
        config: OpenClawConfig | None = None,
        backend: HttpBackend | None = None,
        ssh_runner: SshRunner | None = None,
        ssh_hosts: list[str] | None = None,
        device_doc_path: Path | None = None,
    ) -> None:
        """初始化巡检器。

        Args:
            config: OpenClaw 配置；为空时使用默认配置。
            backend: 可注入的 HTTP backend，测试时传入 fake。
            ssh_runner: 可注入的 SSH runner，测试时传入 fake。
            ssh_hosts: SSH 探测目标主机名列表。
            device_doc_path: 设备说明文档路径，测试时可覆盖。
        """
        self.config = config or OpenClawConfig()
        if backend is None:
            self._backend: HttpBackend = _HttpxBackend(self.config.timeout_s)
            self._owns_backend = True
        else:
            self._backend = backend
            self._owns_backend = False

        self._ssh_runner = ssh_runner or _make_default_ssh_runner()
        self._ssh_hosts = ssh_hosts or DEFAULT_SSH_HOSTS
        self._device_doc_path = device_doc_path or DEVICE_DOC_PATH

    @staticmethod
    def _health_url(endpoint: str) -> str:
        """构造健康检查 URL。

        OpenAI 兼容端点（以 ``/v1`` 结尾）使用 ``/v1/models`` 作为可用性探针，
        避免 vLLM 等服务的 ``/health`` 不在 ``/v1`` 路径下导致误报。
        """
        base = endpoint.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/models"
        return f"{base}/health"

    def _build_endpoints(self) -> list[tuple[str, str, str]]:
        """构造巡检端点列表（名称, 优先级, URL）。"""
        cfg = self.config
        return [
            ("gateway", "p0", f"{cfg.gateway.rstrip('/')}/health"),
            ("llm_l1", "p0", self._health_url(cfg.llm_l1_endpoint)),
            ("llm_l4", "p1", self._health_url(cfg.llm_l4_endpoint)),
            (
                "comfyui",
                "p1",
                f"{cfg.comfyui_endpoint.rstrip('/')}/system_stats",
            ),
            ("tts", "p1", f"{cfg.tts_endpoint.rstrip('/')}/health"),
            # Qwen3-Embedding-4B :9302 只实现了 /health 与 /v1/embeddings，没有 /v1/models
            ("embedding", "p1", f"{cfg.embedding_endpoint.rstrip('/').removesuffix('/v1')}/health"),
        ]

    async def _probe_http(self, name: str, priority: str, url: str) -> dict[str, Any]:
        """探测单个 HTTP 端点，返回统一结果字典。"""
        start = time.perf_counter()
        try:
            status, body = await self._backend.request("GET", url)
        except Exception as exc:
            status = 0
            body = str(exc)
        elapsed_ms = (time.perf_counter() - start) * 1000

        return {
            "name": name,
            "priority": priority,
            "url": url,
            "status": status,
            "elapsed_ms": round(elapsed_ms, 1),
            "body": body,
            "ok": status == 200,
        }

    async def _probe_ssh(self, host: str) -> dict[str, Any]:
        """探测单个 SSH 主机。"""
        if self._ssh_runner is None:
            return {
                "host": host,
                "ok": False,
                "detail": "SSH runner 未配置",
            }
        healthy, detail = await self._ssh_runner(host)
        return {"host": host, "ok": healthy, "detail": detail}

    async def health_check(self) -> dict[str, Any]:
        """并行执行集群健康检查，返回 P0/P1/P2 分级报告。

        分级规则：
        - P0：网关、L1 模型不可用（status != 200 或异常）。
        - P1：L4、ComfyUI、TTS、Embedding 不可用。
        - P2：任意端点响应慢（>2s）或返回非 200。
        """
        endpoints = self._build_endpoints()
        http_results: list[dict[str, Any]] = await asyncio.gather(
            *[self._probe_http(name, priority, url) for name, priority, url in endpoints]
        )

        ssh_results: list[dict[str, Any]] = []
        if self._ssh_runner is not None:
            ssh_results = await asyncio.gather(
                *[self._probe_ssh(host) for host in self._ssh_hosts]
            )

        p0 = [r for r in http_results if r["priority"] == "p0" and not r["ok"]]
        p1 = [r for r in http_results if r["priority"] == "p1" and not r["ok"]]
        p2 = [
            r
            for r in http_results
            if r["ok"] is False or r["elapsed_ms"] > SLOW_THRESHOLD_MS
        ]

        if p0:
            summary = f"关键服务异常：{len(p0)} 个 P0 端点不可用"
        elif p1:
            summary = f"次级服务异常：{len(p1)} 个 P1 端点不可用"
        elif p2:
            summary = f"服务降级：{len(p2)} 个端点响应慢或非 200"
        else:
            summary = "集群健康"

        report = {
            "p0": p0,
            "p1": p1,
            "p2": p2,
            "details": http_results,
            "ssh": ssh_results,
        }
        return success_response(report=report, summary=summary)

    def device_lookup(self, query: str) -> dict[str, Any]:
        """在设备说明文档中查询与 ``query`` 匹配的设备信息。

        文件不存在时返回友好提示，仍标记 ``ok=true``（属于信息查询，非错误）。
        """
        path = self._device_doc_path
        if not path.exists():
            return success_response(
                found=False,
                path=str(path),
                summary="设备说明文件不存在，无法查询",
                matches=[],
            )

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return error_response(
                "E_DEVICE_DOC_READ",
                f"读取设备说明文件失败: {exc}",
                path=str(path),
            )

        lines = text.splitlines()
        keyword = str(query).strip().lower()
        matches: list[dict[str, Any]] = []
        current_section = ""

        for index, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                current_section = stripped.lstrip("#").strip()
            if not keyword or keyword in stripped.lower():
                matches.append(
                    {
                        "line": index,
                        "section": current_section,
                        "content": stripped,
                    }
                )

        if keyword:
            summary = f"找到 {len(matches)} 条匹配" if matches else "未找到匹配设备"
        else:
            summary = f"文档共 {len(lines)} 行，请提供查询关键字"

        return success_response(
            found=bool(matches),
            path=str(path),
            query=query,
            summary=summary,
            matches=matches[:20],
        )

    async def close(self) -> None:
        """释放 backend 资源。"""
        if self._owns_backend and hasattr(self._backend, "close"):
            await self._backend.close()
