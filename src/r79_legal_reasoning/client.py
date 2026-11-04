from __future__ import annotations

import hashlib
import json
import os
import threading
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema

from .settings import ROUTE_CONFIG


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_json(text: str) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=unique)


def _vllm_guided_schema(value: Any) -> Any:
    """Remove only keywords unsupported by vLLM's guided-decoding compiler.

    The original schema is still applied locally after generation, so this compatibility
    projection does not relax the accepted result.
    """
    if isinstance(value, dict):
        return {
            key: _vllm_guided_schema(child) for key, child in value.items() if key != "uniqueItems"
        }
    if isinstance(value, list):
        return [_vllm_guided_schema(child) for child in value]
    return value


_GLOBAL_CONCURRENCY = int(
    os.environ.get(
        "R79_MAX_CONCURRENT_BACKEND", str(ROUTE_CONFIG["backend"]["max_concurrent_requests"])
    )
)
if not 1 <= _GLOBAL_CONCURRENCY <= 8:
    raise ValueError("R79_MAX_CONCURRENT_BACKEND must be between 1 and 8")
_GLOBAL_BACKEND_GATE = threading.BoundedSemaphore(_GLOBAL_CONCURRENCY)

# Mac 适配:未加载 LoRA 适配器的基模在 enable_thinking=true 时思考不收敛,
# 草稿会耗尽 token 预算(finish_reason=length)。R79_DRAFT_THINKING=0 时草稿阶段
# 关闭思考通道,让模型直接输出核验清单;原 NVIDIA+适配器环境保持默认开启。
_DRAFT_THINKING = os.environ.get("R79_DRAFT_THINKING", "1").lower() not in {
    "0",
    "false",
    "no",
    "off",
}


@dataclass
class StageResult:
    content: str
    reasoning_content: str
    usage: dict[str, Any]
    raw: dict[str, Any]


class AuditWriter:
    """Append local audit records with private content opt-in rather than default."""

    def __init__(self, root: Path, mode: str):
        if mode not in {"off", "hashes", "full"}:
            raise ValueError("audit mode must be off, hashes, or full")
        self.root = root
        self.mode = mode

    def write(self, workflow_id: str, sequence: int, value: dict[str, Any]) -> Path | None:
        if self.mode == "off":
            return None
        folder = self.root / workflow_id
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            folder.chmod(0o700)
        except OSError:
            pass
        record = value
        if self.mode == "hashes":
            allowed = {
                "label",
                "created_at",
                "kind",
                "status",
                "finish_reason",
                "request_sha256",
                "response_sha256",
                "usage",
                "token_count",
                "reserved_output_tokens",
                "max_model_len",
                "error",
            }
            record = {key: child for key, child in value.items() if key in allowed}
        path = folder / f"{sequence:02d}.json"
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return path


class OpenAIChatClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: int,
        audit_dir: Path,
        *,
        audit_mode: str = "hashes",
        max_model_len: int = 16384,
    ):
        self.base_url = base_url.rstrip("/")
        self.server_root = self.base_url.removesuffix("/v1")
        self.timeout_seconds = timeout_seconds
        self.max_model_len = max_model_len
        self.audit = AuditWriter(audit_dir, audit_mode)
        self.native_requests = 0
        self.tokenizer_preflights = 0
        self.audit_events = 0

    def _record(self, workflow_id: str, value: dict[str, Any]) -> None:
        self.audit_events += 1
        self.audit.write(workflow_id, self.audit_events, value)

    def _post(self, url: str, body: dict[str, Any]) -> tuple[int, bytes]:
        request_raw = canonical_bytes(body)
        request = urllib.request.Request(
            url,
            data=request_raw,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _GLOBAL_BACKEND_GATE:
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    return response.status, response.read()
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read()

    def _preflight(
        self,
        *,
        adapter: str,
        messages: list[dict[str, str]],
        enable_thinking: bool,
        reserved_output_tokens: int,
        workflow_id: str,
        label: str,
    ) -> int:
        self.tokenizer_preflights += 1
        body = {
            "model": adapter,
            "messages": messages,
            "add_generation_prompt": True,
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        }
        request_raw = canonical_bytes(body)
        try:
            status, response_raw = self._post(f"{self.server_root}/tokenize", body)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self._record(
                workflow_id,
                {
                    "label": label,
                    "kind": "tokenizer_preflight",
                    "created_at": datetime.now(UTC).isoformat(),
                    "status": "transport_error",
                    "request_sha256": sha256(request_raw),
                    "request": body,
                    "error": repr(exc),
                },
            )
            raise RuntimeError(f"tokenizer preflight unavailable for {label}") from exc
        try:
            response = _strict_json(response_raw.decode("utf-8"))
            count = response.get("count")
            if not isinstance(count, int):
                token_ids = response.get("tokens") or response.get("token_ids")
                count = len(token_ids) if isinstance(token_ids, list) else None
            if status != 200 or not isinstance(count, int):
                raise ValueError(f"HTTP {status}, invalid token count")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
            self._record(
                workflow_id,
                {
                    "label": label,
                    "kind": "tokenizer_preflight",
                    "created_at": datetime.now(UTC).isoformat(),
                    "status": status,
                    "request_sha256": sha256(request_raw),
                    "response_sha256": sha256(response_raw),
                    "request": body,
                    "response_raw": response_raw.decode("utf-8", errors="replace"),
                    "error": repr(exc),
                },
            )
            raise RuntimeError(f"invalid tokenizer preflight for {label}") from exc
        record = {
            "label": label,
            "kind": "tokenizer_preflight",
            "created_at": datetime.now(UTC).isoformat(),
            "status": status,
            "request_sha256": sha256(request_raw),
            "response_sha256": sha256(response_raw),
            "request": body,
            "response": response,
            "token_count": count,
            "reserved_output_tokens": reserved_output_tokens,
            "max_model_len": self.max_model_len,
        }
        self._record(workflow_id, record)
        if count + reserved_output_tokens > self.max_model_len:
            raise RuntimeError(
                f"context budget exceeded for {label}: {count}+{reserved_output_tokens}>"
                f"{self.max_model_len}; source was not truncated"
            )
        return count

    def _request(self, body: dict[str, Any], workflow_id: str, label: str) -> StageResult:
        self.native_requests += 1
        request_raw = canonical_bytes(body)
        try:
            status, response_raw = self._post(f"{self.base_url}/chat/completions", body)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self._record(
                workflow_id,
                {
                    "label": label,
                    "kind": "generation",
                    "created_at": datetime.now(UTC).isoformat(),
                    "status": "transport_error",
                    "request_sha256": sha256(request_raw),
                    "request": body,
                    "error": repr(exc),
                },
            )
            raise RuntimeError(f"vLLM transport failed for {label}") from exc
        record: dict[str, Any] = {
            "label": label,
            "kind": "generation",
            "created_at": datetime.now(UTC).isoformat(),
            "status": status,
            "request_sha256": sha256(request_raw),
            "response_sha256": sha256(response_raw),
            "request": body,
        }
        try:
            value = _strict_json(response_raw.decode("utf-8"))
            if status != 200:
                message = value.get("error", {}).get("message", "")
                record.update({"response": value, "error": message or f"HTTP {status}"})
                self._record(workflow_id, record)
                raise RuntimeError(f"vLLM HTTP {status} for {label}: {message or 'no detail'}")
            message = value["choices"][0]["message"]
            finish_reason = value["choices"][0].get("finish_reason")
            content = message.get("content") or ""
            # Mac 适配:vllm-metal 将思考内容放在 "reasoning" 字段,
            # 标准 vLLM(NVIDIA)为 "reasoning_content",两者都接受。
            reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
            record.update(
                {
                    "finish_reason": finish_reason,
                    "usage": value.get("usage", {}),
                    "response": value,
                }
            )
        except RuntimeError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            record.update(
                {
                    "response_raw": response_raw.decode("utf-8", errors="replace"),
                    "error": repr(exc),
                }
            )
            self._record(workflow_id, record)
            raise RuntimeError(f"invalid OpenAI response for {label}") from exc
        self._record(workflow_id, record)
        if finish_reason not in ("stop", None):
            raise RuntimeError(f"non-terminal model response for {label}: {finish_reason}")
        if not content.strip() and not reasoning.strip():
            raise RuntimeError(f"blank model response for {label}")
        return StageResult(
            content=content, reasoning_content=reasoning, usage=value.get("usage", {}), raw=value
        )

    def bounded_two_stage(
        self,
        *,
        adapter: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any],
        workflow_id: str,
        label: str,
        reasoning_budget: int,
        final_budget: int,
    ) -> dict[str, Any]:
        draft_messages = [
            *messages,
            {
                "role": "user",
                "content": (
                    "先只生成私有核验草稿，不输出最终答案或最终JSON。最多12条，每条一句；"
                    "依次核对主体、事件、日期、证据状态、必要条件和引用缺口。不得重复确认"
                    "同一字段，列完即停止。系统中的JSON要求留给下一阶段定稿。"
                ),
            },
        ]
        self._preflight(
            adapter=adapter,
            messages=draft_messages,
            enable_thinking=_DRAFT_THINKING,
            reserved_output_tokens=reasoning_budget,
            workflow_id=workflow_id,
            label=f"{label}.draft.preflight",
        )
        draft_body = {
            "model": adapter,
            "messages": draft_messages,
            "stream": False,
            "temperature": 0,
            "top_p": 1,
            "repetition_penalty": 1.05,
            "max_tokens": reasoning_budget,
            "chat_template_kwargs": {"enable_thinking": _DRAFT_THINKING},
        }
        draft = self._request(draft_body, workflow_id, f"{label}.draft")
        full_draft = "\n".join(x for x in (draft.reasoning_content, draft.content) if x).strip()
        if not full_draft:
            raise RuntimeError(f"empty draft for {label}")
        final_messages = [
            *messages,
            {
                "role": "assistant",
                "content": (
                    "Private working draft follows. Recheck every statement against the original materials, "
                    "correct it as needed, and return only the requested final JSON.\n<draft>\n"
                    + full_draft
                    + "\n</draft>"
                ),
            },
            {
                "role": "user",
                "content": (
                    "Produce the final answer now. Do not reveal the private draft. "
                    "每个实体、事件、步骤、证据或命题只列一次，不得重复、同义扩写或为了耗尽预算"
                    "新增编号。"
                    "Return exactly one JSON object matching this JSON Schema; do not add "
                    "Markdown or commentary outside the object:\n"
                    + json.dumps(response_schema, ensure_ascii=False, separators=(",", ":"))
                ),
            },
        ]
        self._preflight(
            adapter=adapter,
            messages=final_messages,
            enable_thinking=False,
            reserved_output_tokens=final_budget,
            workflow_id=workflow_id,
            label=f"{label}.final.preflight",
        )
        final_body = {
            "model": adapter,
            "messages": final_messages,
            "stream": False,
            "temperature": 0,
            "top_p": 1,
            "repetition_penalty": 1.05,
            "max_tokens": final_budget,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": label.replace(".", "_"),
                    "strict": True,
                    "schema": _vllm_guided_schema(response_schema),
                },
            },
        }
        final = self._request(final_body, workflow_id, f"{label}.final")
        try:
            value = _strict_json(final.content)
            jsonschema.validate(instance=value, schema=response_schema)
        except (json.JSONDecodeError, ValueError, TypeError, jsonschema.ValidationError) as exc:
            raise RuntimeError(
                f"final response failed local schema validation for {label}"
            ) from exc
        if not isinstance(value, dict):
            raise TypeError(f"final response is not an object for {label}")
        return value


def new_workflow_id() -> str:
    return uuid.uuid4().hex
