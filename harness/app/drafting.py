"""行政复议申请书起草:模型结构化分析 + 确定性模板组装。

规则(见 SPEC「文书起草」):
- 不再调用模型自由生成,仅由 assist 响应的 facts/procedure/answer 组装。
- 结构:标题 → 申请人 → 被申请人 → 第三人(可省略)→ 复议请求 →
  事实和理由(一、基本事实;二、行政程序情况;三、申请理由与法律依据)→
  证据目录 → 此致 {复议机关} → 签名/日期【待补充】。
- 缺失信息一律写【待补充:xxx】并同步进 review_notes;
  answer.limitations 不进正文,进 review_notes。
- make_docx:标题二号黑体居中;正文三号(16pt)仿宋,首行缩进 2 字符,
  1.5 倍行距;中文字体经 qn('w:eastAsia') 设置。
"""
from __future__ import annotations

import io
import re
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Pt

from .evidence import build_chain

_PENDING_RE = re.compile(r"【待补充:([^】]+)】")


def _find_applicant(assist_result: dict) -> str | None:
    """从 facts/procedure 的 actors 中找 role 含「申请人」的主体名称。"""
    for section in (assist_result.get("facts") or {}, assist_result.get("procedure") or {}):
        for actor in section.get("actors") or []:
            if "申请人" in (actor.get("role") or "") and "被申请人" not in (actor.get("role") or ""):
                return actor.get("name_as_stated")
    return None


def _find_respondent(assist_result: dict) -> str | None:
    """被申请人 = procedure.decision_maker_actor_id 对应的 actor 名称。"""
    proc = assist_result.get("procedure") or {}
    dm_id = proc.get("decision_maker_actor_id")
    if dm_id:
        for actor in proc.get("actors") or []:
            if actor.get("actor_id") == dm_id:
                return actor.get("name_as_stated")
        facts = assist_result.get("facts") or {}
        for actor in facts.get("actors") or []:
            if actor.get("actor_id") == dm_id:
                return actor.get("name_as_stated")
    return None


def _derive_claims_text(assist_result: dict) -> str:
    """由 challenged_action 推导复议请求。"""
    proc = assist_result.get("procedure") or {}
    action = (proc.get("challenged_action") or {}).get("description") or ""
    if action:
        return f"请求撤销{action}。"
    return ""


