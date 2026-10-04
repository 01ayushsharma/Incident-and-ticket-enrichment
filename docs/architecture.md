# Architecture

## 1. Shape of the system

Six processes. The copilot holds no HTTP client for any source system; its
only route to alarm and ticket data is the MCP server. That is the single
most important structural property here, and it is enforced by construction
rather than by convention — there is no `httpx` import anywhere under
`apps/backend/copilot/` that points at a source system.

![Architecture](architecture-diagram.png)

```
                            ┌────────────────────────┐
                            │  Streamlit GUI  :8501  │
                            │  chat · draft · trace  │
                            └───────────┬────────────┘
                                        │ HTTP/JSON
                            ┌───────────▼────────────┐
                            │ Copilot backend :8080  │
                            │                        │
                            │  ┌──────────────────┐  │
   AUTH BOUNDARY            │  │ Orchestrator     │  │
   ─────────────            │  │  planner         │  │
   No source-system         │  │  workflow        │  │
   credential exists        │  │  drafting        │  │
   in this process.         │  │  synthesis       │  │
                            │  └───┬──────────┬───┘  │
                            │      │          │      │
                            │  ┌───▼────┐ ┌───▼────┐ │
                            │  │  MCP   │ │  RAG   │ │
                            │  │ client │ │retrieval│ │
                            │  └───┬────┘ └───┬────┘ │
                            └──────┼──────────┼──────┘
                                   │          │
                  MCP (streamable  │          │ in-process
                  HTTP or stdio)   │          │
                            ┌──────▼───────┐  │   ┌──────────────────┐
                            │ MCP server   │  └──►│ Chroma + BM25    │
                            │ :9000        │      │ 202 chunks       │
                            │ 20 tools     │      └────────▲─────────┘
                            │              │               │
                            │ AUTH BOUNDARY│      ┌────────┴─────────┐
                            │ holds both   │      │ Ingestion        │
                            │ credentials  │      │ extract·chunk·   │
                            └───┬──────┬───┘      │ embed·index      │
                                │      │          └────────▲─────────┘
                    Bearer auth │      │ Bearer auth       │
                      + trace   │      │  + trace          │
                   ┌────────────▼─┐ ┌──▼─────────────┐ ┌───┴──────────┐
                   │ Alarm API    │ │ Ticketing API  │ │ rag/documents│
                   │ :8000        │ │ :8100          │ │ 21 markdown  │
                   │ 28 assets    │ │ 272 tickets    │ │ documents    │
                   │ 5,024 alarms │ │ WRITE TARGET   │ └──────────────┘
                   └──────────────┘ └────────────────┘
```

## 2. Layers and what each owns

| Layer | Location | Owns | Deliberately does not own |
|---|---|---|---|
| GUI | `apps/frontend/gui/` | Rendering, the approval form, evidence panels | Any business logic; it calls one HTTP API |
| Orchestration | `apps/backend/copilot/orchestration/` | Planning, tool chaining, drafting, synthesis | HTTP to source systems; tool schemas |
| MCP client | `apps/backend/copilot/mcp_client.py` | Discovery, validation, invocation, the trace | What the tools mean |
| Retrieval | `rag/retrieval/` | Hybrid search, filtering, citations, sanitisation | How documents got there |
| Ingestion | `rag/ingestion/` | Extraction, chunking, metadata, indexing | Query-time concerns |
| MCP server | `mcp-servers/alarm-management/` | Tool contracts, output projection, error mapping | HTTP mechanics; business workflow |
| Connectors | `connectors/` | Auth, retry, timeout, tracing, error envelope | Domain meaning |
| Source systems | `services/` | Alarm and ticket data and analytics | Anything about MCP or the copilot |

Dependencies point one way: GUI → backend → MCP client → MCP server →
connectors → source systems. Nothing below a layer imports anything above it.

## 3. Request flow

A single `POST /chat` with *"Prepare an incident for the highest-priority
active alarm in EastRefinery"*:

1. **Trace established.** `TraceMiddleware` reads or mints a trace id. It is
   attached to every downstream call and appears in all six processes' logs.
