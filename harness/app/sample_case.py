"""示例案件与模拟推理响应(演示/测试用,全部为虚构合成数据)。

材料文本按行分段,与 R79 工作流的 source_catalog 段落编号规则一致
(M001 = 第 1 份材料,P0001 = 该材料第 1 行),因此以下 source_refs 均为真实可核验的引用。
"""
from __future__ import annotations

import uuid

SAMPLE_MATERIALS: list[dict[str, str]] = [
    {
        "title": "行政处罚决定书(公交决字〔2026〕第0315号)",
        "text": """某县公安局交通管理大队 公安交通管理行政处罚决定书 公交决字〔2026〕第0315号
被处罚人:张某,男,1985年6月10日出生,住某县幸福路12号,系桂D12345轻型普通货车驾驶人。
现查明:2026年3月15日14时20分,张某驾驶桂D12345轻型普通货车行至S304省道12公里600米处时,经固定测速设备(编号CS-07)记录,行驶速度为78公里/小时,该路段限速60公里/小时。
以上事实有测速记录、现场照片等证据证明。
本大队认为,张某的行为违反了《中华人民共和国道路交通安全法》第四十二条之规定,依据该法第九十条,决定给予张某罚款1000元的行政处罚,并记6分。
本决定书于2026年3月18日作出。经办民警:王某、李某。加盖某县公安局交通管理大队印章。""",
    },
    {
        "title": "送达情况说明",
        "text": """某县公安局交通管理大队于2026年3月20日将公交决字〔2026〕第0315号行政处罚决定书送至张某工作单位某县顺达物流有限公司,由该公司门卫陈某签收。
张某2026年3月15日至3月22日在外地出差,2026年3月23日返回单位后从陈某处取得该决定书。""",
    },
    {
        "title": "张某陈述申辩书",
        "text": """申请人张某认为:一、编号CS-07测速设备自2025年6月投入使用,被申请人未出示该设备在有效期内的检定合格证书,测速数据真实性存疑。
二、处罚决定书未直接送达本人,由门卫代收,申请人直至2026年3月23日才知悉处罚内容,复议申请期限应自该日起算。
三、申请人当日系为避让前方突然变道的客车而瞬时加速,具有紧急避险情节。""",
    },
    {
        "title": "测速记录打印件",
        "text": """设备编号:CS-07;记录时间:2026年3月15日14时20分;地点:S304省道12公里600米;记录速度:78km/h;限速:60km/h。
附抓拍照片两张(照片可见桂D12345车辆及测速点标志)。
本打印件未见设备检定合格标志或检定证书编号。""",
    },
]

SAMPLE_QUESTION = (
    "测速设备未见检定证书、处罚决定书由门卫代收,本案处罚决定是否合法?"
    "复议申请期限从何时起算?"
)

SAMPLE_OVERRIDES = {
    "applicant_name": "张某",
    "review_organ": "某县人民政府",
    "claims_text": "",
    "third_party": "",
}

