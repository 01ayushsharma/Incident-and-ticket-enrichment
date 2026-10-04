# Design Decisions

Decisions where a reasonable alternative existed, with the reasoning and
what it cost.

---

## 1. The copilot has no HTTP client for any source system

**Decision.** All alarm and ticket access goes through the MCP server. There
is no `httpx` call to a source system anywhere under `apps/backend/copilot/`.

**Alternative.** Call the APIs directly for "simple" operations and use MCP
for the rest — tempting, because `search_assets` is one GET.

**Why not.** The moment one path bypasses MCP, the MCP integration becomes
decorative. It also splits credential handling across two processes. The
architecture test for this is simply that removing the MCP server leaves the
copilot with no data at all, which `test_a_failing_source_system_is_reported`
demonstrates.

**Cost.** Slightly more indirection for trivial calls.

---

## 2. The deterministic LLM provider is a component, not a mock

**Decision.** `LLM_PROVIDER=fake` is the default. It produces correctly
shaped plans and narratives derived from the prompt.

**Alternative.** Require an API key and mock the provider in tests.

**Why not.** Three things follow from the default being real. CI runs the
entire suite — including orchestration and end-to-end — with no secret,
which the guidelines effectively require since GitHub Actions has none. An
evaluator gets a working stack from `docker compose up` with nothing to
configure. And the degraded path is exercised continuously rather than being
a code path nobody runs.

The provider is not a stub returning fixed strings: it classifies intent by
scored keyword matching, extracts asset and time hints, emits schema-valid
plans, and quotes the citation markers it was given. Everything downstream —
JSON parsing, plan validation, citation checking, the GUI — is fully
exercised.

**Cost.** A few hundred lines that a real model would make unnecessary, and
prose that is templated rather than written.

---

## 3. Tool chaining is deterministic; only planning uses the model

**Decision.** The planner chooses *which* tools run. `workflow.py` decides
how each tool's arguments are built from prior results.

**Alternative.** Give the model the tools and let it drive the loop.

**Why not.** Threading an `asset_id` from one call into the next is not a
judgement call; it is plumbing. Delegating it adds a failure mode, costs a
round trip per step, and makes the chain untestable — you cannot assert that
correlation was scoped to the right asset if a model decided it. With it in
code, `test_output_of_one_tool_becomes_the_input_of_the_next` asserts exactly
that.

**Cost.** Less flexible than an open agent loop. A genuinely novel request
falls back to the closest matching plan rather than improvising.

**Follow-up: the model's plan is completed, not trusted as-is.** Run against
a real model (Groq, `gpt-oss-120b`), the planner's output was often
technically valid but incomplete: it "preferred few steps" and omitted the
similar-ticket search and the procedure from an incident draft. It also
named `list_alarms`, which is an MCP tool the workflow had no step for, and
listed `draft_ticket` first. `planner.complete_plan` now merges the intent's
template steps into the model's plan. It drops steps the workflow cannot
run (reported, not silently ignored) and sorts the result by
`workflow.STEP_ORDER`, so a step always runs after the step producing its
input. The model still chooses the intent, the hints and any extra steps.
It can no longer remove a step the business flow requires.
`test_a_terse_model_plan_still_runs_the_whole_incident_workflow` reproduces
the observed plan.

---

## 4. The MCP server projects onto its own output models

**Decision.** `alarm_mcp/models.py` defines what each tool returns;
`projections.py` maps upstream payloads onto it. Tools do not return the
Alarm API's response shapes.

**Alternative.** Pass the upstream JSON through.

**Why.** Three benefits. A source-system field change fails validation in
the MCP server rather than reaching the model as malformed data. An alarm
record drops from eighteen fields to ten, which is real token cost on every
call. And the documented tool contract stays stable across source-system
churn.

**Cost.** Two extra files and a mapping to maintain per tool.

---

## 5. Both source-system credentials live only in the MCP server

**Decision.** Separate tokens per system, held by the MCP server. The
copilot process holds neither.

**Why.** It is what a real multi-source integration looks like, and it makes
the boundary meaningful: compromising the copilot yields no source-system
access. A shared token would have been simpler and would have taught nothing.

---

## 6. Three independent gates on the one write

**Decision.** Ticket creation requires: `approved=true` at the MCP tool,
`confirmed=true` at the ticketing API, and an `Idempotency-Key` header.

**Alternative.** One check at the orchestration layer.

**Why not.** The guidelines list "write operations without approval" as a red
flag, and a single check in the layer most likely to be refactored is thin.
The MCP-level gate also holds if the server is driven by a different client —
Claude Desktop, the MCP Inspector — which a copilot-only check would not.

