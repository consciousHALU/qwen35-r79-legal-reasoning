#!/usr/bin/env bash
# Mac(Apple Silicon,无 NVIDIA GPU)本地一键启动:
#   vllm-metal(MLX 基模,四个别名)+ R79 推理 API(8088)+ Harness(8090)
#
# 与 NVIDIA 整栈的差异(由环境变量完成适配,不改默认行为):
#   - vLLM 用 --served-model-name 把 facts_1949 / procedure_1978 / candidate_r79
#     三个适配器名映射到同一个 MLX 基模(未加载 LoRA,用于流程验证与演示);
#   - R79_DRAFT_THINKING=0:基模思考通道不收敛,草稿阶段关闭 thinking;
#   - R79_MAX_MODEL_LEN=32768:与本地 vllm-metal 实际上下文一致;
#   - R79_REASONING_BUDGET / R79_FINAL_BUDGET:按 MLX 吞吐(~40 tok/s)调低。
#
# 用法:
#   VLLM_BIN=/path/to/vllm MODEL_PATH=/path/to/mlx-model bash scripts/start_local_mac.sh
# 若不提供 VLLM_BIN/MODEL_PATH,则假定 vLLM 已在 127.0.0.1:8000 以四别名运行,
# 本脚本只启动 R79 API 与 Harness。
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

R79_API_PORT="${R79_API_PORT:-8088}"
HARNESS_PORT="${HARNESS_PORT:-8090}"
VLLM_PORT="${VLLM_PORT:-8000}"

export R79_MAX_MODEL_LEN="${R79_MAX_MODEL_LEN:-32768}"
export R79_DRAFT_THINKING="${R79_DRAFT_THINKING:-0}"
export R79_REASONING_BUDGET="${R79_REASONING_BUDGET:-8192}"
export R79_FINAL_BUDGET="${R79_FINAL_BUDGET:-6144}"
export R79_AUDIT_MODE="${R79_AUDIT_MODE:-hashes}"

if [[ -n "${VLLM_BIN:-}" && -n "${MODEL_PATH:-}" ]]; then
  if ! curl -s -m 2 "http://127.0.0.1:${VLLM_PORT}/v1/models" >/dev/null 2>&1; then
    echo "[mac] starting vllm-metal on 127.0.0.1:${VLLM_PORT} ..."
    nohup "${VLLM_BIN}" serve \
      --model "${MODEL_PATH}" \
      --served-model-name qwen3.5-9b facts_1949 procedure_1978 candidate_r79 \
      --max-model-len "${R79_MAX_MODEL_LEN}" \
      --mamba-ssm-cache-dtype float32 \
      --reasoning-parser qwen3 \
      --default-chat-template-kwargs '{"enable_thinking": false}' \
      --host 127.0.0.1 --port "${VLLM_PORT}" \
      > /tmp/r79_mac_vllm.log 2>&1 &
    for _ in $(seq 1 36); do
      curl -s -m 2 "http://127.0.0.1:${VLLM_PORT}/v1/models" >/dev/null 2>&1 && break
      sleep 5
    done
  fi
fi

echo "[mac] backend models:"
curl -s -m 5 "http://127.0.0.1:${VLLM_PORT}/v1/models" | python3 -c \
  "import json,sys;print([m['id'] for m in json.load(sys.stdin)['data']])"

if ! curl -s -m 2 "http://127.0.0.1:${R79_API_PORT}/health" >/dev/null 2>&1; then
  echo "[mac] starting R79 API on 127.0.0.1:${R79_API_PORT} ..."
  (cd "${PROJECT_ROOT}" && nohup .venv/bin/python -m uvicorn r79_legal_reasoning.api:app \
    --host 127.0.0.1 --port "${R79_API_PORT}" > /tmp/r79_mac_api.log 2>&1 &)
  sleep 4
fi
curl -s -m 5 "http://127.0.0.1:${R79_API_PORT}/health" | python3 -c \
  "import json,sys;d=json.load(sys.stdin);print('[mac] r79 health:', d['status'])"

if ! curl -s -m 2 "http://127.0.0.1:${HARNESS_PORT}/api/status" >/dev/null 2>&1; then
  echo "[mac] starting harness on 127.0.0.1:${HARNESS_PORT} (real mode) ..."
  (cd "${PROJECT_ROOT}/harness" && \
    nohup env HARNESS_REQUEST_TIMEOUT=2400 .venv/bin/python -m uvicorn app.main:app \
      --host 127.0.0.1 --port "${HARNESS_PORT}" > /tmp/r79_mac_harness.log 2>&1 &)
  sleep 4
fi
curl -s -m 5 "http://127.0.0.1:${HARNESS_PORT}/api/status" | python3 -c \
  "import json,sys;d=json.load(sys.stdin);print('[mac] harness mock:', d['mock'])"

echo "[mac] done. open http://127.0.0.1:${HARNESS_PORT}/"