_MOCK_FACTS = {
    "actors": [
        {"actor_id": "A001", "name_as_stated": "张某", "role": "申请人(被处罚人)",
         "evidence_status": "asserted", "source_refs": ["M001:P0002", "M003:P0001"]},
        {"actor_id": "A002", "name_as_stated": "某县公安局交通管理大队",
         "role": "被申请人(处罚决定作出机关)", "evidence_status": "proved",
         "source_refs": ["M001:P0001", "M001:P0006"]},
        {"actor_id": "A003", "name_as_stated": "王某", "role": "经办民警",
         "evidence_status": "proved", "source_refs": ["M001:P0006"]},
        {"actor_id": "A004", "name_as_stated": "李某", "role": "经办民警",
         "evidence_status": "proved", "source_refs": ["M001:P0006"]},
        {"actor_id": "A005", "name_as_stated": "陈某", "role": "文书代收人(申请人单位门卫)",
         "evidence_status": "asserted", "source_refs": ["M002:P0001"]},
    ],
    "events": [
        {"event_id": "E001", "actor_ids": ["A001"],
         "action": "驾驶桂D12345货车超速行驶(记录时速78km/h,限速60km/h)",
         "object": "S304省道12公里600米", "date_text": "2026年3月15日14时20分",
         "date_status": "exact", "evidence_status": "proved",
         "source_refs": ["M001:P0003", "M004:P0001"]},
        {"event_id": "E002", "actor_ids": ["A002"],
         "action": "作出公交决字〔2026〕第0315号行政处罚决定(罚款1000元并记6分)",
         "object": "张某", "date_text": "2026年3月18日", "date_status": "exact",
         "evidence_status": "proved", "source_refs": ["M001:P0005", "M001:P0006"]},
        {"event_id": "E003", "actor_ids": ["A002", "A005"],
         "action": "向申请人单位送达处罚决定书,由门卫陈某签收",
         "object": "某县顺达物流有限公司", "date_text": "2026年3月20日",
         "date_status": "exact", "evidence_status": "asserted",
         "source_refs": ["M002:P0001"]},
        {"event_id": "E004", "actor_ids": ["A001"],
         "action": "出差返回后从陈某处取得决定书,实际知悉处罚内容",
         "object": "行政处罚决定书", "date_text": "2026年3月23日",
         "date_status": "exact", "evidence_status": "asserted",
         "source_refs": ["M002:P0002", "M003:P0002"]},
    ],
    "evidence": [
        {"evidence_id": "EV001", "description": "行政处罚决定书(公交决字〔2026〕第0315号)",
         "supports_event_ids": ["E001", "E002"], "status": "proved",
         "source_refs": ["M001:P0001"]},
        {"evidence_id": "EV002", "description": "测速记录打印件及抓拍照片两张",
         "supports_event_ids": ["E001"], "status": "proved",
         "source_refs": ["M004:P0001", "M004:P0002"]},
        {"evidence_id": "EV003", "description": "送达情况说明(门卫陈某代收)",
         "supports_event_ids": ["E003", "E004"], "status": "asserted",
         "source_refs": ["M002:P0001"]},
        {"evidence_id": "EV004", "description": "张某陈述申辩书",
         "supports_event_ids": ["E004"], "status": "asserted",
         "source_refs": ["M003:P0001"]},
        {"evidence_id": "EV005",
         "description": "CS-07测速设备有效期内的检定合格证书(卷内未见)",
         "supports_event_ids": [], "status": "unknown",
         "source_refs": ["M003:P0001", "M004:P0003"]},
    ],
    "uncertainties": [
        {"field": "测速设备检定状态",
         "reason": "卷内未见CS-07设备的检定合格证书或检定标志,无法确认测速数据的合法性。",
         "source_refs": ["M003:P0001", "M004:P0003"]},
        {"field": "送达程序合法性",
         "reason": "决定书由单位门卫代收而非直接送达本人,是否符合法定送达方式需进一步核实。",
         "source_refs": ["M002:P0001"]},
    ],
}

_MOCK_PROCEDURE = {
    "actors": [
        {"actor_id": "A001", "name_as_stated": "张某", "role": "申请人",
         "evidence_status": "asserted", "source_refs": ["M003:P0001"]},
        {"actor_id": "A002", "name_as_stated": "某县公安局交通管理大队",
         "role": "被申请人(行政行为作出机关)", "evidence_status": "proved",
         "source_refs": ["M001:P0001", "M001:P0006"]},
    ],
    "decision_maker_actor_id": "A002",
    "challenged_action": {
        "event_id": "E002", "actor_id": "A002",
        "description": "公交决字〔2026〕第0315号行政处罚决定(罚款1000元并记6分)",
        "evidence_status": "proved", "source_refs": ["M001:P0005"],
    },
    "steps": [
        {"step_id": "S001", "actor_id": "A002", "action": "固定测速设备记录超速行为",
         "date_text": "2026年3月15日14时20分", "date_status": "exact",
         "evidence_status": "proved", "source_refs": ["M004:P0001"]},
        {"step_id": "S002", "actor_id": "A002", "action": "作出行政处罚决定",
         "date_text": "2026年3月18日", "date_status": "exact",
         "evidence_status": "proved", "source_refs": ["M001:P0006"]},
        {"step_id": "S003", "actor_id": "A002", "action": "向申请人单位送达决定书(门卫代收)",
         "date_text": "2026年3月20日", "date_status": "exact",
         "evidence_status": "asserted", "source_refs": ["M002:P0001"]},
    ],
    "deadlines": [
        {"description": "行政复议申请期限(自知道行政行为之日起六十日内)",
         "start_date": "2026年3月23日(申请人主张的实际知悉日)",
         "end_date": "2026年5月22日前后(取决于起算日认定)", "date_status": "partial",
         "source_refs": ["M002:P0002", "M003:P0002"]},
    ],
    "unknowns": [
        {"field": "处罚前告知程序",
         "reason": "卷内材料未显示作出处罚决定前是否依法告知申请人陈述、申辩权。",
         "source_refs": ["M001:P0005"]},
    ],
}

