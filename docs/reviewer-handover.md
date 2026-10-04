# Reviewer handover

What to send alongside the video so someone can test the system without
asking a single follow-up question. Paste the first block into the
submission email; the second is the card to put in the README next to the
video link.

---

## Submission message

```text
Subject: Senior Software Engineer Copilot Assignment Submission

Repository:
https://github.com/01ayushsharma/Incident-and-ticket-enrichment

Selected use case:
Incident and Ticket Enrichment Copilot

MCP server:
Candidate-built, mcp-servers/alarm-management/, 20 tools over the Alarm
Management API and the ticketing system (18 read-only, 2 writes).
Runs independently:
  python -m alarm_mcp                      # streamable HTTP on :9000/mcp
  MCP_TRANSPORT=stdio python -m alarm_mcp  # stdio, for Claude Desktop or the Inspector
Full schemas, auth, error and timeout behaviour with live examples:
docs/mcp-tool-catalog.md (generated from a real list_tools call).

Document RAG:
21 markdown documents (~15,500 words) -> 202 chunks. Heading-aware
chunking, hybrid dense (all-MiniLM-L6-v2 ONNX) + BM25, metadata filtering,
citations with verbatim-checked excerpts, measured low-confidence floor,
prompt-injection defence. Ingest with: make ingest
Design and measurements: docs/rag-design.md

Run instructions:
  docker compose up --build      # then http://localhost:8501
No API key required - the default LLM provider is deterministic, so
orchestration, retrieval, citations and the ticket draft are all live out
of the box. Swap in Groq/Gemini/Ollama/Anthropic/OpenAI via .env if you
prefer; only the prose changes.

Test instructions:
  make test        # 325 tests, no API key needed
  make coverage    # 88% branch coverage over 5,281 statements

Demo:
Video (<10 min): <LINK>
Screenshots: docs/screenshots/
Shot list and timings: docs/demo.md

Known limitations:
- Docker was not installed on the build machine, so `docker compose up`
  has not been run by me; the same topology is verified over real sockets
  and CI exercises the compose stack.
- Conversations, drafts, audit trail and tickets are in memory and lost on
  restart.
- Full list, written plainly: docs/known-limitations.md

Estimated implementation time:
<hours>
```

---

## "Try it yourself" card for the README

**Run it** — `docker compose up --build`, then <http://localhost:8501>.
No API key, no external account, no seed step. The alarm dataset is
generated from a fixed seed (`ALARM_API_SEED=20260501`), so your run
matches the video frame for frame.

Without Docker: `make install`, `make ingest`, then the five `make run-*`
targets (ports 8000, 8100, 9000, 8080, 8501).

**Four prompts, in this order:**

| Ask | What to check |
|---|---|
| *Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last 90 days…* | The acceptance scenario. Asset resolution, an 8-tool chain, OP-114 retrieved and cited, one trace id throughout |
| *Prepare an incident for the highest-priority active alarm in EastRefinery* | The write path: a draft, editable, with the priority derivation shown — then the approval gate |
| *What is our policy on expense claims?* | It cites nothing and says it does not know, rather than inventing an answer |
| *Find similar historical tickets for a pump vibration problem* — with the ticketing API stopped (`docker compose stop ticketing-api`) | The answer still arrives, with a degradation notice naming the failing tool |

**Where the evidence is.** Every answer carries an Evidence panel: the MCP
execution trace with per-tool durations and upstream call counts, document
citations with scores and verbatim excerpts, comparable historical tickets,
and the audit trail. Tool discovery is under the status line in the
sidebar.

**Three claims worth verifying, and where:**

1. *The copilot never touches a source system directly.* No `httpx` client
   or source-system credential exists under `apps/backend/copilot/`; both
   bearer tokens live only in the MCP server.
2. *No ticket can be created without a human.* `POST /chat` returns a draft
   and no plan can reach `create_ticket` — asserted by test. Creation needs
   a second request through three gates, and a replay returns the original
   ticket.
3. *Citations are real.* Each excerpt is asserted verbatim against the file
   it names in `rag/tests/`.

**Verify the MCP server alone**, without the copilot:

```bash
curl -s localhost:9000/mcp -X POST \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"review","version":"1"}}}'
```

**Tests:** `make test` (325, no key required) · `make coverage` ·
CI badge at the top of the README.

**Read in this order if you only have ten minutes with the repo:**
`docs/architecture.md`, `docs/design-decisions.md`,
`docs/known-limitations.md`.
