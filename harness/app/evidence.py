"""证据链梳理:把 R79 assist 响应整理为结构化 chain,并生成中文 Markdown 报告。

chain 形状(见 SPEC):
    {actors, timeline, evidence, matrix, uncertainties,
     procedure_steps, deadlines, stats}

- timeline:exact(可解析日期升序)→ partial → unknown。
- matrix:行=事件,列=证据,cell=True 表示该证据的 supports_event_ids 含该事件。
- stats:actors/events/evidence/uncertainties/contradicted/unknown 计数。
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

_CN_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


def _parse_date(text: str | None) -> date | None:
    """从 date_text 解析 YYYY年M月D日 或 YYYY-MM-DD,失败返回 None。"""
    if not text:
        return None
    m = _CN_DATE_RE.search(text) or _ISO_DATE_RE.search(text)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _date_sort_key(item: dict) -> tuple:
    """exact 且可解析日期的排前(按日期升序),其余 exact 次之,再 partial,最后 unknown。"""
    status = item.get("date_status", "unknown")
    parsed = _parse_date(item.get("date_text"))
    if status == "exact":
        if parsed is not None:
            return (0, parsed, item.get("event_id") or item.get("step_id") or "")
        return (1, date.max, item.get("event_id") or item.get("step_id") or "")
    if status == "partial":
        return (2, date.max, item.get("event_id") or item.get("step_id") or "")
    return (3, date.max, item.get("event_id") or item.get("step_id") or "")


def _actor_name_map(assist_result: dict) -> dict[str, str]:
    names: dict[str, str] = {}
    facts = assist_result.get("facts") or {}
    for actor in facts.get("actors") or []:
        names[actor.get("actor_id", "")] = actor.get("name_as_stated", "")
    proc = assist_result.get("procedure") or {}
    for actor in proc.get("actors") or []:
        names.setdefault(actor.get("actor_id", ""), actor.get("name_as_stated", ""))
    return names


def build_chain(assist_result: dict) -> dict:
    """按 SPEC 从 assist 响应生成证据链 dict。"""
    facts = assist_result.get("facts") or {}
    proc = assist_result.get("procedure") or {}

    actors = facts.get("actors") or []
    events = facts.get("events") or []
    evidence = facts.get("evidence") or []
    uncertainties = facts.get("uncertainties") or []
    steps = proc.get("steps") or []
    deadlines = proc.get("deadlines") or []

    names = _actor_name_map(assist_result)

    timeline = []
    for ev in events:
        timeline.append(
            {
                "event_id": ev.get("event_id", ""),
                "date_text": ev.get("date_text", ""),
                "date_status": ev.get("date_status", "unknown"),
                "action": ev.get("action", ""),
                "object": ev.get("object", ""),
                "actor_names": [names.get(a, a) for a in ev.get("actor_ids") or []],
                "evidence_status": ev.get("evidence_status", "unknown"),
                "source_refs": ev.get("source_refs") or [],
            }
        )
    timeline.sort(key=_date_sort_key)

    event_ids = [e.get("event_id", "") for e in events]
    evidence_ids = [e.get("evidence_id", "") for e in evidence]
    supports = {e.get("evidence_id", ""): set(e.get("supports_event_ids") or []) for e in evidence}
    cells = [[ev_id in supports.get(evidence_id, set()) for evidence_id in evidence_ids] for ev_id in event_ids]
    matrix = {"event_ids": event_ids, "evidence_ids": evidence_ids, "cells": cells}

    stats = {
        "actors": len(actors),
        "events": len(events),
        "evidence": len(evidence),
        "uncertainties": len(uncertainties),
        "contradicted": sum(1 for e in events if e.get("evidence_status") == "contradicted"),
        "unknown": sum(1 for e in events if e.get("evidence_status") == "unknown"),
    }

    return {
        "actors": actors,
        "timeline": timeline,
        "evidence": evidence,
        "matrix": matrix,
        "uncertainties": uncertainties,
        "procedure_steps": steps,
        "deadlines": deadlines,
        "stats": stats,
    }


_STATUS_LABEL = {
    "proved": "已证实",
    "asserted": "单方主张",
    "contradicted": "存在矛盾",
    "unknown": "未知",
}
_DATE_LABEL = {"exact": "精确", "partial": "部分", "unknown": "未知"}


def _esc(text: Any) -> str:
    return str(text if text is not None else "").replace("|", "\\|")


def build_report_markdown(assist_result: dict, chain: dict) -> str:
    """生成中文证据链梳理报告(Markdown)。"""
    facts = assist_result.get("facts") or {}
    proc = assist_result.get("procedure") or {}
    names = _actor_name_map(assist_result)
    stats = chain["stats"]

    lines: list[str] = []
    lines.append("# 行政案件证据链梳理报告")
    lines.append("")
    lines.append("## 一、概览统计")
    lines.append("")
    lines.append(f"- 主体:{stats['actors']} 个")
    lines.append(f"- 事件:{stats['events']} 件")
    lines.append(f"- 证据:{stats['evidence']} 份")
    lines.append(f"- 待核实事项:{stats['uncertainties']} 项")
    lines.append(f"- 证据状态矛盾的事件:{stats['contradicted']} 件")
    lines.append(f"- 证据状态未知的事件:{stats['unknown']} 件")
    lines.append("")

    lines.append("## 二、案件主体")
    lines.append("")
    lines.append("| 编号 | 名称(卷内表述) | 角色 | 证据状态 | 出处 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for a in chain["actors"]:
        lines.append(
            f"| {_esc(a.get('actor_id'))} | {_esc(a.get('name_as_stated'))} | {_esc(a.get('role'))} "
            f"| {_STATUS_LABEL.get(a.get('evidence_status'), a.get('evidence_status', ''))} "
            f"| {_esc('、'.join(a.get('source_refs') or []))} |"
        )
    lines.append("")

    lines.append("## 三、事件时间线")
    lines.append("")
    lines.append("| 时间 | 日期状态 | 事件 | 对象 | 相关主体 | 证据状态 | 出处 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for ev in chain["timeline"]:
        lines.append(
            f"| {_esc(ev.get('date_text') or '日期不详')} "
            f"| {_DATE_LABEL.get(ev.get('date_status'), ev.get('date_status', ''))} "
            f"| {_esc(ev.get('action'))} | {_esc(ev.get('object'))} "
            f"| {_esc('、'.join(ev.get('actor_names') or []))} "
            f"| {_STATUS_LABEL.get(ev.get('evidence_status'), ev.get('evidence_status', ''))} "
            f"| {_esc('、'.join(ev.get('source_refs') or []))} |"
        )
    lines.append("")

    lines.append("## 四、证据支持矩阵")
    lines.append("")
    matrix = chain["matrix"]
    evidence_by_id = {e.get("evidence_id", ""): e for e in chain["evidence"]}
    header = "| 事件 \\ 证据 | " + " | ".join(_esc(e) for e in matrix["evidence_ids"]) + " |"
    sep = "| --- |" + " --- |" * len(matrix["evidence_ids"])
    lines.append(header)
    lines.append(sep)
    for i, ev_id in enumerate(matrix["event_ids"]):
        row = [f"| {_esc(ev_id)}"]
        for j, evd_id in enumerate(matrix["evidence_ids"]):
            row.append("✓" if matrix["cells"][i][j] else "—")
        lines.append(" | ".join(row) + " |")
    lines.append("")
    lines.append("证据清单:")
    lines.append("")
    for evd_id in matrix["evidence_ids"]:
        evd = evidence_by_id.get(evd_id, {})
        lines.append(
            f"- **{evd_id}**:{evd.get('description', '')}"
            f"(状态:{_STATUS_LABEL.get(evd.get('status'), evd.get('status', ''))};"
            f"出处:{'、'.join(evd.get('source_refs') or [])})"
        )
    lines.append("")

    lines.append("## 五、矛盾与未知事项")
    lines.append("")
    contradicted = [e for e in chain["timeline"] if e.get("evidence_status") == "contradicted"]
    if contradicted:
        lines.append("存在矛盾证据的事件:")
        lines.append("")
        for ev in contradicted:
            lines.append(f"- {ev.get('event_id')}:{ev.get('action')}")
        lines.append("")
    uncertainties = chain["uncertainties"]
    if uncertainties:
        lines.append("尚无法确认的事项:")
        lines.append("")
        for u in uncertainties:
            lines.append(
                f"- **{u.get('field', '')}**:{u.get('reason', '')}"
                f"(出处:{'、'.join(u.get('source_refs') or [])})"
            )
        lines.append("")
    if not contradicted and not uncertainties:
        lines.append("本次梳理未发现矛盾证据或待确认事项。")
        lines.append("")

    lines.append("## 六、行政程序步骤与期限")
    lines.append("")
    steps = chain["procedure_steps"]
    if steps:
        lines.append("程序步骤:")
        lines.append("")
        lines.append("| 编号 | 时间 | 行为主体 | 行为 | 证据状态 | 出处 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for s in steps:
            actor = names.get(s.get("actor_id", ""), s.get("actor_id", ""))
            lines.append(
                f"| {_esc(s.get('step_id'))} | {_esc(s.get('date_text') or '日期不详')} "
                f"| {_esc(actor)} | {_esc(s.get('action'))} "
                f"| {_STATUS_LABEL.get(s.get('evidence_status'), s.get('evidence_status', ''))} "
                f"| {_esc('、'.join(s.get('source_refs') or []))} |"
            )
        lines.append("")
    deadlines = chain["deadlines"]
    if deadlines:
        lines.append("相关期限:")
        lines.append("")
        for d in deadlines:
            lines.append(
                f"- {d.get('description', '')}:{d.get('start_date', '')} 起,"
                f"{d.get('end_date', '')} 止"
                f"(日期状态:{_DATE_LABEL.get(d.get('date_status'), d.get('date_status', ''))};"
                f"出处:{'、'.join(d.get('source_refs') or [])})"
            )
        lines.append("")
    proc_unknowns = proc.get("unknowns") or []
    if proc_unknowns:
        lines.append("程序待核实事项:")
        lines.append("")
        for u in proc_unknowns:
            lines.append(f"- **{u.get('field', '')}**:{u.get('reason', '')}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "本报告由 AI 辅助生成,仅基于所提供材料的结构化分析结果,"
        "不构成法律意见;所有事实、日期、证据状态与出处引用须经人工逐项复核后方可使用。"
    )
    lines.append("")
    return "\n".join(lines)
