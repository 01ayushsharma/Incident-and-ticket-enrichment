"""Generate docs/mcp-tool-catalog.md from the live MCP server.

    python scripts/generate_tool_catalog.py

Generated rather than hand-written, because a hand-written tool catalog
drifts from the code the first time someone adds an argument. Everything
here - names, descriptions, schemas, annotations - comes from an actual
`list_tools` call against the real server, and the example invocations are
executed against the real source systems so the responses are genuine.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import anyio

ROOT = Path(__file__).resolve().parents[1]
for relative in (".", "services", "mcp-servers/alarm-management", "apps/backend"):
    sys.path.insert(0, str(ROOT / relative))

OUTPUT = ROOT / "docs" / "mcp-tool-catalog.md"

# One worked example per tool. Chosen to be representative rather than
# minimal - a catalog whose examples all pass `{}` teaches nothing.
EXAMPLES: dict[str, dict[str, Any]] = {
    "search_assets": {"query": "Boiler Feed Pump 101", "limit": 3},
    "get_asset_metadata": {"asset_id": "AST-0001"},
    "list_alarms": {"site": "EastRefinery", "status": ["active"], "page_size": 2},
    "get_alarm_detail": {"alarm_id": "ALM-004935"},
    "rank_active_alarms_by_priority": {"site": "EastRefinery", "top_n": 2},
    "summarize_alarms": {
        "asset_ids": ["AST-0001"],
        "lookback_days": 90,
        "group_by": ["alarm_name"],
        "kpis": ["alarm_count", "recurring_rate"],
    },
    "get_alarm_trends": {
        "asset_ids": ["AST-0001"],
        "lookback_days": 60,
        "bucket": "weekly",
        "metrics": ["alarm_count"],
    },
    "correlate_alarms": {
        "unit": "Unit 5",
        "lookback_days": 150,
        "min_support": 2,
        "severity_threshold": "high",
    },
    "analyze_alarm_floods": {
        "unit": "Unit 2",
        "start_time": "2026-05-01T00:00:00Z",
        "end_time": "2026-07-01T00:00:00Z",
    },
    "find_rationalization_candidates": {
        "unit": "Unit 1",
        "lookback_days": 150,
        "recurrence_threshold": 6,
    },
    "score_alarm_priority": {"alarm_id": "ALM-004935"},
    "recommend_operator_actions": {"alarm_id": "ALM-004935"},
    "compute_kpi": {
        "calculation_type": "nuisance_alarm_score",
        "unit": "Unit 4",
        "lookback_days": 120,
    },
    "list_kpi_definitions": {},
    "find_similar_tickets": {
        "alarm_name": "High Discharge Temperature",
        "asset_id": "AST-0001",
        "resolved_only": True,
        "limit": 2,
    },
    "list_tickets": {"asset_ids": ["AST-0001"], "open_only": True, "page_size": 2},
    "get_ticket": {"key": "INC-1001"},
    "create_ticket": {
        "title": "High Discharge Temperature on Boiler Feed Pump 101",
        "description": "Drafted by the copilot; see the incident body.",
        "approved": True,
        "approval_reference": "docs-example:ALM-000001",
        "priority": "P2",
        "asset_id": "AST-0001",
    },
    "add_ticket_comment": {
        "key": "INC-1001",
        "body": "Procedure OP-114 attached.",
        "approved": True,
    },
    "check_source_systems": {},
}

# Per-tool notes the schema cannot express.
NOTES: dict[str, str] = {
    "rank_active_alarms_by_priority": "Composite tool: one alarm listing plus one priority score per candidate. "
    "`meta.upstream_calls` reports the real cost.",
    "compute_kpi": "Composite tool: generate then execute. Paired because the simulator holds "
    "generated calculations in memory only, so an id handed back separately "
    "could already be gone.",
    "create_ticket": "**The only state-changing tool.** Refuses unless `approved` is true, and "
    "derives an idempotency key from `approval_reference`, so a retried or "
    "repeated approval returns the existing ticket rather than opening a "
    "duplicate.",
    "add_ticket_comment": "State-changing. Not idempotent - a replay would post the comment twice - "
    "so the connector does not retry it.",
    "check_source_systems": "Reports degradation instead of failing: an unreachable source system is a "
    "valid result here, not an error.",
}

# Which source system each tool reaches, and therefore which credential,
# timeout and retry budget applies to it. `check_source_systems` touches
# both; `compute_kpi` and `rank_active_alarms_by_priority` spend the budget
# more than once, which is why the per-tool table states the worst case
# rather than repeating the global default.
SYSTEM: dict[str, str] = {
    "search_assets": "alarm-api",
    "get_asset_metadata": "alarm-api",
    "list_alarms": "alarm-api",
    "get_alarm_detail": "alarm-api",
    "rank_active_alarms_by_priority": "alarm-api",
    "summarize_alarms": "alarm-api",
    "get_alarm_trends": "alarm-api",
    "correlate_alarms": "alarm-api",
    "analyze_alarm_floods": "alarm-api",
    "find_rationalization_candidates": "alarm-api",
    "score_alarm_priority": "alarm-api",
    "recommend_operator_actions": "alarm-api",
    "compute_kpi": "alarm-api",
    "list_kpi_definitions": "alarm-api",
    "find_similar_tickets": "ticketing-api",
    "list_tickets": "ticketing-api",
    "get_ticket": "ticketing-api",
    "create_ticket": "ticketing-api",
    "add_ticket_comment": "ticketing-api",
    "check_source_systems": "both",
}

CREDENTIAL = {
    "alarm-api": "`ALARM_API_TOKEN` (bearer, server-held)",
    "ticketing-api": "`TICKETING_API_TOKEN` (bearer, server-held)",
    "both": "`ALARM_API_TOKEN` and `TICKETING_API_TOKEN` (bearer, server-held)",
}

# Upstream calls per invocation, where it is not one.
CALL_COUNT: dict[str, str] = {
    "rank_active_alarms_by_priority": "1 + 1 per candidate (`top_n`, capped at "
    "`MCP_MAX_RANK_CANDIDATES`)",
    "compute_kpi": "2 (generate, then execute)",
    "check_source_systems": "2 (one health probe per system)",
}

# Tools that are not retried, and why. Everything else is a GET or an
# idempotent POST and inherits the default policy.
NO_RETRY: dict[str, str] = {
    "add_ticket_comment": "no - a replayed comment would be posted twice",
    "create_ticket": "yes - the `Idempotency-Key` makes a replay return the original ticket",
}

# The failure a caller is most likely to hit, per tool.
LIKELY_ERROR: dict[str, str] = {
    "search_assets": "`invalid_input` when `query` is empty.",
    "get_asset_metadata": "`upstream` 404 when `asset_id` does not exist - "
    "resolve the name with `search_assets` first.",
    "get_alarm_detail": "`upstream` 404 for an unknown `alarm_id`.",
    "list_alarms": "`invalid_input` for an inverted time window, or an "
    "`upstream` 422 for an unsupported `sort_by`.",
    "score_alarm_priority": "`upstream` 404 for an unknown `alarm_id`.",
    "recommend_operator_actions": "`upstream` 404 for an unknown `alarm_id`.",
    "compute_kpi": "`upstream` 422 when `calculation_type` is not in `list_kpi_definitions`.",
    "find_similar_tickets": "`invalid_input` when no search criterion is given.",
    "get_ticket": "`upstream` 404 for an unknown ticket key.",
    "create_ticket": "`invalid_input` when `approved` is not true - the gate is "
    "deliberate and no argument bypasses it.",
    "add_ticket_comment": "`invalid_input` when `approved` is not true, or an "
    "`upstream` 404 for an unknown ticket key.",
    "check_source_systems": "none - an unreachable system is reported in the "
    "result rather than raised.",
}

TIMEOUT_NOTE = (
    "`ALARM_API_TIMEOUT_SECONDS` (default 10s) per upstream call, with "
    "`ALARM_API_MAX_RETRIES` (default 3) retries on 408/425/429/5xx and transport "
    "errors, using exponential backoff with full jitter. The MCP client applies its "
    "own `MCP_TOOL_TIMEOUT_SECONDS` (default 30s) across the whole tool call."
)


def _ref_name(schema: dict[str, Any]) -> str | None:
    """The ``$defs`` entry a schema points at, if it points at one."""
    ref = schema.get("$ref")
    if not ref and len(schema.get("allOf", ())) == 1:
        ref = schema["allOf"][0].get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        return ref.split("/")[-1]
    return None


def _fmt_type(schema: dict[str, Any]) -> str:
    """Render a JSON Schema node as a type the reader can act on.

    ``$ref`` is resolved to the referenced model's name, whose fields are
    tabulated under "Nested types" in the same section. Leaving these as
    ``any`` - which is what a naive renderer does, because a ``$ref`` node
    carries no ``type`` of its own - told the reader nothing about the shape
    they would actually receive. Not linked: the same model appears in
    several tool sections, so an anchor would be ambiguous.
    """
    if name := _ref_name(schema):
        return f"`{name}`"
    if "anyOf" in schema:
        parts = [_fmt_type(s) for s in schema["anyOf"] if s.get("type") != "null"]
        return " \| ".join(parts) + " \| null"
    if "enum" in schema:
        return " \| ".join(f"`{v}`" for v in schema["enum"])
    kind = schema.get("type", "any")
    if kind == "array":
        return f"array&lt;{_fmt_type(schema.get('items', {}))}&gt;"
    if kind == "object" and isinstance(schema.get("additionalProperties"), dict):
        return f"object&lt;{_fmt_type(schema['additionalProperties'])}&gt;"
    return kind


def _referenced(schema: dict[str, Any], defs: dict[str, Any]) -> list[str]:
    """Every ``$defs`` name reachable from ``schema``, in discovery order."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        name = _ref_name(node)
        if name and name not in found:
            found.append(name)
            walk(defs.get(name, {}))
        for key, value in node.items():
            if key != "$defs":
                walk(value)

    walk(schema.get("properties", {}))
    return found


