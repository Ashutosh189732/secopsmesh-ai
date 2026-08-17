"""Report Generator — Day 6.

Renders one incident into a PDF via reportlab (pure Python, no headless
browser). Handles incidents at any pipeline stage gracefully — sections for
data that hasn't been produced yet (parked/queued incidents, or one still
mid-investigation) render a placeholder instead of crashing.
"""

from datetime import datetime, timezone
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models import Incident

_styles = getSampleStyleSheet()
_h1 = _styles["Heading1"]
_h2 = _styles["Heading2"]
_body = _styles["BodyText"]
_small = ParagraphStyle("small", parent=_body, fontSize=8, leading=10)


def _p(text: str, style=None):
    return Paragraph(text.replace("\n", "<br/>"), style or _body)


def _placeholder(text: str):
    return _p(f"<i>{text}</i>", _body)


def _section_title(text: str):
    return _p(text, _h2)


def _executive_summary(incident: Incident) -> list:
    elements = [_section_title("Executive Summary")]
    if incident.risk_assessment:
        ra = incident.risk_assessment
        elements.append(
            _p(
                f"<b>Risk severity:</b> {ra.get('severity')} "
                f"(score {ra.get('score')}/100) &nbsp;&nbsp; "
                f"<b>GDPR flag:</b> {'Yes' if ra.get('gdpr_flag') else 'No'}"
            )
        )
        elements.append(Spacer(1, 6))
        elements.append(_p(ra.get("business_impact", "")))
    elif incident.fp_explanation:
        # Gated (parked/queued) or still-running incidents get the deterministic
        # gate explanation instead of a misleading "not yet available" — for a
        # parked incident there is no later; this IS the summary.
        elements.append(_p(incident.fp_explanation))
        if incident.llm_explanation:
            elements.append(Spacer(1, 6))
            elements.append(_p(f"<b>Analyst explanation (LLM, on demand):</b> {incident.llm_explanation}"))
    else:
        elements.append(_placeholder("Risk assessment not yet available for this incident."))
    return elements


def _timeline_section(incident: Incident) -> list:
    elements = [Spacer(1, 12), _section_title("Timeline")]
    if not incident.timeline:
        elements.append(_placeholder("No timeline events recorded."))
        return elements

    rows = [["Time (UTC)", "Signal", "Source"]]
    for event in incident.timeline:
        rows.append([event.get("timestamp", ""), event.get("signal", ""), event.get("source", "")])
    table = Table(rows, colWidths=[2.2 * inch, 2.2 * inch, 2.2 * inch])
    table.setStyle(_table_style())
    elements.append(table)
    return elements


def _fp_gate_section(incident: Incident) -> list:
    elements = [Spacer(1, 12), _section_title("False-Positive Gate Decision")]
    elements.append(
        _p(
            f"<b>Score:</b> {incident.fp_score} &nbsp;&nbsp; "
            f"<b>Status:</b> {incident.status} &nbsp;&nbsp; "
            f"<b>Correlated signals:</b> {incident.correlated_count}"
        )
    )
    if incident.fp_decision_reason:
        elements.append(_p(incident.fp_decision_reason, _small))
    return elements


def _evidence_section(incident: Incident) -> list:
    elements = [Spacer(1, 12), _section_title("Evidence (with confidence scores)")]
    if not incident.evidence:
        elements.append(_placeholder("No evidence collected yet."))
        return elements

    rows = [["ID", "Connector", "Confidence", "Fetched At", "Data Preview"]]
    for item in incident.evidence:
        preview = ", ".join(f"{k}={v}" for k, v in list(item.get("data", {}).items())[:3])
        rows.append(
            [
                item.get("id", ""),
                item.get("connector", ""),
                f"{item.get('confidence', 0):.2f}",
                item.get("fetched_at", "")[:19],
                Paragraph(preview, _small),
            ]
        )
    table = Table(rows, colWidths=[0.5 * inch, 1.1 * inch, 0.8 * inch, 1.3 * inch, 2.6 * inch])
    table.setStyle(_table_style())
    elements.append(table)
    if incident.evidence_guard_triggered:
        elements.append(Spacer(1, 4))
        elements.append(
            _p(
                "<b>Note:</b> the 90-second investigation guard was triggered — "
                "evidence collection was cut short.",
                _small,
            )
        )
    return elements