2. **Plan.** The orchestrator sends the request plus the discovered tool
   catalog to the LLM, constrained by a JSON schema. The plan is validated
   against the real catalog; a hallucinated tool is dropped, not attempted.
   If the provider is unreachable, the rule-based planner produces the same
   structure and the response is marked degraded.
3. **Chain.** Steps execute in order, threading state:
   `rank_active_alarms_by_priority` → the winning alarm's `alarm_id` feeds
   `get_alarm_detail` and `recommend_operator_actions`; its `asset_id` feeds
   `correlate_alarms`; the correlated asset ids feed `list_tickets`.
   Argument construction is deterministic code, not model output.
4. **Retrieve.** *After* the chain, so the query can be enriched with what
   the tools found — the alarm name, the asset, the likely causes — and the
   metadata filters set from the same place. This ordering is what makes it
   one workflow rather than two demonstrations.
5. **Draft.** Built deterministically from evidence against the ESC-010
   template. The model does not write the ticket body.
6. **Synthesise.** The model receives the structured evidence and the
   retrieved passages, fenced as untrusted data, plus the exact citation
   markers it may use.
7. **Respond.** Answer, alarm, citations, similar tickets, draft, MCP trace,
   degradation notices, timings.

Nothing in that path can create a ticket. Writing requires a second request
to `POST /tickets/approve` carrying a draft id a human has seen.

## 4. Design decisions that shaped the structure

**The MCP server projects onto its own output models.** The tools do not
return the Alarm API's response shapes. `alarm_mcp/models.py` defines what
each tool returns and `projections.py` maps upstream payloads onto it. This
costs a file but buys three things: a source-system change fails loudly in
the MCP server instead of reaching the model as malformed data; an alarm
record drops from eighteen fields to ten, which is real token cost; and the
documented tool contract can stay stable across source-system churn.

**Chaining is deterministic.** The planner chooses which tools run; the
workflow decides how each one's arguments are built from prior results.
Letting a model thread identifiers between calls adds a failure mode and
makes the chain untestable.

**The deterministic LLM provider is a first-class component, not a mock.**
It emits correctly-shaped plans and narratives derived from the prompt, so
the entire system — JSON parsing, plan validation, citation rendering, the
GUI — is exercised without a key. CI runs on it, and so does
`docker compose up` out of the box.

**Failure degrades rather than propagates.** A failed tool, an unreachable
provider, an empty retrieval: each is recorded as a `DegradationNotice` and
surfaced in the response and the GUI. An incident draft missing its
correlation section is still useful; a 500 is not.

**Both source-system credentials live only in the MCP server.** The copilot
process has no alarm or ticketing token. Compromising the copilot does not
yield source-system access.

## 5. Security boundaries

| Boundary | Control |
|---|---|
| GUI → backend | No credentials; the backend is the trust boundary |
| Backend → MCP | Transport-scoped; the backend holds no source credential |
| MCP → sources | Per-system bearer tokens, `compare_digest`, never logged |
| Retrieved documents | Fenced as untrusted data with a per-request nonce, instruction patterns neutralised |
| Ticket creation | Two independent gates: `approved=true` at the tool, `confirmed=true` at the API, plus an `Idempotency-Key` |
| Logs | `connectors/observability.py` redacts any key whose name looks sensitive |
| Query construction | No SQL anywhere; filters are typed Python predicates over immutable records |

## 6. Observability

One structured JSON line per event, carrying the trace id through all six
processes. Fields cover the submission guidelines' list: request id,
conversation id, trace id, MCP server and tool, tool duration and outcome,
API status code, retry count, retrieval query length, retrieved document
ids, retrieval score, and LLM latency and token counts.

A single `trace_id` grep reconstructs an entire request across every process.

## 7. Where persistence would go

Conversations, drafts and the audit trail are in-memory and bounded
(`copilot/state.py`); the ticket store is in-memory
(`ticketing_api/store.py`). Both are documented limitations rather than
oversights, and both are narrow: each is one module behind an interface, so
substituting Postgres or Redis touches nothing else. See
[known-limitations.md](known-limitations.md).
