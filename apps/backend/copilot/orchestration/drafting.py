"""Assembling the incident draft.

The draft is built deterministically from evidence, not written by the
model. Two reasons: a ticket is an operational record and every line in it
should be traceable to a tool result or a cited document; and the
escalation procedure (ESC-010 section 6) specifies exactly what a ticket
must contain, which is a template, not a generation task.

The model's contribution is the narrative answer in the chat, not the
ticket body.
"""

from __future__ import annotations

import hashlib
from typing import Any

from copilot.models import (
    AlarmSummaryView,
    EvidenceCitation,
    SimilarTicketSummary,
    TicketDraft,
)
from rag.models import RetrievalResult

# ESC-010 priority matrix: (alarm severity, asset criticality) -> priority.
_PRIORITY_MATRIX: dict[tuple[str, str], str] = {
    ("critical", "critical"): "P1",
    ("critical", "high"): "P1",
    ("critical", "medium"): "P2",
    ("critical", "low"): "P2",
    ("high", "critical"): "P1",
    ("high", "high"): "P2",
    ("high", "medium"): "P2",
    ("high", "low"): "P3",
    ("medium", "critical"): "P2",
    ("medium", "high"): "P3",
    ("medium", "medium"): "P3",
    ("medium", "low"): "P4",
    ("low", "critical"): "P3",
    ("low", "high"): "P3",
    ("low", "medium"): "P4",
    ("low", "low"): "P4",
}

_BANDS = ["P1", "P2", "P3", "P4"]


def derive_priority(
    severity: str, criticality: str, *, modifiers: list[str] | None = None
) -> tuple[str, list[str]]:
    """Apply the ESC-010 matrix plus its escalation modifiers.

    Returns the priority and the reasons, so the draft can show its
    working rather than asserting a band.
    """
    base = _PRIORITY_MATRIX.get((severity.lower(), criticality.lower()), "P3")
    reasons = [
        f"ESC-010 matrix: {severity} alarm on a {criticality}-criticality asset gives {base}."
    ]
    index = _BANDS.index(base)
    for modifier in modifiers or []:
        if index > 0:
            index -= 1
            reasons.append(f"Raised one band: {modifier}")
        else:
            reasons.append(f"Already P1; {modifier} noted.")
    return _BANDS[index], reasons


def build_ticket_draft(
    *,
    conversation_id: str,
    alarm: AlarmSummaryView,
    asset_metadata: dict[str, Any] | None = None,
    recommendations: list[dict[str, Any]] | None = None,
    likely_causes: list[dict[str, Any]] | None = None,
    similar_tickets: list[SimilarTicketSummary] | None = None,
    correlation: dict[str, Any] | None = None,
    retrieval: RetrievalResult | None = None,
    open_linked_tickets: list[SimilarTicketSummary] | None = None,
) -> TicketDraft:
    """Compose the draft an operator will review, edit and approve."""
    recommendations = recommendations or []
    likely_causes = likely_causes or []
    similar_tickets = similar_tickets or []
    open_linked_tickets = open_linked_tickets or []

    criticality = str((asset_metadata or {}).get("criticality", "medium"))
    modifiers: list[str] = []
    if (alarm.occurrences_last_90_days or 0) > 5:
        modifiers.append(
            f"recurring: {alarm.occurrences_last_90_days} occurrences in 90 days "
            "(AP-001 section 6.1)"
        )
    if str((asset_metadata or {}).get("asset_type", "")) and not (asset_metadata or {}).get(
        "related_asset_ids"
    ):
        modifiers.append("no installed standby for this asset")

    priority, priority_reasons = derive_priority(alarm.severity, criticality, modifiers=modifiers)

    citations = [
        EvidenceCitation(**c.model_dump()) for c in (retrieval.citations if retrieval else [])
    ]
    description = _render_description(
        alarm=alarm,
        asset_metadata=asset_metadata,
        priority=priority,
        priority_reasons=priority_reasons,
        recommendations=recommendations,
        likely_causes=likely_causes,
        similar_tickets=similar_tickets,
        correlation=correlation,
        citations=citations,
        open_linked_tickets=open_linked_tickets,
    )

    # Stable across retries of the same request, so an approval replay
    # returns the ticket already created instead of opening a second one.
    approval_reference = f"{conversation_id}:{alarm.alarm_id}"
    draft_id = "draft-" + hashlib.sha256(approval_reference.encode()).hexdigest()[:12]

    labels = sorted(
        {
            "alarm-driven",
            "copilot-drafted",
            alarm.severity,
            str((asset_metadata or {}).get("asset_type", "")).strip() or "asset",
            alarm.unit.lower().replace(" ", "-"),
        }
        - {""}
    )

    return TicketDraft(
        draft_id=draft_id,
        title=f"{alarm.alarm_name} on {alarm.asset_name}",
        description=description,
        priority=priority,
        asset_id=alarm.asset_id,
        asset_name=alarm.asset_name,
        site=alarm.site,
        unit=alarm.unit,
        alarm_name=alarm.alarm_name,
        labels=labels,
        linked_alarm_ids=[alarm.alarm_id],
        citations=citations,
        similar_tickets=similar_tickets[:5],
        requires_approval=True,
        approval_reference=approval_reference,
    )


