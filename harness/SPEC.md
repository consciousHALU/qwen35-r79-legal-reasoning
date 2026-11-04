# Harness 开发契约(后端/前端/文案共同遵守)

## 定位

`harness/` 是 qwen35-r79-legal-reasoning(本地推理 API,默认 `http://127.0.0.1:8088`)的 Web 壳,
面向三大场景:① 行政案件问题咨询 ② 行政案件证据链梳理 ③ 行政复议文书起草。
中文界面,全部本地回环运行,不上传任何数据;不依赖任何 CDN/外网资源。

## 技术栈

- Python 3.11+;后端 FastAPI + httpx + python-docx;前端原生 HTML/CSS/JS(无构建步骤)。
- 依赖清单一律写进 `harness/requirements.txt`:fastapi、uvicorn、httpx、python-docx、pytest。
- 后端包根:`harness/app/`;前端静态文件:`harness/app/static/`(index.html / app.css / app.js)。
- 运行入口(在 harness/ 目录下):`python -m uvicorn app.main:app --host 127.0.0.1 --port 8090`;
  另提供 `run.sh` / `run.ps1`;模拟后端:`HARNESS_MOCK=1` 环境变量,或 `python -m app.mock_r79`(独立在 8088 起模拟 R79 API)。

## 已有文件(不要改动)

- `harness/app/__init__.py`、`harness/app/config.py`(配置:R79_API_BASE/HARNESS_HOST/HARNESS_PORT/REQUEST_TIMEOUT/HARNESS_MOCK/DRAFT_TTL_SECONDS)
- `harness/app/sample_case.py`(示例案件 + `build_mock_assist()` 模拟推理响应 + `MOCK_WIKI_RESULT`)

## R79 后端 API(真实端,8088)

- `GET /health` → `{"status":"ok|degraded","wiki_available":bool,"routes":[...],...}`
- `POST /v1/legal/assist` 入参 `{"user_request":str,"raw_materials":[{"title":str,"text":str}]}`
  出参:`{"workflow_id","backend_generation_requests","tokenizer_preflights","routing":{...},
  "selected_graphs":[...],"facts":{actors,events,evidence,uncertainties},
  "procedure":{actors,decision_maker_actor_id,challenged_action,steps,deadlines,unknowns},
  "deterministic_normalization":{...},"answer":{conclusion,analysis,claims,limitations}}`
- `POST /v1/wiki/similar-case/search` 入参 `{"query":str}` → `{"mode":"retrieval_only","result":null|{source_id,title,full_original,...}}`
- facts.events 元素:`event_id, actor_ids[], action, object, date_text, date_status(exact|partial|unknown), evidence_status(proved|asserted|contradicted|unknown), source_refs[]`
- facts.evidence 元素:`evidence_id, description, supports_event_ids[], status, source_refs[]`
- facts.actors 元素:`actor_id, name_as_stated, role, evidence_status, source_refs[]`
- procedure.steps 元素:`step_id, actor_id, action, date_text, date_status, evidence_status, source_refs[]`
- procedure.deadlines 元素:`description, start_date, end_date, date_status, source_refs[]`
- answer.claims 元素:`claim, source_refs[], graph_refs[], evidence_status`

## Harness 自身 API(后端实现、前端调用,端口 8090)

