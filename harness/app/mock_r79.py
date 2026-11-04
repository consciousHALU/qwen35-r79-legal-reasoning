"""模拟 R79 后端,两种用途:

1. ``MockBackend``:与 :class:`app.r79_client.R79Client` 同接口的进程内模拟器,
   供 HARNESS_MOCK=1 时 main.py 直接使用(无网络、无延迟)。
2. 独立 FastAPI 服务:``python -m app.mock_r79`` 在 127.0.0.1:8088 启动,
   完整模拟真实 R79 API 的三个端点(/health、/v1/legal/assist、
   /v1/wiki/similar-case/search),每次 assist 人为 sleep 1.5 秒模拟推理耗时。

所有数据来自 app.sample_case(虚构合成数据)。
"""
from __future__ import annotations

import time

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .sample_case import MOCK_WIKI_RESULT, build_mock_assist

MOCK_HEALTH: dict = {
    "status": "ok",
    "model_repo": "mock-r79-legal-reasoning",
    "model_revision": "mock",
    "vllm_url": "mock://local",
    "backend": {"reachable": True, "status": 200, "models": {"data": ["mock-r79"]}},
    "graph_verified": True,
    "wiki_available": True,
    "routes": ["facts_1949", "procedure_1978", "candidate_r79"],
    "excluded": ["2008", "2026"],
    "errors": [],
    "mock_notice": "演示模式:本健康信息由内置模拟器生成。",
}


class MockBackend:
    """与 R79Client 同接口的进程内模拟后端(HARNESS_MOCK=1 时使用)。"""

    def __init__(self, base_url: str = "mock://local", timeout: float = 0.0) -> None:
        self.base_url = base_url
        self.timeout = timeout

    def close(self) -> None:  # 与 R79Client 接口对齐
        return None

    def health(self) -> dict:
        return dict(MOCK_HEALTH)

    def assist(self, user_request: str, materials: list[dict]) -> dict:
        return build_mock_assist(user_request, materials)

    def wiki_search(self, query: str) -> dict | None:
        result = dict(MOCK_WIKI_RESULT)
        result["query"] = query
        return result


# ---------------------------------------------------------------------------
# 独立运行的模拟 R79 API(模拟真实 8088 端口)
# ---------------------------------------------------------------------------

app = FastAPI(title="Mock R79 legal reasoning", version="1.0.0-mock")


class _MaterialInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1)


class _AssistInput(BaseModel):
    user_request: str = Field(min_length=1, max_length=20_000)
    raw_materials: list[_MaterialInput] = Field(min_length=1, max_length=99)


class _SearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=8000)


@app.get("/health")
def health() -> dict:
    return dict(MOCK_HEALTH)


@app.post("/v1/legal/assist")
def assist(payload: _AssistInput) -> dict:
    time.sleep(1.5)  # 模拟真实推理耗时
    return build_mock_assist(
        payload.user_request,
        [m.model_dump() for m in payload.raw_materials],
    )


@app.post("/v1/wiki/similar-case/search")
def similar_case(payload: _SearchInput) -> dict:
    result = dict(MOCK_WIKI_RESULT)
    result["query"] = payload.query
    return result


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8088, log_level="info")


if __name__ == "__main__":
    main()
