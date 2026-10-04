"""Export resolved tickets as RAG corpus documents.

    python scripts/export_resolution_notes.py

The assignment asks for "historical resolution notes" in the document
corpus. Rather than inventing a second, parallel set of stories, these are
generated from the same resolved tickets the ticketing system serves - so a
citation the copilot shows and a ticket the user can open say the same
thing. Regenerating after changing the ticket seed keeps them in step.

One document per asset type keeps each file small enough to chunk cleanly
while still grouping related failure modes together.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TICKETS = ROOT / "test-data" / "seed_tickets.json"
OUT_DIR = ROOT / "rag" / "documents"

# Only these statuses carry a usable resolution.
RESOLVED = {"resolved", "closed"}

# Keep each document focused; the most instructive cases are the ones that
# recur, so order by root cause frequency and cap the long tail.
MAX_CASES_PER_CAUSE = 3


def _fmt_date(raw: str) -> str:
    try:
        return datetime.fromisoformat(raw).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return raw[:10]


def build_documents() -> dict[str, str]:
    payload = json.loads(TICKETS.read_text(encoding="utf-8"))
    tickets = [t for t in payload["tickets"] if t["status"] in RESOLVED and t.get("resolution")]

    by_type: dict[str, list[dict]] = defaultdict(list)
    for ticket in tickets:
        by_type[ticket["asset_type"]].append(ticket)

    documents: dict[str, str] = {}
    for asset_type, rows in sorted(by_type.items()):
        # Group by (alarm, root cause) so the document reads as failure
        # modes rather than as a ticket dump.
        grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for ticket in rows:
            grouped[(ticket["alarm_name"], ticket["root_cause"] or "Unclassified")].append(ticket)

        ordered = sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        alarms = sorted({a for a, _ in grouped})
        sites = sorted({t["site"] for t in rows})
        resolve_times = [t["time_to_resolve_hours"] for t in rows if t.get("time_to_resolve_hours")]

        lines: list[str] = []
        lines.append("---")
        lines.append(f"doc_id: KB-{asset_type.upper().replace('_', '')[:6]}")
        lines.append(f"title: Historical Resolution Notes - {asset_type.replace('_', ' ').title()}")
        lines.append("doc_type: resolution_notes")
        lines.append("revision: 1")
        lines.append("effective_date: 2026-09-30")
        lines.append("owner: Maintenance Knowledge Base")
        lines.append(f"applies_to_asset_types: [{asset_type}]")
        lines.append("applies_to_alarms: [" + ", ".join(alarms) + "]")
        lines.append("sites: [" + ", ".join(sites) + "]")
        lines.append(f"tags: [resolution-notes, history, {asset_type}, root-cause]")
        lines.append(
            "source: generated from resolved tickets by scripts/export_resolution_notes.py"
        )
        lines.append("---")
        lines.append("")
        lines.append(f"# Historical Resolution Notes: {asset_type.replace('_', ' ').title()}")
        lines.append("")
        lines.append(
            f"Drawn from {len(rows)} resolved tickets across {len(sites)} site(s). "
            "Each section is a failure mode that has actually occurred on this class "
            "of asset, with what was found and what fixed it."
        )
        if resolve_times:
            median = sorted(resolve_times)[len(resolve_times) // 2]
            lines.append("")
            lines.append(f"Median time to resolve across these cases: {median:.1f} hours.")
        lines.append("")

        for (alarm_name, root_cause), cases in ordered:
            lines.append(f"## {alarm_name} - {root_cause}")
            lines.append("")
            lines.append(
                f"Occurred {len(cases)} time(s) on this asset class. "
                f"Tickets: {', '.join(c['key'] for c in cases[:6])}"
                + (" and others." if len(cases) > 6 else ".")
            )
            lines.append("")

            exemplar = cases[0]
            lines.append(f"**What was found.** {_finding(exemplar)}")
            lines.append("")
            lines.append(f"**What resolved it.** {exemplar['resolution']}")
            lines.append("")

            times = [c["time_to_resolve_hours"] for c in cases if c.get("time_to_resolve_hours")]
            if times:
                lines.append(
                    f"**Typical effort.** {min(times):.1f} to {max(times):.1f} hours "
                    f"({len(times)} recorded)."
                )
                lines.append("")

            if len(cases) > 1:
                lines.append("Recorded instances:")
                lines.append("")
                for case in cases[:MAX_CASES_PER_CAUSE]:
                    lines.append(
                        f"- `{case['key']}` {_fmt_date(case['created_at'])} - "
                        f"{case['asset_name']} ({case['site']} / {case['unit']}), "
                        f"priority {case['priority']}"
                    )
                lines.append("")

        documents[f"KB-resolution-notes-{asset_type}.md"] = "\n".join(lines)

    return documents


def _finding(ticket: dict) -> str:
    """Pull the field-investigation sentence out of the ticket description."""
    marker = "Field investigation found: "
    description = ticket.get("description", "")
    if marker in description:
        return description.split(marker, 1)[1].strip()
    return ticket.get("root_cause") or "Condition confirmed in the field."


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    documents = build_documents()
    for name, body in documents.items():
        (OUT_DIR / name).write_text(body, encoding="utf-8")
        words = len(body.split())
        print(f"  wrote {name} ({words} words)")
    print(f"exported {len(documents)} resolution-note documents to {OUT_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
