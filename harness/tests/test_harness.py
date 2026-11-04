"""Harness 后端测试(HARNESS_MOCK=1,TestClient,不起真实端口)。"""
from __future__ import annotations

import os

# config 在 import 时读取环境变量,必须先于 app 模块导入设置
os.environ["HARNESS_MOCK"] = "1"

import pytest
from fastapi.testclient import TestClient

from app import main
from app.sample_case import SAMPLE_MATERIALS, SAMPLE_QUESTION


@pytest.fixture()
def client(monkeypatch):
    """monkeypatch 设置 HARNESS_MOCK=1 并用 MockBackend 重建后端实例。"""
    monkeypatch.setenv("HARNESS_MOCK", "1")
    monkeypatch.setattr(main, "backend", main.build_backend())
    with TestClient(main.app) as c:
        yield c


def test_status_mock_true(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["harness"] == "ok"
    assert data["mock"] is True
    assert data["backend"]["status"] == "ok"


def test_sample_case(client):
    resp = client.get("/api/sample-case")
    assert resp.status_code == 200
    data = resp.json()
    assert data["question"]
    assert len(data["materials"]) >= 1
    assert "overrides" in data


def test_consult_returns_workflow_id(client):
    resp = client.post(
        "/api/consult",
        json={"question": SAMPLE_QUESTION, "materials": SAMPLE_MATERIALS, "search_wiki": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["workflow_id"]
    assert data["meta"]["backend_generation_requests"] is not None
    assert "routing" in data["meta"]
    assert data["assist"]["answer"]["conclusion"]
    assert data["wiki"] is None


def test_consult_with_wiki(client):
    resp = client.post(
        "/api/consult",
        json={"question": SAMPLE_QUESTION, "materials": SAMPLE_MATERIALS, "search_wiki": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["wiki"] is not None
    assert data["wiki"]["mode"] == "retrieval_only"
    assert data["wiki"]["query"] == SAMPLE_QUESTION


def test_consult_empty_question_400(client):
    resp = client.post(
        "/api/consult",
        json={"question": "", "materials": SAMPLE_MATERIALS, "search_wiki": False},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]


def test_consult_empty_materials_400(client):
    resp = client.post(
        "/api/consult",
        json={"question": SAMPLE_QUESTION, "materials": [], "search_wiki": False},
    )
    assert resp.status_code == 400


def test_evidence_chain_matrix_consistent(client):
    resp = client.post("/api/evidence-chain", json={"materials": SAMPLE_MATERIALS})
    assert resp.status_code == 200
    data = resp.json()
    chain = data["chain"]
    matrix = chain["matrix"]
    assert matrix["event_ids"]
    assert matrix["evidence_ids"]
    # matrix cells 必须与 evidence.supports_event_ids 严格一致
    supports = {e["evidence_id"]: set(e.get("supports_event_ids") or []) for e in chain["evidence"]}
    assert len(matrix["cells"]) == len(matrix["event_ids"])
    for i, ev_id in enumerate(matrix["event_ids"]):
        assert len(matrix["cells"][i]) == len(matrix["evidence_ids"])
        for j, evd_id in enumerate(matrix["evidence_ids"]):
            assert matrix["cells"][i][j] == (ev_id in supports[evd_id])
    # stats 与 timeline 排序
    assert data["chain"]["stats"]["events"] == len(matrix["event_ids"])
    dates = [t["date_text"] for t in chain["timeline"] if t["date_status"] == "exact"]
    assert dates == sorted(dates)
    assert data["report_markdown"].startswith("# 行政案件证据链梳理报告")


def test_draft_with_overrides(client):
    resp = client.post(
        "/api/draft",
        json={
            "materials": SAMPLE_MATERIALS,
            "overrides": {"applicant_name": "张某", "review_organ": "某县人民政府",
                          "claims_text": "", "third_party": ""},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "行政复议申请书" in data["document_markdown"]
    assert "此致" in data["document_markdown"]
    assert "某县人民政府" in data["document_markdown"]
    assert data["review_notes"]
    assert any("人工核对" in n for n in data["review_notes"])
    assert data["docx_token"]
    # docx 下载 200
    dl = client.get(f"/api/draft/download/{data['docx_token']}")
    assert dl.status_code == 200
    assert dl.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert dl.content[:2] == b"PK"  # docx 是 zip


def test_draft_without_overrides_has_pending(client):
    resp = client.post("/api/draft", json={"materials": SAMPLE_MATERIALS})
    assert resp.status_code == 200
    data = resp.json()
    assert "行政复议申请书" in data["document_markdown"]
    assert "此致" in data["document_markdown"]
    assert "【待补充" in data["document_markdown"]
    assert any("待补充" in n for n in data["review_notes"])


def test_draft_download_bad_token_404(client):
    resp = client.get("/api/draft/download/nonexistent-token")
    assert resp.status_code == 404
    assert resp.json()["detail"]


def test_mock_r79_module_importable():
    import app.mock_r79 as mock_mod

    assert mock_mod.app is not None
    routes = {getattr(r, "path", "") for r in mock_mod.app.routes}
    assert "/health" in routes
    assert "/v1/legal/assist" in routes
    assert "/v1/wiki/similar-case/search" in routes