1. `GET /` → 返回 static/index.html;/static/* 静态资源。
2. `GET /api/status` → `{"harness":"ok","mock":bool,"backend":<透传 8088 /health>|{"reachable":false,"error":str}}`
3. `GET /api/sample-case` → `{"question":str,"materials":[{"title","text"}],"overrides":{...}}`(来自 sample_case)
4. `POST /api/consult` 入参 `{"question":str,"materials":[...],"search_wiki":bool}`
   → `{"assist":<r79原始响应>,"wiki":<wiki原始响应|null>,"meta":{"workflow_id","backend_generation_requests","routing"}}`
5. `POST /api/evidence-chain` 入参 `{"materials":[...],"question":str(可选,有默认值)}`
   → `{"assist":<原始>,"chain":{...见下},"report_markdown":str}`
   chain = `{actors, timeline, evidence, matrix, uncertainties, procedure_steps, deadlines, stats}`
   - timeline:事件按日期排序(exact 解析日期升序 → partial → unknown),每项 `{event_id,date_text,date_status,action,object,actor_names[],evidence_status,source_refs[]}`
   - matrix:`{"event_ids":[...],"evidence_ids":[...],"cells":[[bool,...],...]}`(行=事件,列=证据,cell=该证据是否支持该事件)
   - stats:`{"actors":n,"events":n,"evidence":n,"uncertainties":n,"contradicted":n,"unknown":n}`
6. `POST /api/draft` 入参 `{"materials":[...],"overrides":{"applicant_name":"","review_organ":"","claims_text":"","third_party":""}}`
   → `{"assist":<原始>,"document_markdown":str,"review_notes":[str,...],"docx_token":str}`
   `GET /api/draft/download/{docx_token}` → `application/vnd.openxmlformats-officedocument.wordprocessingml.document`,文件名 `行政复议申请书.docx`;令牌内存保存,1 小时过期。
7. 错误约定:用户输入缺失 → 400;后端不可达 → 503;后端 5xx → 502;响应体一律 `{"detail":"中文友好说明"}`。

## 三大场景的用户请求文案(发给 R79 的 user_request,后端内置默认值)

- 咨询:用户自填问题。
- 证据链:`请梳理本案的主体、事件经过、日期与证据状态,逐一列明每份证据支持的事实、证据之间的矛盾以及尚无法确认的事项。`
- 文书:`请分析该行政行为的主体、程序与法律适用,评估其合法性与合理性,为起草行政复议申请书提供依据。`

## 文书起草(drafting)规则

文书 = 模型结构化分析 + 确定性模板组装(不得再调用模型自由生成)。
结构:标题「行政复议申请书」→ 申请人(overrides.applicant_name 优先,否则从 facts/procedure 中 role 含“申请人”的 actor;缺失写【待补充:申请人姓名】)→ 被申请人(procedure.decision_maker 对应 actor 名称)→ 第三人(overrides 或省略)→ 复议请求(overrides.claims_text 优先,否则由 challenged_action 描述推导“请求撤销/变更……”)→ 事实和理由(一、基本事实=事件时间线叙述;二、程序情况=steps/deadlines;三、理由=answer.claims+conclusion+analysis)→ 证据目录(facts.evidence 编号列表)→ 此致 {review_organ 或【待补充:复议机关名称】} → 申请人签名/日期【待补充】。
review_notes:列出所有【待补充】项与 answer.limitations,提示“AI 辅助生成,须经人工核对”。
docx 排版:标题二号方正小标宋/黑体居中;正文三号仿宋,首行缩进 2 字符,1.5 倍行距;中文字体须设置 w:eastAsia。

## 前端要求

- 单页三标签页:案件咨询 / 证据链梳理 / 文书起草;页头含产品名「行政复议智能助手」与后端状态徽标
  (绿=已连接模型服务,黄=演示模式 mock=true,红=未连接,30s 轮询 /api/status)。
- 三页共用“案件材料编辑器”(JS 组件):材料卡片列表(标题+正文+删除),“添加材料”“从文件导入(.txt/.md)”
  “载入示例案件”(GET /api/sample-case)。
- 请求时显示加载动画与已用秒数;失败展示 detail。
- 咨询页:问题输入框 + “同时检索类案(只读,不注入推理)”复选框;结果区:结论卡、分析、主张列表
  (claim + 证据状态色块 + source_refs 角标)、局限、类案卡(若有)、审计信息(workflow_id、生成请求数、路由)。
- 证据链页:统计色块行、事件时间轴(竖向,按状态着色)、证据×事件支持矩阵表、主体表、程序步骤与期限、
  矛盾与未知列表、“导出梳理报告(.md)”按钮(report_markdown → Blob 下载)。
- 文书页:可选信息表单(申请人/复议机关/复议请求/第三人)→ 生成后显示文书预览(等宽换行)+
  审核提示列表 +「下载 .docx」「下载 .md」「复制全文」。
- 证据状态配色:proved=绿,asserted=蓝,contradicted=红,unknown=灰;date_status:exact 实色,partial 半透,unknown 虚线框。
- 风格:政务蓝(#2456a6)主色,白底卡片,圆角 8px,system-ui/"PingFang SC"/"Microsoft YaHei";禁止任何外部资源。

## 测试(harness/tests/test_harness.py)

mock 模式(HARNESS_MOCK=1)下用 fastapi.testclient.TestClient:
status 200 且 mock=true;consult 返回 meta.workflow_id;evidence-chain 的 matrix 与 evidence.supports_event_ids 一致;
draft 的 document_markdown 含「行政复议申请书」「此致」且缺少 overrides 时出现【待补充】;docx 下载 200;
question 为空 → 400。另测 `app.mock_r79` 模块可导入且其 app 对象存在。
