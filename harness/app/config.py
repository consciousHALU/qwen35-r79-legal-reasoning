"""Harness 配置:仅环境变量,无外部依赖,默认全部绑定回环地址。"""
from __future__ import annotations

import os

# R79 推理 API 地址(start_api.sh 启动,默认 8088)
R79_API_BASE: str = os.environ.get("R79_API_BASE", "http://127.0.0.1:8088").rstrip("/")

# Harness 自身监听地址与端口(只绑定回环,与推理框架一致)
HARNESS_HOST: str = os.environ.get("HARNESS_HOST", "127.0.0.1")
HARNESS_PORT: int = int(os.environ.get("HARNESS_PORT", "8090"))

# 推理单次工作流在 GPU 上可达分钟级;给足超时
REQUEST_TIMEOUT: float = float(os.environ.get("HARNESS_REQUEST_TIMEOUT", "660"))

# 演示模式:不连接真实后端,由内置模拟器返回结构化样例数据
HARNESS_MOCK: bool = os.environ.get("HARNESS_MOCK", "").lower() in {"1", "true", "yes", "on"}

# 生成的 docx 临时保存目录(内存令牌 + 临时文件,下载后即清理)
DRAFT_TTL_SECONDS: int = int(os.environ.get("HARNESS_DRAFT_TTL", "3600"))
