#!/usr/bin/env bash
# 行政复议智能助手 Harness 启动脚本(macOS/Linux)
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "未检测到 .venv,正在创建虚拟环境并安装依赖……"
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

HOST="${HARNESS_HOST:-127.0.0.1}"
PORT="${HARNESS_PORT:-8090}"

echo "正在启动行政复议智能助手 Harness: http://${HOST}:${PORT}"
if [ "${HARNESS_MOCK:-}" = "1" ]; then
  echo "当前为演示模式(HARNESS_MOCK=1),不会连接真实推理服务。"
else
  echo "将连接推理服务 ${R79_API_BASE:-http://127.0.0.1:8088}(未启动时可改用 HARNESS_MOCK=1)。"
fi

exec .venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$PORT"