def _fmt_default(schema: dict[str, Any]) -> str:
    if "default" not in schema:
        return "—"
    value = schema["default"]
    if value is None:
        return "`null`"
    return f"`{json.dumps(value)}`"


def _truncate(payload: Any, limit: int = 1400) -> str:
    text = json.dumps(payload, indent=2, default=str)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit("\n", 1)[0] + "\n  ... (truncated)"


async def build() -> str:
    import httpx2
    from alarm_api.main import create_app as create_alarm_app
    from alarm_mcp import server as server_module
    from alarm_mcp.config import McpSettings
    from alarm_mcp.runtime import Runtime
    from mcp import ClientSession
    from mcp.shared.memory import create_client_server_memory_streams
    from ticketing_api.main import create_app as create_ticket_app

    from connectors.alarm_client import AlarmApiClient
    from connectors.ticketing_client import TicketingApiClient

    settings = McpSettings()
    runtime = Runtime(
        settings=settings,
        alarm=AlarmApiClient(
            "http://alarm",
            "demo-token",
            client=httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=create_alarm_app()), base_url="http://alarm"
            ),
        ),
        tickets=TicketingApiClient(
            "http://tickets",
            "demo-ticket-token",
            client=httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=create_ticket_app()), base_url="http://tickets"
            ),
        ),
    )
    server_module.set_runtime(runtime)
    server = server_module.build_server(settings)
    low = server._lowlevel_server

    lines: list[str] = []
    # Nested rather than combined: the task group must be entered inside
    # the stream context, and anyio forbids reordering them.
    async with create_client_server_memory_streams() as ((cr, cw), (sr, sw)):  # noqa: SIM117
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(
                lambda: low.run(sr, sw, low.create_initialization_options(), raise_exceptions=False)
            )
            async with ClientSession(cr, cw) as session:
                init = await session.initialize()
                tools = sorted((await session.list_tools()).tools, key=lambda t: t.name)

                lines += _header(init, tools)
                for tool in tools:
                    lines += await _tool_section(session, tool)
            task_group.cancel_scope.cancel()

    server_module.set_runtime(None)
    return "\n".join(lines)


