# Qwen3.5 R79 Legal Reasoning

一个可审计、可本地运行的研究型行政法律推理框架。它使用同一个 Qwen3.5-9B FP8 基模，并按任务显式路由三个独立 FP16 LoRA：

- `facts_1949`：主体、事件、日期和证据状态整理；
- `procedure_1978`：行政行为作出者、程序步骤与期限；
- `candidate_r79`：法律适用和最终回答；
- 外挂知识图谱：本地确定性检索，不调用模型，也不作为本案事实；
- 类案 Wiki：独立检索端点，只返回最相关的一份完整原文，不注入推理。

模型下载（需邀请码并经 Hugging Face 账号审批）：[xujianing1990/qwen3.5-9b-fp8-1949-1978-r79-public](https://huggingface.co/xujianing1990/qwen3.5-9b-fp8-1949-1978-r79-public)。邀请码和完整申请步骤见 [模型访问说明](docs/MODEL_ACCESS.md)。

> 这是研究预览，不是法律意见、专家金标或生产质量承诺。输出必须由合格人员复核。

## 开箱运行

要求：Python 3.11+、Linux/WSL2、支持当前 vLLM 的 NVIDIA GPU。已验证的组合是 vLLM 0.27.1、MTP3、FP8 基模和三个 FP16 LoRA。

```bash
git clone https://github.com/consciousHALU/qwen35-r79-legal-reasoning.git
cd qwen35-r79-legal-reasoning
python -m venv .venv
source .venv/bin/activate
pip install -e .

# 在Linux/WSL的GPU环境安装经验证的后端版本
pip install -r requirements-backend.txt

# 先按 docs/MODEL_ACCESS.md 获批并运行 hf auth login；随后下载到本地缓存目录
r79-legal download-model

# 可选：用合成数据启用类案检索演示
mkdir -p runtime
r79-legal build-wiki \
  --input data/wiki_demo.jsonl \
  --output runtime/wiki.sqlite3 \
  --privacy-reviewed --rights-confirmed

# 终端 1：FP8 + 1949/1978/R79 + MTP3
bash scripts/start_backend.sh

# 终端 2：本地 API
bash scripts/start_api.sh
```

以上步骤也可用 `bash scripts/bootstrap.sh` 一次完成依赖、模型下载和合成 Wiki 演示索引准备。Windows PowerShell 可运行 `scripts/bootstrap.ps1`；脚本会输出对应的 WSL 模型路径与启动命令。

检查：

```bash
curl http://127.0.0.1:8088/health
```

完整推理：

```bash
curl -s http://127.0.0.1:8088/v1/legal/assist \
  -H 'content-type: application/json' \
  -d '{
    "user_request":"请分析该行政行为的主体、程序和适用条件。",
    "raw_materials":[
      {"title":"申请材料","text":"这里放完整原始材料，不要先行摘要。"}
    ]
  }'
```

类案检索（只返回原文、不参与推理）：

```bash
curl -s http://127.0.0.1:8088/v1/wiki/similar-case/search \
  -H 'content-type: application/json' \
  -d '{"query":"送达日期不明时如何审查期限"}'
```

## Mac 本地适配（无 NVIDIA GPU）

在 Apple Silicon 上可用 [vllm-metal](https://github.com/waybarrios/vllm-metal)（MLX 后端）跑通完整推理链路。此时不加载 LoRA 适配器，三个路由名经 `--served-model-name` 别名指向同一 MLX 基模，**用于验证流程与演示交互，输出为未微调基模水平**；参评性能指标仍以 FP8 + 三适配器的 NVIDIA 整栈为准。

```bash
# 终端 1:vllm-metal 以四个别名服务同一基模
vllm serve --model <mlx-模型路径> \
  --served-model-name qwen3.5-9b facts_1949 procedure_1978 candidate_r79 \
  --max-model-len 32768 --mamba-ssm-cache-dtype float32 \
  --reasoning-parser qwen3 \
  --default-chat-template-kwargs '{"enable_thinking": false}' \
  --host 127.0.0.1 --port 8000

# 终端 2:R79 API + Harness(一条命令)
bash scripts/start_local_mac.sh
```

Mac 适配由环境变量完成，不改变默认（NVIDIA）行为：

| 变量 | Mac 值 | 默认 | 原因 |
| --- | --- | --- | --- |
| `R79_DRAFT_THINKING` | `0` | `1` | 未加载适配器的基模思考通道不收敛，草稿会耗尽 token 预算（finish_reason=length)；关闭后模型直接输出核验清单 |
| `R79_MAX_MODEL_LEN` | `32768` | 取 `routes.json`(16384) | 与本地 vllm-metal 实际上下文对齐，预检预算按真实上限计算 |
| `R79_REASONING_BUDGET` / `R79_FINAL_BUDGET` | `8192` / `6144` | `8192` / `8192` | 按 MLX 吞吐（约 40 tok/s）控制单阶段时延 |
| `HARNESS_REQUEST_TIMEOUT` | `2400` | `660` | Mac 上完整三阶段工作流约 2-6 分钟，harness 等待放宽 |

另外，`client.py` 兼容 vllm-metal 将思考内容放在 `reasoning` 字段（标准 vLLM 为 `reasoning_content`）的差异；两种字段名都被接受。

## 推理流程

```text
完整用户请求 + 全部原始材料
       ├─ facts_1949 ────── 主体/事件/日期/证据状态
       ├─ procedure_1978 ── 行为作出者/步骤/期限
       └─ 本地图谱检索 ─── 最多3个抽象条件图
                    ↓
              candidate_r79
                    ↓
        结论 + 分析 + 引用 + 局限
```

三个语义阶段都使用两段式生成：先开启 thinking 生成有界私有草稿，再由同一 adapter 在温度 0 下生成严格 JSON 定稿。每次生成前都调用后端 tokenizer 做真实上下文预算检查，超限会在生成前明确拒绝且绝不截断原文。一次工作流固定 3 个逻辑调用、6 个原生生成请求和 6 次 tokenizer 预检，低于 8 个并发生成请求上限。

默认审计模式为 `hashes`，只落盘请求/响应哈希、路由、token和状态，不保存原始法律材料或私有草稿。需要完整本地审计时显式设置 `R79_AUDIT_MODE=full`；这些文件含敏感材料和私有 thinking，只应保存在受控目录，API 永不返回。也可用 `R79_AUDIT_MODE=off` 关闭落盘。

详细设计见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，评测结果见 [docs/EVALUATION.md](docs/EVALUATION.md)。
实际后端兼容记录见 [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md)。

## Web 界面(Harness)

`harness/` 是本框架的 Web 壳(行政复议智能助手),把本地推理 API 包装为中文浏览器界面,面向三个场景:案件咨询、证据链梳理(时间轴 + 证据×事件矩阵)、行政复议文书起草(结构化分析 + 确定性模板组装,导出 docx)。它不改、不包装、不代理模型权重,只调用 `127.0.0.1:8088` 的本地 API;另内置演示模式(`HARNESS_MOCK=1`,合成数据,无需 GPU)便于评审与测试。详见 [harness/README.md](harness/README.md)。

## 数据边界

仓库带有 1,030 条仅含抽象条件、规则、推导关系和迁移边界的公开图谱；内部案件身份、逐段原文引句、路径和 private provenance 已全部剥离。

原内部 Wiki 的 4,382 份全文材料含身份证、电话、账号、地址等个人信息，且缺少逐来源公开再分发许可清单，因此**没有上传到公开仓库**。仓库提供同一检索接口、合成演示数据和本地索引构建器；只有在你完成隐私审阅并确认再分发权利后，才可导入自己的语料。见 [docs/DATA.md](docs/DATA.md)。

## 路由与限制

- 活跃权重仅为 1949、1978、R79；不加载退役的 2008，也不包含 2026。
- 图谱只提供抽象推理逻辑，不能替代本案事实、现行法核验或专业复核。
- Wiki 端点和推理端点严格分离，Wiki 结果不会自动进入模型上下文。
- 所有服务默认只绑定 `127.0.0.1`。
- 进程内共享信号量把模型后端并发硬限制为最多 8；可用 `R79_MAX_CONCURRENT_BACKEND` 调低，不能调高。
- 不包含训练、权重合并、自动部署或自动采纳输出。

## 开发验证

```bash
pip install -e '.[dev]'
pytest
python scripts/build_public_graph.py \
  --input data/public_patterns.jsonl \
  --output /tmp/graph.sqlite3
```

## 许可证

代码与随仓抽象图谱按 Apache-2.0 发布。模型仓库沿用 Qwen3.5 的 Apache-2.0 许可与模型卡限制。你导入的 Wiki 语料仍受其各自来源、隐私和再分发条件约束。
