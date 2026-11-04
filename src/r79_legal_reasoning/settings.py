from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent
PACKAGE_DATA = PACKAGE_DIR / "data"
PACKAGE_CONFIG = PACKAGE_DIR / "config"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


MODEL_CONFIG = _load_json(PACKAGE_CONFIG / "model.json")
ROUTE_CONFIG = _load_json(PACKAGE_CONFIG / "routes.json")


def _path_env(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, str(default))).expanduser().resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class Settings:
    model_repo: str = field(
        default_factory=lambda: os.environ.get("R79_MODEL_REPO", MODEL_CONFIG["repository"])
    )
    model_revision: str = field(
        default_factory=lambda: os.environ.get(
            "R79_MODEL_REVISION", MODEL_CONFIG["verified_revision"]
        )
    )
    model_dir: Path = field(
        default_factory=lambda: _path_env(
            "R79_MODEL_DIR", Path.home() / ".cache" / "r79-legal-reasoning" / "model"
        )
    )
    vllm_url: str = field(
        default_factory=lambda: os.environ.get("R79_VLLM_URL", "http://127.0.0.1:8000/v1").rstrip(
            "/"
        )
    )
    graph_db: Path = field(
        default_factory=lambda: _path_env("R79_GRAPH_DB", PACKAGE_DATA / "graph.sqlite3")
    )
    graph_manifest: Path = field(
        default_factory=lambda: _path_env(
            "R79_GRAPH_MANIFEST", PACKAGE_DATA / "GRAPH_MANIFEST.json"
        )
    )
    wiki_db: Path = field(
        default_factory=lambda: _path_env(
            "R79_WIKI_DB", Path.home() / ".cache" / "r79-legal-reasoning" / "wiki.sqlite3"
        )
    )
    audit_dir: Path = field(
        default_factory=lambda: _path_env(
            "R79_AUDIT_DIR", Path.home() / ".cache" / "r79-legal-reasoning" / "audit"
        )
    )
    audit_mode: str = field(
        default_factory=lambda: os.environ.get("R79_AUDIT_MODE", "hashes").lower()
    )
    max_backend_requests: int = field(
        default_factory=lambda: int(os.environ.get("R79_MAX_BACKEND_REQUESTS", "8"))
    )
    timeout_seconds: int = field(
        default_factory=lambda: int(os.environ.get("R79_TIMEOUT_SECONDS", "600"))
    )
    reasoning_budget: int = field(
        default_factory=lambda: int(
            os.environ.get(
                "R79_REASONING_BUDGET", str(ROUTE_CONFIG["reasoning"]["reasoning_budget"])
            )
        )
    )
    final_budget: int = field(
        default_factory=lambda: int(
            os.environ.get("R79_FINAL_BUDGET", str(ROUTE_CONFIG["reasoning"]["final_budget"]))
        )
    )
    max_model_len: int = field(
        default_factory=lambda: int(
            # Mac 适配:可用 R79_MAX_MODEL_LEN 覆盖(本地 vllm-metal 跑 32768),
            # 默认仍取 routes.json(NVIDIA 验证环境为 16384)。
            os.environ.get("R79_MAX_MODEL_LEN", str(ROUTE_CONFIG["backend"]["max_model_len"]))
        )
    )

    facts_adapter: str = ROUTE_CONFIG["routes"]["fact_extraction"]
    procedure_adapter: str = ROUTE_CONFIG["routes"]["procedure_timeline"]
    reasoning_adapter: str = ROUTE_CONFIG["routes"]["legal_reasoning_and_final_answer"]

    def validate(self) -> None:
        if self.max_backend_requests < 6 or self.max_backend_requests > 8:
            raise ValueError("R79_MAX_BACKEND_REQUESTS must be between 6 and 8")
        if self.audit_mode not in {"off", "hashes", "full"}:
            raise ValueError("R79_AUDIT_MODE must be off, hashes, or full")
        if not self.vllm_url.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise ValueError("the public runtime accepts only a loopback vLLM endpoint")
        if not self.graph_db.is_file() or not self.graph_manifest.is_file():
            raise FileNotFoundError("reasoning graph database or manifest is missing")
        manifest = _load_json(self.graph_manifest)
        actual = _sha256(self.graph_db)
        if actual != manifest.get("public_database_sha256"):
            raise ValueError("reasoning graph SHA-256 does not match GRAPH_MANIFEST.json")