def _header(init: Any, tools: list[Any]) -> list[str]:
    reads = [t for t in tools if not t.annotations or t.annotations.read_only_hint]
    writes = [t for t in tools if t.annotations and t.annotations.read_only_hint is False]

    lines = [
        "# MCP Tool Catalog",
        "",
        "> Generated by `python scripts/generate_tool_catalog.py` from a live",
        "> `list_tools` call against the server, with every example invocation",
        "> executed against the real source systems. Regenerate after changing a",
        "> tool rather than editing this file.",
        "",
        f"**Server:** `{init.server_info.name}` v{init.server_info.version}  ",
        f"**Tools:** {len(tools)} — {len(reads)} read-only, {len(writes)} write  ",
        "**Transports:** streamable HTTP (`MCP_TRANSPORT=http`, default) and stdio  ",
        "**Start independently:** `python -m alarm_mcp`",
        "",
        "## Conventions",
        "",
        "Every tool result carries a `meta` object:",
        "",
        "| Field | Meaning |",
        "|---|---|",
        "| `source_system` | Which source system served the data |",
        "| `operation` | The upstream operation invoked |",
        "| `trace_id` | Correlation id shared with that system's logs |",
        "| `duration_ms` | Wall-clock time for the upstream call(s) |",
        "| `upstream_calls` | Number of HTTP calls made |",
        "| `truncated` | True when the result was capped for context economy |",
        "",
        "### Authentication",
        "",
        "The server holds a separate bearer token per source system "
        "(`ALARM_API_TOKEN`, `TICKETING_API_TOKEN`) and attaches it to every "
        "upstream request. Tokens are never returned in a result, an error, or a "
        "log line. An MCP client presents no source-system credential.",
        "",
        "### Timeouts and retries",
        "",
        TIMEOUT_NOTE,
        "",
        "### Error behaviour",
        "",
        "Failures return an MCP tool error (`isError`) rather than a protocol "
        "error, so the model can read and react to them. Each message is an "
        "actionable sentence followed by a compact JSON diagnosis:",
        "",
        "```",
        "Error executing tool get_asset_metadata: alarm-api.asset_metadata: No asset",
        "with id 'AST-9999'. This will not succeed on retry without changing the",
        'arguments. | diagnosis: {"kind":"upstream","system":"alarm-api",',
        '"status_code":404,"retryable":false,"attempts":1,"trace_id":"..."}',
        "```",
        "",
        "| `kind` | Cause | Retryable |",
        "|---|---|---|",
        "| `invalid_input` | Arguments the schema cannot express as invalid | No |",
        "| `upstream` | The source system returned an error | Per `retryable` |",
        "",
        "### Time windows",
        "",
        "Tools accepting a period take either explicit `start_time`/`end_time` "
        "(ISO-8601) or a relative `lookback_days`. Relative windows resolve against "
        "the **data horizon** read from the Alarm API's health endpoint, not the "
        "wall clock — the simulator's dataset ends at a fixed date, so resolving "
        "against `now` would silently return nothing. Omitting all three gives the "
        "last 90 days.",
        "",
        "---",
        "",
        "## Tools",
        "",
    ]

    lines.append("| Tool | Access | Purpose |")
    lines.append("|---|---|---|")
    for tool in tools:
        write = tool.annotations and tool.annotations.read_only_hint is False
        access = "**write**" if write else "read"
        summary = (tool.description or "").split(". ")[0].strip().rstrip(".")
        # GitHub keeps the underscores in a heading anchor rather than
        # turning them into hyphens; every link in this table used to 404.
        lines.append(f"| [`{tool.name}`](#{tool.name}) | {access} | {summary} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    return lines


async def _tool_section(session: Any, tool: Any) -> list[str]:
    write = tool.annotations and tool.annotations.read_only_hint is False
    schema = tool.input_schema or {}
    properties: dict[str, Any] = schema.get("properties", {})
    required = set(schema.get("required", []))

    lines = [
        f"### `{tool.name}`",
        "",
        ("🔴 **Write operation**" if write else "🟢 Read-only") + "  ",
        f"**Underlying operation:** {_underlying(tool.name)}",
        "",
        tool.description or "",
        "",
    ]

    if note := NOTES.get(tool.name):
        lines += [f"> {note}", ""]

    lines += _behaviour_table(tool.name, write=bool(write))

    lines += ["**Input schema**", ""]
    if properties:
        lines += ["| Argument | Type | Required | Default | Description |", "|---|---|---|---|---|"]
        for name, spec in properties.items():
            description = (spec.get("description") or "").replace("|", "\\|")
            lines.append(
                f"| `{name}` | {_fmt_type(spec)} | "
                f"{'yes' if name in required else 'no'} | "
                f"{_fmt_default(spec)} | {description} |"
            )
    else:
        lines.append("_No arguments._")
    lines.append("")

    output = tool.output_schema or {}
    if output.get("properties"):
        defs: dict[str, Any] = output.get("$defs", {})
        lines += ["**Output schema**", "", "| Field | Type |", "|---|---|"]
        for name, spec in output["properties"].items():
            lines.append(f"| `{name}` | {_fmt_type(spec)} |")
        lines.append("")

        nested = _referenced(output, defs)
        if nested:
            lines += ["<details><summary>Nested types</summary>", ""]
            for name in nested:
                definition = defs.get(name, {})
                lines += [f"**`{name}`**", "", "| Field | Type |", "|---|---|"]
                for field, spec in definition.get("properties", {}).items():
                    lines.append(f"| `{field}` | {_fmt_type(spec)} |")
                lines.append("")
            lines += ["</details>", ""]

    example = EXAMPLES.get(tool.name)
    if example is not None:
        lines += [
            "**Example invocation**",
            "",
            "```json",
            json.dumps({"name": tool.name, "arguments": example}, indent=2),
            "```",
            "",
        ]
        result = await session.call_tool(tool.name, example)
        if result.is_error:
            text = next((c.text for c in result.content if hasattr(c, "text")), "error")
            lines += [
                "**Example response** (this invocation returns an error)",
                "",
                "```",
                text[:600],
                "```",
                "",
            ]
        else:
            lines += [
                "**Example response**",
                "",
                "```json",
                _truncate(result.structured_content),
                "```",
                "",
            ]

    lines += ["---", ""]
    return lines


def _behaviour_table(tool_name: str, *, write: bool) -> list[str]:
    """Auth, timeout, retry and error behaviour for one tool.

    The same facts are stated globally under "Conventions". They are
    repeated per tool because that is where someone integrating a single
    tool actually looks, and because the answers are not uniform: two tools
    are not retried, three spend more than one upstream call, and the
    likely failure differs for every one of them.
    """
    system = SYSTEM.get(tool_name, "alarm-api")
    retry = NO_RETRY.get(
        tool_name, "yes - up to `ALARM_API_MAX_RETRIES` (default 3) on 408/425/429/5xx"
    )
    budget = (
        "`ALARM_API_TIMEOUT_SECONDS` (default 10s) per upstream call; "
        "`MCP_TOOL_TIMEOUT_SECONDS` (default 30s) for the whole tool call"
    )
    return [
        "**Behaviour**",
        "",
        "| | |",
        "|---|---|",
        f"| Source system | `{system}` |",
        f"| Credential | {CREDENTIAL[system]} |",
        f"| Upstream calls | {CALL_COUNT.get(tool_name, '1')} |",
        f"| Timeout | {budget} |",
        f"| Retried | {retry} |",
        f"| State-changing | {'**yes**' if write else 'no'} |",
        f"| Likely error | {LIKELY_ERROR.get(tool_name, 'See the error table under Conventions.')} |",
        "",
    ]


def _underlying(tool_name: str) -> str:
    mapping = {
        "search_assets": "`GET /assets/search` on the Alarm Management API",
        "get_asset_metadata": "`GET /assets/{asset_id}/metadata`",
        "list_alarms": "`GET /alarms`",
        "get_alarm_detail": "`GET /alarms/{alarm_id}`",
        "rank_active_alarms_by_priority": "`GET /alarms` then `POST /alarms/priority-score` per candidate",
        "summarize_alarms": "`POST /alarms/summary`",
        "get_alarm_trends": "`POST /alarms/trends`",
        "correlate_alarms": "`POST /alarms/correlation`",
        "analyze_alarm_floods": "`POST /alarms/flood-analysis`",
        "find_rationalization_candidates": "`POST /alarms/rationalization-candidates`",
        "score_alarm_priority": "`POST /alarms/priority-score`",
        "recommend_operator_actions": "`POST /recommendations/operator-actions`",
        "compute_kpi": "`POST /calculation-code/generate` then `POST /calculation-code/execute`",
        "list_kpi_definitions": "`GET /analytics/kpi-definitions`",
        "find_similar_tickets": "`POST /tickets/search` on the ticketing API",
        "list_tickets": "`GET /tickets`",
        "get_ticket": "`GET /tickets/{key}`",
        "create_ticket": "`POST /tickets` with an `Idempotency-Key` header",
        "add_ticket_comment": "`POST /tickets/{key}/comments`",
        "check_source_systems": "`GET /health` on both source systems",
    }
    return mapping.get(tool_name, "—")


def main() -> None:
    content = anyio.run(build)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({len(content.splitlines())} lines)")


if __name__ == "__main__":
    main()