_MOCK_ANSWER = {
    "conclusion": (
        "本案处罚决定在事实认定上有测速记录和现场照片支持,但存在两项需重点审查的程序事项:"
        "一是处罚决定书由单位门卫代收、未直接送达本人,送达程序的合法性存疑;"
        "二是卷内未见CS-07测速设备有效期内的检定合格证书,测速数据的证据能力待核实。"
        "建议以程序瑕疵为主要复议理由,并可请求复议机关责令被申请人补充提交检定证明。"
    ),
    "analysis": (
        "一、事实认定方面。超速行为有CS-07测速设备记录及两张抓拍照片印证,"
        "车速78km/h、限速60km/h的记录内容具体明确,事实认定基础较为充分。\n"
        "二、证据能力方面。依据计量监管相关规定,用于执法取证的测速设备应当经检定合格并在有效期内。"
        "本案卷内未见该设备的检定合格证书或标志,申请人亦明确提出异议,"
        "若被申请人不能补充提交有效检定证明,测速记录的证明力将受到实质影响。\n"
        "三、程序方面。处罚决定书由申请人所在单位门卫代收,申请人主张因出差直至2026年3月23日才实际知悉处罚内容。"
        "代收是否构成合法送达直接影响复议申请期限的起算日:若认定2026年3月20日送达有效,期限自该日起算;"
        "若认定送达不合法,则应自3月23日申请人实际知悉之日起算。\n"
        "四、申请人主张的紧急避险情节目前仅有本人陈述,缺乏行车记录仪、证人证言等其他证据印证,证明力较弱。"
    ),
    "claims": [
        {"claim": "被申请人某县公安局交通管理大队具有作出本案交通管理行政处罚的职权,"
                  "决定书加盖其印章并由两名经办民警签名。",
         "source_refs": ["M001:P0001", "M001:P0006"], "graph_refs": [],
         "evidence_status": "proved"},
        {"claim": "超速事实有测速记录及抓拍照片证明,但测速设备检定合格证书未在卷,"
                  "测速数据的证明力存在合理疑问。",
         "source_refs": ["M004:P0001", "M004:P0003"], "graph_refs": [],
         "evidence_status": "asserted"},
        {"claim": "处罚决定书由申请人单位门卫代收,申请人主张2026年3月23日才实际知悉处罚内容,"
                  "送达程序合法性存疑,复议期限起算日存在争议。",
         "source_refs": ["M002:P0001", "M002:P0002", "M003:P0002"], "graph_refs": [],
         "evidence_status": "asserted"},
        {"claim": "申请人主张的紧急避险情节仅有本人陈述,无其他证据印证。",
         "source_refs": ["M003:P0003"], "graph_refs": [],
         "evidence_status": "asserted"},
    ],
    "limitations": [
        "本分析仅基于所提供的四份材料;卷内未见处罚前告知、听证等程序记载,不代表其必然不存在。",
        "测速设备检定状态、送达回证原件等关键事实需向被申请人或复议机关核实。",
        "本输出为AI辅助分析,不构成法律意见,正式使用前须由具备资质的人员复核。",
    ],
}

MOCK_WIKI_RESULT = {
    "mode": "retrieval_only",
    "model_calls": 0,
    "reasoning_used": False,
    "automatic_inference_injection": False,
    "result": {
        "source_id": "DEMO-002",
        "title": "合成演示:主体与事件分别绑定",
        "source_type": "synthetic_demo",
        "text_sha256": "demo",
        "full_original": "甲机关作出通知,乙机关仅转交材料。审查时应分别识别行为作出者、送达者、"
                         "申请人和第三人,不得因同一卷宗出现多个机关名称而互换主体。",
        "complete": True,
        "retrieval_score": 0.0,
        "retrieval_score_kind": "bm25_not_confidence",
    },
}


def sample_case() -> dict:
    """供前端「载入示例案件」使用。"""
    return {
        "question": SAMPLE_QUESTION,
        "materials": SAMPLE_MATERIALS,
        "overrides": SAMPLE_OVERRIDES,
    }


def build_mock_assist(user_request: str, materials: list[dict]) -> dict:
    """构造结构与真实 /v1/legal/assist 完全一致的模拟响应(仅演示/测试)。"""
    return {
        "workflow_id": f"mock-{uuid.uuid4().hex[:8]}",
        "backend_generation_requests": 6,
        "tokenizer_preflights": 6,
        "routing": {
            "facts": "facts_1949",
            "procedure": "procedure_1978",
            "final": "candidate_r79",
            "graph": "deterministic_local_fts_source_only",
            "wiki_injected": False,
        },
        "selected_graphs": [],
        "facts": _MOCK_FACTS,
        "procedure": _MOCK_PROCEDURE,
        "deterministic_normalization": {
            "facts": {"duplicate_actors_removed": 0, "duplicate_events_removed": 0,
                      "duplicate_evidence_removed": 0, "duplicate_uncertainties_removed": 0},
            "procedure": {"duplicate_actors_removed": 0, "duplicate_steps_removed": 0,
                          "duplicate_deadlines_removed": 0, "duplicate_unknowns_removed": 0,
                          "decision_maker_derived_from_challenged_action": True},
            "final": {"missing_graph_prefixes_restored": 0, "duplicate_graph_refs_removed": 0},
        },
        "answer": _MOCK_ANSWER,
        "mock_notice": "演示模式:本响应由内置模拟器生成,未调用真实模型。",
    }
