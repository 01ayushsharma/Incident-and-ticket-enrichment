"""Generate docs/coverage-summary.md from the recorded coverage data.

    make coverage                              # produces .coverage
    python scripts/generate_coverage_summary.py

Generated rather than hand-written, for the reason the numbers needed
reconciling in the first place: a test count and a coverage percentage
copied into four documents by hand diverge the first time either changes.
The README's headline figures come from this file.

One number, one definition. The project measures branch coverage
(`branch = true` in pyproject), so the headline is the branch-inclusive
figure that `make coverage` prints at the end of a run. ``coverage.xml``'s
``line-rate`` attribute is the *statement-only* figure and is a couple of
points higher; both are reported below so neither can be mistaken for the
other again.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "coverage-summary.md"

# How files roll up into the areas the table reports. First match wins, so
# the specific single-file entries precede the directory they live in.
AREAS: list[tuple[str, str]] = [
    ("apps/backend/copilot/llm", "`apps/backend` LLM adapters"),
    ("apps/backend", "`apps/backend` (orchestration, API)"),
    ("connectors/alarm_client.py", "`connectors/alarm_client.py`"),
    ("connectors/http_errors.py", "`connectors/http_errors.py`"),
    ("connectors/observability.py", "`connectors/observability.py`"),
    ("connectors/source_client.py", "`connectors/source_client.py`"),
    ("connectors/ticketing_client.py", "`connectors/ticketing_client.py`"),
    ("connectors/tracing.py", "`connectors/tracing.py`"),
    ("mcp-servers/alarm-management", "`mcp-servers/alarm-management`"),
    ("rag/config.py", "`rag/config.py`"),
    ("rag/ingestion", "`rag/ingestion`"),
    ("rag/models.py", "`rag/models.py`"),
    ("rag/retrieval", "`rag/retrieval`"),
    ("services/alarm_api", "`services/alarm_api`"),
    ("services/ticketing_api", "`services/ticketing_api`"),
]

# Suites, in the order the README lists them, and what each one covers.
SUITES: list[tuple[str, str, str]] = [
    (
        "Simulator contract",
        "tests/unit/test_alarm_api_contract.py tests/unit/test_alarm_api_analytics.py",
        "Auth, trace, pagination, sorting, error envelope, determinism, analytics",
    ),
    ("Ticketing", "tests/unit/test_ticketing_api.py", "Similarity, the write gates, idempotency"),
    (
        "LLM adapters",
        "tests/unit/test_llm_providers.py",
        "Request shape, auth header, structured output, error mapping, retries",
    ),
    (
        "Postman chaining",
        "tests/integration/test_postman_chaining.py",
        "The CHAIN flows replayed with their assertions",
    ),
    (
        "MCP contracts",
        "tests/integration/test_mcp_contracts.py",
        "Discovery, schemas, chaining, error mapping, auth, health",
    ),
    (
        "MCP transport",
        "tests/integration/test_mcp_transport.py",
        "Streamable HTTP over real sockets, trace propagation into the source systems",
    ),
    (
        "Resilience",
        "tests/integration/test_resilience.py",
        "Retry limits, backoff, timeouts, which writes may be replayed",
    ),
    (
        "Orchestration",
        "tests/integration/test_orchestration.py",
        "Intent, chaining, partial failure, LLM degradation, priority matrix",
    ),
    ("RAG", "rag/tests", "Relevance, citations, filters, low confidence, injection"),
    (
        "End-to-end",
        "tests/e2e/test_incident_workflow.py",
        "The acceptance scenario and the full incident-to-ticket journey",
    ),
]

PROSE = """\
## Reading these numbers

Coverage is uneven on purpose, and the gaps are worth naming rather than
averaging away.

- **The LLM adapters are covered against local mocks.** No test hits a live
  endpoint, because CI has no keys. The mocks return each provider's
  documented response shape, so the request body, auth header,
  structured-output wiring and error mapping are all asserted; the network
  call itself is the remaining gap.
- **`rag/ingestion/cli.py` is 0%.** It is an argparse entry point; the
  pipeline it calls is covered well above the project average.
