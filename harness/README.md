# 行政复议智能助手 Harness

`harness/` 是 R79 推理框架(qwen35-r79-legal-reasoning,本地推理 API,默认 `http://127.0.0.1:8088`)的 Web 壳。它不改动模型与推理管线,只把后端能力包装成中文浏览器界面,面向行政复议办理中的三个高频场景。中文界面,全部本地回环运行,不上传任何数据,也不依赖任何 CDN/外网资源。

> 接口与实现契约见 [SPEC.md](SPEC.md)。

## 三大功能

**① 案件咨询。** 用户录入案件材料并提出问题(例如"该行政处罚决定是否合法、复议期限从何时起算"),harness 把完整问题与全部原始材料一并提交 R79 工作流,返回结构化结论、逐条分析、主张列表(每条主张带证据状态与原始材料段落引用)以及局限说明。可选勾选"同时检索类案":类案 Wiki 是独立检索端点,只返回最相关的一份完整原文,只读展示,**不注入推理**。

**② 证据链梳理。** 一键把卷宗材料整理为可核验的证据链视图:主体表、按日期排序的事件时间轴、证据 × 事件支持矩阵、程序步骤与期限、矛盾与未知事项清单,并附统计概览(主体/事件/证据/矛盾/未知数量)。所有条目都带 `M001:P0003` 式的来源锚点,可回查原始材料段落;支持一键导出 Markdown 梳理报告。

**③ 复议文书起草。** 文书 = 模型结构化分析 + 确定性模板组装,**不再调用模型自由生成**。在模型产出的事实、程序与法律适用分析之上,由模板确定性拼装《行政复议申请书》:申请人、被申请人、复议请求、事实和理由、证据目录、此致复议机关依次成文;缺失信息一律标注【待补充】,并生成审核提示清单。支持在线预览、复制全文,以及下载按公文样式排版的 `.docx`(标题二号方正小标宋/黑体居中,正文三号仿宋、首行缩进 2 字符、1.5 倍行距)。

## 架构

```text
┌──────────┐   HTTP    ┌──────────────────┐   HTTP    ┌─────────────────┐   HTTP    ┌─────────────┐
│  浏览器   │ ◄──────► │  harness(8090)   │ ◄──────► │  R79 API(8088)  │ ◄──────► │ vLLM(8000)  │
│ 三标签页  │  回环     │ FastAPI + 静态页  │  回环     │ 路由/审计/图谱   │  回环     │ FP8 + LoRA  │
└──────────┘           └──────────────────┘           └─────────────────┘           └─────────────┘
   原生 HTML/CSS/JS        只绑定 127.0.0.1              只绑定 127.0.0.1              Qwen3.5-9B FP8
   无构建步骤、无 CDN       透传 /health · 代理三大场景     三 LoRA 显式路由              facts_1949
                                                      类案 Wiki 检索隔离             procedure_1978
                                                                                    candidate_r79
```

浏览器到模型之间的每一跳都只走 `127.0.0.1` 回环地址,数据不出本机。

## 快速开始

### 前置条件

- Python 3.11+;
- 模型仓库已按主仓 [docs/MODEL_ACCESS.md](../docs/MODEL_ACCESS.md) 获批、下载并完成部署,即 `scripts/start_backend.sh`(vLLM,8000)与 `scripts/start_api.sh`(R79 API,8088)已在运行;可用 `curl http://127.0.0.1:8088/health` 确认;
- 安装 harness 依赖:

```bash
cd harness
pip install -r requirements.txt   # fastapi / uvicorn / httpx / python-docx / pytest
```

### 真实模式(连接 8088 真实推理)

```bash
cd harness
./run.sh        # 等价于 python -m uvicorn app.main:app --host 127.0.0.1 --port 8090
```

打开 `http://127.0.0.1:8090`,页头状态徽标为绿色即已连接模型服务。Windows 使用 `run.ps1`。

### 演示模式(无 GPU、无后端也能完整走通界面)

```bash
cd harness
HARNESS_MOCK=1 ./run.sh
```

