# 行政复议智能助手 Harness 启动脚本(Windows PowerShell)
$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "未检测到 .venv,正在创建虚拟环境并安装依赖……"
    python -m venv .venv
    .\.venv\Scripts\pip.exe install -q -r requirements.txt
}

$HostAddr = if ($env:HARNESS_HOST) { $env:HARNESS_HOST } else { "127.0.0.1" }
$Port = if ($env:HARNESS_PORT) { $env:HARNESS_PORT } else { "8090" }

Write-Host "正在启动行政复议智能助手 Harness: http://${HostAddr}:${Port}"
if ($env:HARNESS_MOCK -eq "1") {
    Write-Host "当前为演示模式(HARNESS_MOCK=1),不会连接真实推理服务。"
} else {
    $R79 = if ($env:R79_API_BASE) { $env:R79_API_BASE } else { "http://127.0.0.1:8088" }
    Write-Host "将连接推理服务 $R79(未启动时可改用 HARNESS_MOCK=1)。"
}

.\.venv\Scripts\python.exe -m uvicorn app.main:app --host $HostAddr --port $Port