def _render_description(
    *,
    alarm: AlarmSummaryView,
    asset_metadata: dict[str, Any] | None,
    priority: str,
    priority_reasons: list[str],
    recommendations: list[dict[str, Any]],
    likely_causes: list[dict[str, Any]],
    similar_tickets: list[SimilarTicketSummary],
    correlation: dict[str, Any] | None,
    citations: list[EvidenceCitation],
    open_linked_tickets: list[SimilarTicketSummary],
) -> str:
    """Render the body in the structure ESC-010 section 6 requires."""
    lines: list[str] = []

    lines.append("## Alarm")
    lines.append("")
    lines.append(f"- **Alarm**: {alarm.alarm_name} (`{alarm.alarm_id}`)")
    lines.append(f"- **Severity**: {alarm.severity} | **Status**: {alarm.status}")
    lines.append(f"- **Raised**: {alarm.start_time}")
    if alarm.measured_value is not None and alarm.limit_value is not None:
        unit = alarm.unit_of_measure or ""
        lines.append(
            f"- **Reading**: {alarm.measured_value} {unit} against a limit of "
            f"{alarm.limit_value} {unit}".rstrip()
        )
    if alarm.occurrences_last_90_days is not None:
        lines.append(
            f"- **Recurrence**: {alarm.occurrences_last_90_days} occurrence(s) "
            "on this asset in the last 90 days"
        )

    lines.append("")
    lines.append("## Asset")
    lines.append("")
    lines.append(f"- **Asset**: {alarm.asset_name} (`{alarm.asset_id}`)")
    lines.append(f"- **Location**: {alarm.site} / {alarm.unit}")
    if asset_metadata:
        lines.append(f"- **Criticality**: {asset_metadata.get('criticality', 'unknown')}")
        lines.append(f"- **Tag**: {asset_metadata.get('tag', 'n/a')}")
        if asset_metadata.get("manufacturer"):
            lines.append(
                f"- **Equipment**: {asset_metadata.get('manufacturer')} "
                f"{asset_metadata.get('model_number', '')}".rstrip()
            )
        if asset_metadata.get("last_maintenance_date"):
            lines.append(
                f"- **Last maintenance**: {str(asset_metadata['last_maintenance_date'])[:10]}"
            )

    lines.append("")
    lines.append("## Priority")
    lines.append("")
    lines.append(f"**{priority}**")
    lines.append("")
    for reason in priority_reasons:
        lines.append(f"- {reason}")
    if alarm.priority_rationale:
        lines.append(f"- Alarm system score: {alarm.priority_rationale}")

    if likely_causes:
        lines.append("")
        lines.append("## Likely causes")
        lines.append("")
        for cause in likely_causes[:4]:
            confidence = cause.get("confidence")
            suffix = f" (confidence {confidence})" if confidence is not None else ""
            lines.append(f"- {cause.get('cause', '')}{suffix}")

    if recommendations:
        lines.append("")
        lines.append("## Recommended actions")
        lines.append("")
        for action in recommendations[:5]:
            lines.append(
                f"{action.get('rank', '-')}. **{action.get('action', '')}** "
                f"(~{action.get('estimated_minutes', '?')} min)"
            )
            if action.get("rationale"):
                lines.append(f"   - Why: {action['rationale']}")

    if correlation and correlation.get("correlated_assets"):
        lines.append("")
        lines.append("## Correlated assets")
        lines.append("")
        for row in correlation["correlated_assets"][:5]:
            lines.append(
                f"- {row['asset_name']} (`{row['asset_id']}`) - "
                f"{row['shared_events']} co-occurring alarm(s), "
                f"score {row['correlation_score']}"
            )
        pairs = correlation.get("pairs") or []
        if pairs:
            lines.append("")
            lines.append("Leading alarm pairs:")
            for pair in pairs[:3]:
                lines.append(
                    f"- {pair['alarm_name_a']} then {pair['alarm_name_b']} "
                    f"(support {pair['support']}, median lag "
                    f"{pair['median_lag_seconds']:.0f}s)"
                )

    if open_linked_tickets:
        lines.append("")
        lines.append("## Open tickets on linked assets")
        lines.append("")
        lines.append(
            "_Check these before proceeding; ESC-010 section 7 asks that related "
            "work be linked rather than duplicated._"
        )
        lines.append("")
        for ticket in open_linked_tickets[:5]:
            lines.append(f"- `{ticket.key}` [{ticket.priority}/{ticket.status}] {ticket.title}")

    if similar_tickets:
        lines.append("")
        lines.append("## Comparable past incidents")
        lines.append("")
        for ticket in similar_tickets[:4]:
            header = f"- `{ticket.key}` (similarity {ticket.score:.2f}) {ticket.title}"
            lines.append(header)
            if ticket.root_cause:
                lines.append(f"  - Root cause: {ticket.root_cause}")
            if ticket.resolution:
                lines.append(f"  - Resolution: {ticket.resolution}")
            if ticket.time_to_resolve_hours:
                lines.append(f"  - Resolved in {ticket.time_to_resolve_hours:.1f}h")

    if citations:
        lines.append("")
        lines.append("## Applicable procedures")
        lines.append("")
        for citation in citations:
            location = f" > {citation.heading}" if citation.heading else ""
            lines.append(
                f"- {citation.marker} **{citation.doc_id}** {citation.title}{location} "
                f"(`{citation.source_path}`)"
            )
            lines.append(f"  - {citation.excerpt[:300]}")
    else:
        lines.append("")
        lines.append("## Applicable procedures")
        lines.append("")
        lines.append(
            "_No procedure cleared the relevance threshold for this alarm. "
            "Review the corpus before closing._"
        )

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "_Drafted by the Incident and Ticket Enrichment Copilot from alarm-system "
        "data and the document corpus. Every section above is traceable to a tool "
        "result or a cited document. Review and edit before approving._"
    )
    return "\n".join(lines)