演示模式下由内置模拟器返回与真实 `/v1/legal/assist` 结构完全一致的合成样例数据(张某不服测速处罚复议案,全部虚构),页头徽标显示黄色"演示模式"。响应中带 `mock_notice`,不会调用真实模型。

### 独立模拟后端(在 8088 端口模拟 R79 API)

用于联调 harness 真实模式代码路径,但不依赖 GPU:

```bash
cd harness
python -m app.mock_r79   # 在 127.0.0.1:8088 起模拟 R79 API,随后以真实模式启动 harness
```

## 目录结构

```text
harness/
├── SPEC.md               # 开发契约(后端/前端/文案共同遵守)
├── README.md             # 本文件
├── requirements.txt      # fastapi、uvicorn、httpx、python-docx、pytest
├── run.sh / run.ps1      # 启动入口
├── app/
│   ├── __init__.py
│   ├── config.py         # 全部配置仅环境变量
│   ├── sample_case.py    # 内置合成示例案件 + 模拟推理响应 + 模拟类案
│   ├── main.py           # FastAPI 应用(/api/status、consult、evidence-chain、draft 等)
│   ├── mock_r79.py       # 独立模拟 R79 后端(8088)
│   ├── drafting.py       # 确定性文书模板组装 + docx 排版
│   └── static/           # index.html / app.css / app.js(原生前端,无构建)
├── tests/
│   └── test_harness.py   # mock 模式下的端到端契约测试
└── docs/
    └── 使用说明.md        # 面向最终用户的操作手册
```

## 配置项

全部配置均为环境变量,定义见 `app/config.py`,默认全部绑定回环地址:

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `R79_API_BASE` | `http://127.0.0.1:8088` | R79 推理 API 地址(由主仓 `start_api.sh` 启动) |
| `HARNESS_HOST` | `127.0.0.1` | harness 自身监听地址,只绑定回环 |
| `HARNESS_PORT` | `8090` | harness 自身监听端口 |
| `HARNESS_REQUEST_TIMEOUT` | `660` | 转发推理请求的超时(秒);单次工作流在 GPU 上可达分钟级,给足超时 |
| `HARNESS_MOCK` | 空(关) | 设为 `1/true/yes/on` 进入演示模式,由内置模拟器应答 |
| `HARNESS_DRAFT_TTL` | `3600` | 生成的 docx 下载令牌有效期(秒),内存保存、过期失效 |

## 测试

```bash
cd harness
HARNESS_MOCK=1 pytest
```

测试在演示模式下用 `fastapi.testclient.TestClient` 走完整契约:状态接口 200 且 `mock=true`;咨询返回 `meta.workflow_id`;证据链矩阵与 `evidence.supports_event_ids` 一致;文书 Markdown 含「行政复议申请书」「此致」,缺少可选信息时出现【待补充】;docx 下载 200;问题为空返回 400;另验证 `app.mock_r79` 模块可导入且其 app 对象存在。

## 数据安全与合规

- **只绑定回环**:harness(8090)、R79 API(8088)、vLLM(8000)默认均只监听 `127.0.0.1`,案件材料不出本机;
- **不上传数据**:前端不依赖任何 CDN/外网资源,没有任何外发通道;
- **审计最小化**:R79 侧默认审计模式为 `hashes`,只落盘请求/响应哈希、路由、token 和状态,不保存原始法律材料或私有草稿;显式设置 `R79_AUDIT_MODE=full` 才做完整本地审计,且这些文件含敏感材料,只应保存在受控目录,API 永不返回;
- **检索隔离**:类案 Wiki 端点与推理端点严格分离,检索结果只读展示,不会自动进入模型上下文;
- **人工复核**:所有 AI 输出均为辅助性质,页面与文书均带"AI 辅助生成,须经人工核对"提示,正式使用前必须由具备资质的人员复核。

## 许可证

与主仓库一致,按 Apache-2.0 发布,见主仓 [LICENSE](../LICENSE) 与 [NOTICE](../NOTICE)。