def _policies_section(incident: Incident) -> list:
    elements = [Spacer(1, 12), _section_title("Policies Violated / Relevant")]
    if not incident.policies:
        elements.append(_placeholder("No policy matches retrieved yet."))
        return elements

    for policy in incident.policies:
        elements.append(
            _p(
                f"<b>{policy.get('title', policy.get('policy_id'))}</b> "
                f"(relevance {policy.get('relevance_score', 0):.2f})"
            )
        )
        elements.append(_p(policy.get("excerpt", ""), _small))
        elements.append(Spacer(1, 6))
    return elements


def _root_cause_section(incident: Incident) -> list:
    elements = [Spacer(1, 12), _section_title("Root Cause")]
    rc = incident.root_cause
    if not rc:
        elements.append(_placeholder("Root cause analysis not yet available."))
        return elements

    elements.append(_p(rc.get("root_cause", "")))
    elements.append(Spacer(1, 4))
    elements.append(
        _p(
            f"<b>Confidence:</b> {rc.get('confidence', 0):.2f} &nbsp;&nbsp; "
            f"<b>Evidence cited:</b> {', '.join(rc.get('evidence_ids_cited', [])) or 'none'} "
            f"&nbsp;&nbsp; <b>GDPR flag:</b> {'Yes' if rc.get('gdpr_flag') else 'No'}"
        )
    )
    alternatives = rc.get("alternative_hypotheses", [])
    if alternatives:
        elements.append(Spacer(1, 6))
        elements.append(_p("<b>Alternative hypotheses considered:</b>", _body))
        for alt in alternatives:
            elements.append(_p(f"&bull; {alt}", _small))
    return elements


def _risk_section(incident: Incident) -> list:
    elements = [Spacer(1, 12), _section_title("Risk Assessment")]
    ra = incident.risk_assessment
    if not ra:
        elements.append(_placeholder("Risk assessment not yet available."))
        return elements

    elements.append(
        _p(
            f"<b>Severity:</b> {ra.get('severity')} &nbsp;&nbsp; "
            f"<b>Score:</b> {ra.get('score')}/100 &nbsp;&nbsp; "
            f"<b>Affected:</b> {ra.get('affected_estimate')} &nbsp;&nbsp; "
            f"<b>GDPR flag:</b> {'Yes' if ra.get('gdpr_flag') else 'No'}"
        )
    )
    elements.append(Spacer(1, 6))
    elements.append(_p(f"<b>Business impact:</b> {ra.get('business_impact', '')}"))
    elements.append(Spacer(1, 4))
    elements.append(_p(f"<b>Compliance impact:</b> {ra.get('compliance_impact', '')}"))
    return elements


def _remediation_section(incident: Incident) -> list:
    elements = [Spacer(1, 12), _section_title("Remediation Steps")]
    plan = incident.remediation_plan
    if not plan or not plan.get("steps"):
        elements.append(_placeholder("No remediation plan generated yet."))
        return elements

    rows = [["#", "Action", "Owner", "Priority", "Est. Time", "Approval"]]
    for step in plan["steps"]:
        rows.append(
            [
                str(step.get("step_number", "")),
                Paragraph(step.get("action", ""), _small),
                Paragraph(step.get("owner", ""), _small),
                step.get("priority", ""),
                Paragraph(step.get("estimated_time", ""), _small),
                "Required" if step.get("requires_human_approval") else "—",
            ]
        )
    table = Table(rows, colWidths=[0.3 * inch, 2.6 * inch, 1.5 * inch, 0.6 * inch, 0.9 * inch, 0.8 * inch])
    table.setStyle(_table_style())
    elements.append(table)
    elements.append(Spacer(1, 6))
    elements.append(
        _p(
            "<i>No action in this system executes automatically. Every step above "
            "requires explicit human approval.</i>",
            _small,
        )
    )
    return elements


def _table_style() -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
        ]
    )


def build_report(incident: Incident) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter, topMargin=0.6 * inch, bottomMargin=0.6 * inch
    )

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    elements = [
        _p("SecOpsMeshAI POC", _h1),
        _p(f"Incident Report — #{incident.id} — {incident.resource_name}", _h2),
        _p(f"Generated {generated_at}", _small),
        Spacer(1, 12),
    ]
    elements += _executive_summary(incident)
    elements += _fp_gate_section(incident)
    elements += _timeline_section(incident)
    elements += _evidence_section(incident)
    elements += _policies_section(incident)
    elements += _root_cause_section(incident)
    elements += _risk_section(incident)
    elements += _remediation_section(incident)

    doc.build(elements)
    return buffer.getvalue()
