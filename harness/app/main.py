"""Harness FastAPI 应用:三大场景(咨询 / 证据链梳理 / 文书起草)的 Web 壳。

端点(见 SPEC):
- GET  /                          → static/index.html
- GET  /static/*                  → 前端静态资源
- GET  /api/status                → 后端健康状态(mock 标识 + 8088 /health 透传)
- GET  /api/sample-case           → 示例案件
- POST /api/consult               → 案件咨询(可选类案检索,只读不注入)
- POST /api/evidence-chain        → 证据链梳理(chain + report_markdown)
- POST /api/draft                 → 文书起草(document_markdown + review_notes + docx_token)
- GET  /api/draft/download/{token}→ 下载 docx

错误约定:ValueError → 400;连接异常 → 503;上游 5xx → 502;
响应体一律 {"detail": "中文友好说明"}。
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .drafting import build_document, make_docx
from .evidence import build_chain, build_report_markdown
from .mock_r79 import MockBackend
from .r79_client import R79Client
from .sample_case import sample_case

STATIC_DIR = Path(__file__).resolve().parent / "static"

# 三大场景内置默认 user_request(见 SPEC)
EVIDENCE_CHAIN_PROMPT = (
    "请梳理本案的主体、事件经过、日期与证据状态,"
    "逐一列明每份证据支持的事实、证据之间的矛盾以及尚无法确认的事项。"
)
DRAFT_PROMPT = (
    "请分析该行政行为的主体、程序与法律适用,"
    "评估其合法性与合理性,为起草行政复议申请书提供依据。"
)

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOCX_FILENAME = "行政复议申请书.docx"


def build_backend():
    """按 config.HARNESS_MOCK 构造后端实例(测试可替换 app.main.backend)。"""
    if config.HARNESS_MOCK:
        return MockBackend(base_url=config.R79_API_BASE, timeout=config.REQUEST_TIMEOUT)
    return R79Client(base_url=config.R79_API_BASE, timeout=config.REQUEST_TIMEOUT)


backend = build_backend()

app = FastAPI(title="行政复议智能助手 Harness", version="1.0.0")

# docx 令牌内存存储:{token: (bytes, 过期时间戳)}
_draft_store: dict[str, tuple[bytes, float]] = {}

# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class MaterialIn(BaseModel):
    title: str = ""
    text: str = ""


class ConsultIn(BaseModel):
    question: str = ""
    materials: list[MaterialIn] = []
    search_wiki: bool = False


class EvidenceChainIn(BaseModel):
    materials: list[MaterialIn] = []
    question: str = ""


class DraftIn(BaseModel):
    materials: list[MaterialIn] = []
    overrides: dict[str, str] = {}


# ---------------------------------------------------------------------------
# 校验与错误处理
# ---------------------------------------------------------------------------


def _validate_materials(materials: list[MaterialIn]) -> list[dict]:
    if not materials:
        raise ValueError("请至少提供一份案件材料。")
    cleaned = [{"title": m.title.strip(), "text": m.text.strip()} for m in materials]
    for i, m in enumerate(cleaned, 1):
        if not m["title"]:
            raise ValueError(f"第 {i} 份材料缺少标题。")
        if not m["text"]:
            raise ValueError(f"第 {i} 份材料「{m['title']}」正文为空。")
    return cleaned


def _backend_hint() -> str:
    parsed = urlparse(config.R79_API_BASE)
    hostport = parsed.netloc or config.R79_API_BASE
    return (
        f"无法连接推理服务 {hostport},请先按 README 启动 start_api.sh,"
        "或以演示模式运行:HARNESS_MOCK=1"
    )


@app.exception_handler(ValueError)
async def _value_error_handler(_request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(RuntimeError)
async def _runtime_error_handler(_request, exc: RuntimeError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": _backend_hint()})


@app.exception_handler(httpx.HTTPStatusError)
async def _http_status_error_handler(_request, exc: httpx.HTTPStatusError) -> JSONResponse:
    status = exc.response.status_code
    if status >= 500:
        detail = f"推理服务内部错误(HTTP {status}),请检查 8088 后端日志后重试。"
        return JSONResponse(status_code=502, content={"detail": detail})
    try:
        upstream_detail = exc.response.json().get("detail")
    except ValueError:
        upstream_detail = None
    detail = f"推理服务拒绝了请求(HTTP {status}):{upstream_detail or exc.response.text[:200]}"
    return JSONResponse(status_code=400, content={"detail": detail})


# ---------------------------------------------------------------------------
# 页面与静态资源
# ---------------------------------------------------------------------------


@app.get("/")
def index():
    index_html = STATIC_DIR / "index.html"
    if index_html.exists():
        return FileResponse(index_html)
    return JSONResponse(
        {
            "detail": "前端页面尚未就绪(static/index.html 不存在),"
            "API 已可用:/api/status、/api/consult、/api/evidence-chain、/api/draft。"
        }
    )


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@app.get("/api/status")
def api_status() -> dict:
    try:
        backend_health = backend.health()
    except (RuntimeError, httpx.HTTPError) as exc:
        backend_health = {"reachable": False, "error": str(exc)}
    return {"harness": "ok", "mock": config.HARNESS_MOCK, "backend": backend_health}


@app.get("/api/sample-case")
def api_sample_case() -> dict:
    return sample_case()


def _meta(assist: dict) -> dict:
    return {
        "workflow_id": assist.get("workflow_id"),
        "backend_generation_requests": assist.get("backend_generation_requests"),
        "routing": assist.get("routing"),
    }


@app.post("/api/consult")
def api_consult(payload: ConsultIn) -> dict:
    question = payload.question.strip()
    if not question:
        raise ValueError("请输入要咨询的问题。")
    materials = _validate_materials(payload.materials)
    assist = backend.assist(question, materials)
    wiki = backend.wiki_search(question) if payload.search_wiki else None
    return {"assist": assist, "wiki": wiki, "meta": _meta(assist)}


@app.post("/api/evidence-chain")
def api_evidence_chain(payload: EvidenceChainIn) -> dict:
    materials = _validate_materials(payload.materials)
    question = payload.question.strip() or EVIDENCE_CHAIN_PROMPT
    assist = backend.assist(question, materials)
    chain = build_chain(assist)
    report_markdown = build_report_markdown(assist, chain)
    return {"assist": assist, "chain": chain, "report_markdown": report_markdown}


@app.post("/api/draft")
def api_draft(payload: DraftIn) -> dict:
    materials = _validate_materials(payload.materials)
    assist = backend.assist(DRAFT_PROMPT, materials)
    document_markdown, review_notes = build_document(assist, payload.overrides or {})
    docx_bytes = make_docx(document_markdown)
    token = uuid.uuid4().hex
    _draft_store[token] = (docx_bytes, time.time() + config.DRAFT_TTL_SECONDS)
    return {
        "assist": assist,
        "document_markdown": document_markdown,
        "review_notes": review_notes,
        "docx_token": token,
    }


@app.get("/api/draft/download/{token}")
def api_draft_download(token: str) -> Response:
    now = time.time()
    # 过期清理
    for key in [k for k, (_, exp) in _draft_store.items() if exp <= now]:
        _draft_store.pop(key, None)
    entry = _draft_store.get(token)
    if entry is None:
        raise HTTPException(status_code=404, detail="下载链接不存在或已过期,请重新生成文书。")
    docx_bytes, _exp = entry
    filename_header = quote(DOCX_FILENAME)
    return Response(
        content=docx_bytes,
        media_type=DOCX_MEDIA_TYPE,
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"draft.docx\"; filename*=UTF-8''{filename_header}"
            )
        },
    )