The idempotency key is not ceremony. The connector retries on 5xx, so a
timeout after the server committed would otherwise open a second ticket. The
key is derived from the conversation and alarm, so a replayed approval
returns the original ticket. `test_repeating_an_approval_does_not_duplicate_the_ticket`
covers it.

---

## 7. The ticket body is generated deterministically, not by the model

**Decision.** `drafting.py` builds the draft from evidence against the
ESC-010 template. The model writes the chat answer, not the ticket.

**Why.** A ticket is an operational record that outlives the conversation.
Every line should be traceable to a tool result or a cited document, and
ESC-010 §6 already specifies exactly what a ticket must contain — that is a
template, not a generation task. It also means the draft is identical
whether or not a model is available.

The priority derivation shows its working: the ESC-010 matrix result, then
each modifier applied, then the alarm system's own score. An operator can
disagree with a step rather than with a number.

---

## 8. A failed step degrades the answer; it does not end the run

**Decision.** Every failure becomes a `DegradationNotice` surfaced in the
response and the GUI. The workflow continues.

**Why.** An incident draft missing its correlation section is still useful.
A 500 because one of seven tools timed out is not. The distinction matters
most in exactly the situation where the copilot is most valuable — when
something is already wrong.

**Cost.** Callers must read `degraded`, and a partial answer can look
complete if they do not. Mitigated by surfacing notices prominently in the
GUI rather than burying them.

---

## 9. Retrieval runs *after* the tool chain

**Decision.** Documents are retrieved once the tools have resolved the alarm
and asset, using them to enrich the query and set the filters.

**Alternative.** Retrieve from the user's question in parallel with the tools.

**Why not.** Parallel retrieval would be faster, but the question often does
not name the alarm — "the highest-priority active alarm in EastRefinery"
contains nothing to retrieve on. Retrieving after the chain is what makes
this one workflow rather than two demonstrations running side by side.

**Cost.** Roughly 300–500 ms of serialisation.

---

## 10. The dataset is deterministic and fixed in time

**Decision.** The simulator's dataset derives from a seed and spans fixed
absolute dates (2026-04-01 to 2026-09-30) rather than a window relative to
now.

**Why.** It makes the Postman collections and the test suite reproducible on
any machine on any day. Tests can assert concrete values rather than only
response shapes.

**Consequence.** "The last 90 days" must resolve against the **data
horizon**, not the wall clock, or every relative query returns nothing. The
MCP server reads the horizon from the Alarm API's health endpoint and caches
it. This is the kind of detail that silently breaks a demo three months after
it is written.

---

## 11. ONNX embeddings rather than sentence-transformers

**Decision.** ChromaDB's default embedding function — the same
`all-MiniLM-L6-v2`, exported to ONNX.

**Why.** sentence-transformers pulls PyTorch: ~2.5 GB against ~79 MB. The
packaging requirement is that an evaluator runs `docker compose up --build`,
and image size is part of whether that is pleasant. Measured quality is
unchanged for this corpus.

---

## 12. In-memory state, with the boundary drawn narrowly

**Decision.** Conversations, drafts, the audit trail and the ticket store are
in memory and lost on restart.

**Why.** The assignment asks for a mock ticketing system, and a database
would add a service, a migration story and a persistence layer without
demonstrating anything the rubric asks for.

**How the cost is contained.** Each is one module behind an interface —
`copilot/state.py` and `ticketing_api/store.py` — so substituting Redis or
Postgres touches nothing else. Recorded in
[known-limitations.md](known-limitations.md) rather than left implicit.

---

## 13. `asyncio_mode = "strict"`, with anyio for the integration suite

**Decision.** pytest-asyncio in strict mode; the integration and e2e suites
use `@pytest.mark.anyio`.

**Why.** The test harness runs a real MCP session inside an anyio task group.
pytest-asyncio's auto mode finalises async fixtures in a different task,
which anyio forbids — producing "Attempted to exit cancel scope in a
different task". anyio's own plugin keeps fixture and test in one task.

Recorded because it looks like an arbitrary config choice and is not.

---

## 14. Generated documentation where drift is likely

**Decision.** `docs/mcp-tool-catalog.md` and
`docs/architecture-diagram.png` are generated by scripts.

**Why.** A hand-written tool catalog drifts the first time someone adds an
argument. The catalog comes from a live `list_tools` call with every example
executed against the real source systems, so it cannot describe a tool that
does not exist. The diagram is matplotlib rather than a drawing, so it cannot
silently diverge from the code either.

**Cost.** Two scripts to maintain, and a regeneration step after changing a
tool.