- **The GUI is not measured at all.** Streamlit pages need a browser driver
  to test meaningfully, so the GUI is verified by hand against the shot list
  in [demo.md](demo.md).
- **The parts that carry the logic are covered heavily**: the simulator's
  domain and analytics, the MCP server's tool contracts and projections, the
  RAG chunker and sanitiser, and the ticket store.

See [known-limitations.md](known-limitations.md) for the full list.
"""


def _collect(target: str) -> int:
    """How many tests a path or set of paths collects.

    ``pytest --collect-only -q`` prints one ``<file>: <count>`` line per
    test file, so a suite spanning two files has to be summed rather than
    read off the last line.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            *target.split(),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    total = 0
    matched = False
    for line in result.stdout.splitlines():
        head, _, tail = line.rpartition(":")
        if head.endswith(".py") and tail.strip().isdigit():
            total += int(tail.strip())
            matched = True
    if not matched:
        raise SystemExit(f"could not count tests for {target}:\n{result.stdout[-2000:]}")
    return total


def _area_for(path: str) -> str | None:
    normalised = path.replace("\\", "/")
    for prefix, label in AREAS:
        if normalised.startswith(prefix):
            return label
    return None


def build(data: dict[str, Any]) -> str:
    totals = data["totals"]
    rows: dict[str, dict[str, int]] = {}
    for path, entry in data["files"].items():
        label = _area_for(path)
        if label is None:
            continue
        summary = entry["summary"]
        bucket = rows.setdefault(label, {"statements": 0, "covered": 0, "branches": 0})
        bucket["statements"] += summary["num_statements"]
        bucket["covered"] += summary["covered_lines"]
        bucket["branches"] += summary["num_branches"]

    suite_rows = [(name, _collect(target), covers) for name, target, covers in SUITES]
    total_tests = sum(count for _, count, _ in suite_rows)

    lines = [
        "# Coverage Summary",
        "",
        "> Generated by `python scripts/generate_coverage_summary.py` from the",
        "> `.coverage` data file that `make coverage` writes. Regenerate it",
        "> rather than editing this file, and copy the headline figures from",
        "> here into anything else that quotes them.",
        "",
        f"**Overall: {totals['percent_covered_display']}% branch coverage** across "
        f"{totals['num_statements']:,} statements and {totals['num_branches']:,} branches, "
        f"from **{total_tests} tests** - none of which require an API key.",
        "",
        "Two percentages exist and they are not interchangeable. The headline "
        "above is branch-inclusive, which is what `make coverage` prints and "
        "what this project measures. Statement-only coverage - the `line-rate` "
        "attribute in `coverage.xml` - is "
        f"{totals['percent_statements_covered_display']}%, and branch coverage "
        f"on its own is {totals['percent_branches_covered_display']}%.",
        "",
        "## By area",
        "",
        "| Area | Statements | Covered | Branch coverage |",
        "|---|---:|---:|---:|",
    ]
    for label, bucket in sorted(rows.items()):
        percent = (
            round(100 * bucket["covered"] / bucket["statements"]) if bucket["statements"] else 100
        )
        lines.append(f"| {label} | {bucket['statements']:,} | {bucket['covered']:,} | {percent}% |")
    lines += [
        f"| **Total** | **{totals['num_statements']:,}** | **{totals['covered_lines']:,}** | "
        f"**{totals['percent_covered_display']}%** |",
        "",
        "## By suite",
        "",
        "| Suite | Tests | Covers |",
        "|---|---:|---|",
    ]
    for name, count, covers in suite_rows:
        lines.append(f"| {name} | {count} | {covers} |")
    lines += [f"| **Total** | **{total_tests}** | |", "", PROSE]
    return "\n".join(lines)


def main() -> None:
    import tempfile

    data_file = ROOT / ".coverage"
    if not data_file.exists():
        raise SystemExit("no .coverage data file - run `make coverage` first.")

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        json_path = Path(handle.name)
    subprocess.run(
        [sys.executable, "-m", "coverage", "json", "-q", "-o", str(json_path)],
        cwd=ROOT,
        check=True,
    )
    data = json.loads(json_path.read_text(encoding="utf-8"))
    json_path.unlink(missing_ok=True)

    OUTPUT.write_text(build(data), encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
