"""The deterministic provider.

This is the default and the one CI runs against. It is not a stub that
returns a fixed string: it produces output shaped exactly like a real
model's, derived from the prompt, so that everything downstream - JSON
parsing, plan validation, citation rendering, the GUI - is exercised for
real without a network call or an API key.

Determinism is the property that matters. The same prompt always produces
the same output, so a test can assert on content rather than merely on
"something came back".
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from copilot.llm.base import (
    LlmMessage,
    LlmProvider,
    LlmResponse,
    LlmUsage,
    ProviderKind,
)

# Intent keywords. Scored by how many distinct keywords match, not by
# first hit: a real request often touches several intents at once. The
# acceptance scenario - "investigate recurring alarms ... and retrieve the
# relevant operating procedure" - matches both `investigate_asset` and
# `procedure_lookup`, and first-match-wins picked the wrong one, skipping
# the tool chain entirely. Ties break on the order below.
_INTENT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "create_ticket",
        (
            "create a ticket",
            "raise a ticket",
            "open a ticket",
            "prepare an incident",
            "draft an incident",
            "raise an incident",
            "ticket draft",
            "to the ticket",
            "incident draft",
            "log an incident",
            "prepare a ticket",
        ),
    ),
    (
        "similar_tickets",
        (
            "similar ticket",
            "past ticket",
            "historical ticket",
            "seen before",
            "how was this fixed",
            "previous case",
        ),
    ),
    ("linked_tickets", ("open tickets", "linked ticket", "correlated asset", "related ticket")),
    (
        "procedure_lookup",
        (
            "procedure",
            "troubleshooting",
            "how do i",
            "what should i do",
            "guidance",
            "steps to",
            "philosophy",
            "escalation",
        ),
    ),
    # "likely cause" and "recommended action" sit here rather than under
    # `summarize`: a request for causes and actions needs the recommendation
    # and correlation tools, which the summarize plan does not run.
    (
        "investigate_asset",
        (
            "investigate",
            "recurring",
            "contributing factor",
            "root cause",
            "likely cause",
            "recommended action",
            "over the last",
            "trend",
            "why is",
            "diagnose",
        ),
    ),
    (
        "rank_alarms",
        (
            "highest priority",
            "highest-priority",
            "most urgent",
            "top alarm",
            "worst alarm",
            "active alarm",
            "prioritise",
            "prioritize",
        ),
    ),
    ("summarize", ("summari", "overview", "how many", "breakdown", "kpi", "count")),
)


# Intents that imply a tool chain. When one of these ties with a
# retrieval-only intent, prefer it: doing the tool work and retrieving
# documents is strictly better than retrieving documents alone.
_TOOL_BEARING_INTENTS = frozenset(
    {
        "create_ticket",
        "rank_alarms",
        "investigate_asset",
        "similar_tickets",
        "linked_tickets",
        "summarize",
    }
)


def score_intents(text: str) -> dict[str, int]:
    """How many distinct keywords each intent matches."""
    lowered = text.lower()
    return {
        intent: sum(1 for keyword in keywords if keyword in lowered)
        for intent, keywords in _INTENT_RULES
    }


def _classify(text: str) -> str:
    scores = score_intents(text)

    # `create_ticket` is dominant rather than merely competitive. Its plan is
    # a superset of every other plan - it ranks alarms, correlates, retrieves
    # documents and only then drafts - so when the user has asked for a
    # ticket at all, running it satisfies whatever else they also asked for.
    if scores.get("create_ticket", 0) > 0:
        return "create_ticket"

    best = max(scores.values(), default=0)
    if best == 0:
        return "investigate_asset"

    # Among the joint winners, prefer one that drives tools over one that
    # only reads documents, then fall back to the declared rule order.
    order = [intent for intent, _ in _INTENT_RULES]
    winners = [intent for intent, score in scores.items() if score == best]
    tool_bearing = [i for i in winners if i in _TOOL_BEARING_INTENTS]
    pool = tool_bearing or winners
    return min(pool, key=order.index)


class FakeLlmProvider(LlmProvider):
    """Deterministic provider used by tests, CI and the keyless default run."""

    kind = ProviderKind.FAKE

    def __init__(self, model: str = "deterministic-v1", **kwargs: Any) -> None:
        super().__init__(model, **kwargs)
        self.calls: list[list[LlmMessage]] = []

    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        started = time.perf_counter()
        self.calls.append(messages)

        prompt = "\n".join(m.content for m in messages)
        user_text = next((m.content for m in reversed(messages) if m.role == "user"), "")

        text = (
            self._structured_response(prompt, user_text, json_schema)
            if json_schema
            else self._narrative_response(prompt, user_text)
        )

        return LlmResponse(
            text=text,
            provider=str(self.kind),
            model=self.model,
            usage=LlmUsage(
                input_tokens=max(1, len(prompt) // 4),
                output_tokens=max(1, len(text) // 4),
            ),
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    # ------------------------------------------------------------------ plan
    def _structured_response(self, prompt: str, user_text: str, schema: dict[str, Any]) -> str:
        """Emit JSON conforming to the requested schema.

        Only the plan schema is understood specifically; anything else gets
        a minimal valid instance built from the schema itself, so an
        unforeseen structured call still returns parseable output.
        """
        properties = set((schema or {}).get("properties", {}))
        if {"intent", "steps"} <= properties:
            return json.dumps(self._plan(user_text), indent=2)
        return json.dumps(_minimal_instance(schema), indent=2)

    def _plan(self, user_text: str) -> dict[str, Any]:
        intent = _classify(user_text)
        return {
            "intent": intent,
            "reasoning": (
                f"Matched intent '{intent}' from the request wording. "
                "Deterministic provider: intent selected by keyword rules."
            ),
            "asset_hint": _extract_asset_hint(user_text),
            "site_hint": _extract_site_hint(user_text),
            "alarm_hint": None,
            "lookback_days": _extract_lookback_days(user_text),
            "needs_documents": intent in {"procedure_lookup", "create_ticket", "investigate_asset"},
            "steps": _STEPS_BY_INTENT.get(intent, _STEPS_BY_INTENT["investigate_asset"]),
        }

    # ------------------------------------------------------------- narrative
    def _narrative_response(self, prompt: str, user_text: str) -> str:
        """Compose prose from the evidence already present in the prompt.

        It quotes the citation markers it was given rather than inventing
        them, which is what lets the citation-integrity tests be meaningful
        against this provider.
        """
        markers = sorted(set(re.findall(r"\[\d+\]", prompt)))

        # Only claim a specific alarm when one was actually selected. Scanning
        # the whole prompt would pick up an alarm name from correlation data
        # and assert it as the subject, which is wrong for an investigation
        # that never chose a single alarm.
        selected = _section(prompt, "## Selected alarm")
        alarm = _first_match(selected, r"alarm_name['\"]?\s*[:=]\s*['\"]([^'\"]+)")
        asset = _first_match(selected, r"asset_name['\"]?\s*[:=]\s*['\"]([^'\"]+)")
        band = _first_match(selected, r"priority_band['\"]?\s*[:=]\s*['\"](P[1-4])")
        tickets = sorted(set(re.findall(r"\bINC-\d+\b", prompt)))[:3]

        lines: list[str] = []
        if alarm and asset:
            lines.append(
                f"**{alarm}** on **{asset}**"
                + (f" scores {band} on the priority model." if band else ".")
            )
        else:
            subject = _first_match(prompt, r"# User request\s*\n+(.{0,90})")
            lines.append(
                f"Evidence gathered for: {subject.strip()}"
                if subject
                else "Summary of the retrieved evidence."
            )

        lines.append("")
        lines.append(
            "**Assessment.** The evidence assembled from the alarm system and "
            "the document corpus is set out below; every claim is attributable "
            "to a cited source."
        )

        if markers:
            lines.append("")
            lines.append(
                "**Documented guidance.** The applicable procedures are " + ", ".join(markers) + "."
            )

        if tickets:
            lines.append("")
            lines.append(
                "**Comparable cases.** Previous incidents on similar equipment: "
                + ", ".join(tickets)
                + "."
            )

        if "No relevant documents" in prompt:
            lines.append("")
            lines.append(
                "**Note.** No supporting documents cleared the relevance threshold, "
                "so this answer rests on alarm data alone."
            )

        lines.append("")
        lines.append(
            "_Generated by the deterministic provider. Set LLM_PROVIDER to a real "
            "model for narrative synthesis._"
        )
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Plan templates. These mirror what a competent model produces for each
# intent, so the orchestrator's chaining logic is fully exercised offline.
# --------------------------------------------------------------------------
_STEPS_BY_INTENT: dict[str, list[dict[str, Any]]] = {
    "rank_alarms": [
        {"tool": "search_assets", "why": "Resolve any named asset to an id.", "optional": True},
        {"tool": "rank_active_alarms_by_priority", "why": "Score open alarms in scope."},
        {"tool": "get_alarm_detail", "why": "Enrich the leading alarm."},
        {"tool": "recommend_operator_actions", "why": "Retrieve engineered next steps."},
    ],
    "create_ticket": [
        {
            "tool": "search_assets",
            "why": "Resolve the asset named in the request.",
            "optional": True,
        },
        {"tool": "rank_active_alarms_by_priority", "why": "Select the alarm to raise against."},
        {"tool": "get_asset_metadata", "why": "Enrich the alarm with asset context."},
        {"tool": "get_alarm_detail", "why": "Collect alarm and asset context."},
        {"tool": "correlate_alarms", "why": "Identify contributing and related assets."},
        {"tool": "recommend_operator_actions", "why": "Retrieve recommended actions."},
        {"tool": "find_similar_tickets", "why": "Find how comparable cases were resolved."},
        {"tool": "retrieve_documents", "why": "Attach the applicable procedure."},
        {"tool": "draft_ticket", "why": "Assemble the draft for human approval."},
    ],
    "investigate_asset": [
        {"tool": "search_assets", "why": "Resolve the asset."},
        {"tool": "list_alarms", "why": "Find the recurring high-severity alarm in the window."},
        {"tool": "summarize_alarms", "why": "Quantify the alarm history over the window."},
        {"tool": "get_alarm_trends", "why": "Establish whether it is worsening."},
        {"tool": "correlate_alarms", "why": "Find contributing factors."},
        {
            "tool": "recommend_operator_actions",
            "why": "Retrieve recommended actions.",
            "optional": True,
        },
        {
            "tool": "find_similar_tickets",
            "why": "Find how comparable cases were resolved.",
            "optional": True,
        },
        {"tool": "retrieve_documents", "why": "Retrieve the operating procedure."},
    ],
    "similar_tickets": [
        {"tool": "search_assets", "why": "Resolve the asset.", "optional": True},
        {"tool": "find_similar_tickets", "why": "Search historical resolutions."},
        {"tool": "retrieve_documents", "why": "Attach supporting guidance.", "optional": True},
    ],
    "linked_tickets": [
        {"tool": "search_assets", "why": "Resolve the asset.", "optional": True},
        {"tool": "correlate_alarms", "why": "Identify correlated assets."},
        {"tool": "list_tickets", "why": "Find open tickets across those assets."},
    ],
    "procedure_lookup": [
        {"tool": "retrieve_documents", "why": "Retrieve the applicable procedure."},
    ],
    "summarize": [
        {"tool": "search_assets", "why": "Resolve the asset.", "optional": True},
        {"tool": "summarize_alarms", "why": "Compute the requested rollup."},
    ],
}

_SITES = ("EastRefinery", "NorthPlant", "SouthPlant")


def _extract_asset_hint(text: str) -> str | None:
    """Pull an equipment name out of prose.

    Matches a capitalised noun phrase optionally followed by a unit number,
    which covers 'Boiler Feed Pump 101' and 'Crude Charge Motor 501'.
    """
    match = re.search(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,3}\s+\d{2,4})\b", text)
    if match:
        return match.group(1)
    for word in ("compressor", "pump", "motor", "valve", "boiler", "fan", "exchanger"):
        if word in text.lower():
            return word
    return None


def _extract_site_hint(text: str) -> str | None:
    for site in _SITES:
        if site.lower() in text.lower():
            return site
    return None


def _extract_lookback_days(text: str) -> int | None:
    if match := re.search(r"\blast\s+(\d{1,4})\s*(day|days)\b", text, re.IGNORECASE):
        return int(match.group(1))
    if match := re.search(r"\blast\s+(\d{1,3})\s*(week|weeks)\b", text, re.IGNORECASE):
        return int(match.group(1)) * 7
    if match := re.search(r"\blast\s+(\d{1,2})\s*(month|months)\b", text, re.IGNORECASE):
        return int(match.group(1)) * 30
    return None


def _section(text: str, heading: str) -> str:
    """The body of one '## Heading' block, or empty if absent."""
    start = text.find(heading)
    if start == -1:
        return ""
    rest = text[start + len(heading) :]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def _first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def _minimal_instance(schema: dict[str, Any]) -> Any:
    """Build the smallest value satisfying a JSON schema."""
    kind = schema.get("type", "object")
    if kind == "object":
        required = schema.get("required", list(schema.get("properties", {})))
        return {
            key: _minimal_instance(schema.get("properties", {}).get(key, {})) for key in required
        }
    if kind == "array":
        return []
    if kind == "string":
        return str(schema.get("default", ""))
    if kind == "integer":
        return int(schema.get("default", 0))
    if kind == "number":
        return float(schema.get("default", 0.0))
    if kind == "boolean":
        return bool(schema.get("default", False))
    return None


def deterministic_seed(text: str) -> int:
    """Stable integer from text, for any place needing reproducible variety."""
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