def build_document(assist_result: dict, overrides: dict | None = None) -> tuple[str, list[str]]:
    """按 SPEC 生成《行政复议申请书》Markdown 与审核提示。

    返回 (document_markdown, review_notes)。
    """
    overrides = overrides or {}
    review_notes: list[str] = []
    pending: list[str] = []

    def need(value: str | None, label: str) -> str:
        if value and str(value).strip():
            return str(value).strip()
        pending.append(label)
        return f"【待补充:{label}】"

    facts = assist_result.get("facts") or {}
    proc = assist_result.get("procedure") or {}
    answer = assist_result.get("answer") or {}
    chain = build_chain(assist_result)

    applicant = overrides.get("applicant_name") or _find_applicant(assist_result)
    respondent = _find_respondent(assist_result)
    third_party = (overrides.get("third_party") or "").strip()
    claims_text = (overrides.get("claims_text") or "").strip() or _derive_claims_text(assist_result)
    review_organ = (overrides.get("review_organ") or "").strip()

    lines: list[str] = []
    lines.append("# 行政复议申请书")
    lines.append("")
    lines.append(f"申请人:{need(applicant, '申请人姓名')}")
    lines.append("")
    lines.append(f"被申请人:{need(respondent, '被申请人(行政行为作出机关)名称')}")
    lines.append("")
    if third_party:
        lines.append(f"第三人:{third_party}")
        lines.append("")

    lines.append("## 复议请求")
    lines.append("")
    lines.append(need(claims_text, "复议请求"))
    lines.append("")

    lines.append("## 事实和理由")
    lines.append("")

    # 一、基本事实
    lines.append("### 一、基本事实")
    lines.append("")
    if chain["timeline"]:
        for ev in chain["timeline"]:
            date_text = ev.get("date_text") or "日期不详"
            actors = "、".join(ev.get("actor_names") or [])
            actor_part = f"{actors}" if actors else "相关主体"
            obj = f",对象:{ev.get('object')}" if ev.get("object") else ""
            lines.append(f"{date_text},{actor_part}{ev.get('action', '')}{obj}。")
        lines.append("")
    else:
        lines.append("【待补充:基本事实】")
        pending.append("基本事实")
        lines.append("")

    # 二、行政程序情况
    lines.append("### 二、行政程序情况")
    lines.append("")
    steps = proc.get("steps") or []
    deadlines = proc.get("deadlines") or []
    names = {a.get("actor_id", ""): a.get("name_as_stated", "") for a in proc.get("actors") or []}
    if steps:
        for s in steps:
            actor = names.get(s.get("actor_id", ""), s.get("actor_id", ""))
            date_text = s.get("date_text") or "日期不详"
            lines.append(f"{date_text},{actor}{s.get('action', '')}。")
        lines.append("")
    if deadlines:
        for d in deadlines:
            lines.append(
                f"关于「{d.get('description', '')}」:{d.get('start_date', '')} 起,"
                f"{d.get('end_date', '')} 止。"
            )
        lines.append("")
    if not steps and not deadlines:
        lines.append("【待补充:行政程序情况】")
        pending.append("行政程序情况")
        lines.append("")

    # 三、申请理由与法律依据
    lines.append("### 三、申请理由与法律依据")
    lines.append("")
    claims = answer.get("claims") or []
    if claims:
        for i, c in enumerate(claims, 1):
            lines.append(f"{i}. {c.get('claim', '')}")
        lines.append("")
    if answer.get("conclusion"):
        lines.append(str(answer["conclusion"]))
        lines.append("")
    if answer.get("analysis"):
        lines.append(str(answer["analysis"]))
        lines.append("")
    if not claims and not answer.get("conclusion") and not answer.get("analysis"):
        lines.append("【待补充:申请理由与法律依据】")
        pending.append("申请理由与法律依据")
        lines.append("")

    # 证据目录
    lines.append("## 证据目录")
    lines.append("")
    evidence = facts.get("evidence") or []
    if evidence:
        for i, evd in enumerate(evidence, 1):
            lines.append(f"{i}. {evd.get('description', '')}")
        lines.append("")
    else:
        lines.append("【待补充:证据目录】")
        pending.append("证据目录")
        lines.append("")

    lines.append(f"此致 {need(review_organ, '复议机关名称')}")
    lines.append("")
    lines.append("申请人(签名):【待补充:申请人签名】")
    pending.append("申请人签名")
    lines.append("")
    lines.append("日期:【待补充:申请日期】")
    pending.append("申请日期")
    lines.append("")

    document_markdown = "\n".join(lines)

    # review_notes:所有【待补充】项 + answer.limitations + 人工核对提示
    seen: set[str] = set()
    for label in pending + _PENDING_RE.findall(document_markdown):
        if label not in seen:
            seen.add(label)
            review_notes.append(f"【待补充:{label}】")
    for lim in answer.get("limitations") or []:
        review_notes.append(str(lim))
    review_notes.append("本申请书由 AI 辅助生成,须经人工核对全部事实、法律依据与格式后方可提交。")

    return document_markdown, review_notes


def _set_cn_font(run, name: str, size_pt: float, bold: bool = False) -> None:
    run.font.name = name
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), name)


def make_docx(document_markdown: str) -> bytes:
    """把文书 Markdown 转为 docx 字节流。

    排版:标题(#)二号(22pt)黑体居中;小节标题(##/###)三号黑体;
    正文三号(16pt)仿宋,首行缩进 2 字符,1.5 倍行距。
    """
    doc = Document()
    for raw in document_markdown.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# "):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(line[2:].strip())
            _set_cn_font(run, "黑体", 22, bold=True)
        elif line.startswith("## ") or line.startswith("### "):
            p = doc.add_paragraph()
            run = p.add_run(line.lstrip("# ").strip())
            _set_cn_font(run, "黑体", 16, bold=True)
            p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
        else:
            p = doc.add_paragraph()
            run = p.add_run(line)
            _set_cn_font(run, "仿宋", 16)
            pf = p.paragraph_format
            pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
            # 首行缩进 2 字符(按字号 16pt × 2)
            pf.first_line_indent = Pt(32)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
