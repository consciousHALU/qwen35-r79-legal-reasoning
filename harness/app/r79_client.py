"""R79 推理 API 的 httpx 同步客户端。

封装对真实后端(默认 http://127.0.0.1:8088)的三个端点:
- GET  /health
- POST /v1/legal/assist
- POST /v1/wiki/similar-case/search

约定:
- 网络层异常(连接失败、超时等)一律转为 RuntimeError,携带中文说明,
  由上层(main.py)统一映射为 503。
- 上游返回非 2xx 时抛 httpx.HTTPStatusError,由上层区分 5xx → 502。
- wiki 检索不可用时返回 None(不视为致命错误)。
"""
from __future__ import annotations

import httpx


class R79Client:
    """访问 R79 本地推理 API 的同步客户端。"""

    def __init__(self, base_url: str, timeout: float = 660.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "R79Client":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def health(self) -> dict:
        """GET /health。网络异常抛 RuntimeError(中文信息)。"""
        try:
            resp = self._client.get("/health")
            resp.raise_for_status()
            return resp.json()
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise RuntimeError(f"无法连接推理服务 {self.base_url}:{exc}") from exc

    def assist(self, user_request: str, materials: list[dict]) -> dict:
        """POST /v1/legal/assist。网络异常抛 RuntimeError(中文信息)。"""
        payload = {"user_request": user_request, "raw_materials": materials}
        try:
            resp = self._client.post("/v1/legal/assist", json=payload)
            resp.raise_for_status()
            return resp.json()
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise RuntimeError(f"无法连接推理服务 {self.base_url}:{exc}") from exc

    def wiki_search(self, query: str) -> dict | None:
        """POST /v1/wiki/similar-case/search。

        wiki 不可用(网络异常、5xx、返回 result 为 null 等)时返回 None,
        不阻断主流程;仅在网络层正常时返回原始响应 dict。
        """
        try:
            resp = self._client.post("/v1/wiki/similar-case/search", json={"query": query})
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError):
            return None
        if resp.status_code >= 500:
            return None
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            return None
        try:
            return resp.json()
        except ValueError:
            return None
