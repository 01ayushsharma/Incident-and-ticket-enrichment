# Demo Guide

A shot-list for the ≤10-minute walkthrough video, plus the screenshots to
capture. Follow it top to bottom and you will have covered everything the
submission guidelines ask for.

## Before recording

```bash
docker compose up --build        # wait for all six services to report healthy
curl -s localhost:8080/health    # confirm mcp.connected=true and rag.indexed_chunks>0
```

Open <http://localhost:8501>. If you are recording without Docker, start the
five processes with the `make run-*` targets first.

Have a second terminal ready showing `docker compose logs -f backend` — the
structured logs make the trace propagation point land better than describing
it.

---

## Shot list

### 0:00 – 0:40 · What this is

Show the GUI landing page: chats on the left, the prompt and four
suggestions in the middle.

Say: the copilot reaches alarm and ticket data **only** through an MCP
server, grounds every answer in a retrieved document corpus, and cannot
create a ticket without human approval.

Click the status line at the bottom of the sidebar (**All systems
operational**) to open **System status**: backend healthy, MCP server
connected with 20 tools, 202 chunks indexed, LLM provider. Note that the
provider says `fake` and that **no API key is configured** — the whole stack
runs cold.

### 0:40 – 1:20 · MCP tool discovery

Switch to the **MCP tools** tab of the same dialog. Scroll it.

Say: these are discovered at runtime via `list_tools`, not hard-coded. 18
are read-only; two are marked as writes and shown in red. The catalog in
`docs/mcp-tool-catalog.md` is generated from this same call.

*Screenshot 1 — the tool discovery panel.*

### 1:20 – 3:30 · The main scenario

Click the **Prepare an incident** suggestion. It fills the prompt box
rather than sending, so the wording can be edited first; press Enter to run
it (the highest-priority active alarm in EastRefinery).

While it runs, say what is happening: plan, then a chain of MCP calls, then
retrieval scoped by what those calls found.

When it returns, point at the source chips under the answer, then walk
the **Evidence** panel on the right:

- **Alarm panel** — the selected alarm, its P1 band and score, its 90-day
  recurrence, the reading against its limit.
- **MCP trace tab** — expand **Plan** first: intent, source (`llm` or
  `rule_based`), and the ordered steps. Then five tool calls, each with duration, status and
  upstream call count. Point out that
  `rank_active_alarms_by_priority` made ~11 upstream calls inside one tool.
- **Sources tab** — expand one. Show the document id, the heading path,
  the relevance score and the excerpt. Say the excerpt is verified verbatim
  against the source file by a test.
- **Tickets tab** — expand a similar ticket and show its root cause and
  resolution. Note these come from the ticketing system, and the
  resolution-note documents in the corpus are generated from the same
  tickets, so a citation and a ticket never disagree.

*Screenshots 2, 3, 4 — MCP trace, citations, similar tickets.*

### 3:30 – 5:00 · The ticket draft and the approval gate

Scroll to the draft card under the answer.

Say clearly: **nothing has been written.** `POST /chat` produces a draft and
no plan can reach `create_ticket`.

Walk the draft body:
- the alarm, with its reading against the limit and recurrence count;
- the asset and its criticality;
- **the priority derivation** — "ESC-010 matrix gives P2, raised one band
  because 22 occurrences in 90 days under AP-001 §6.1". This is the bit to
  linger on: it shows its working rather than asserting a band.
- likely causes, recommended actions, correlated assets, comparable past
  incidents, and the applicable procedures with citation markers.

Edit the title in place to show the fields are editable. Change priority.

*Screenshot 5 — the editable draft with the priority derivation visible.*

Click **Approve and create ticket**. The draft card is replaced by a
ticket card with the key, priority and status, and the ticket is listed
under **Tickets created** in the sidebar, where it stays after the
conversation moves on. Click it to reopen the ticket and its conversation.

The GUI cannot approve the same draft twice, so show idempotency with the
Postman collection or `curl`: replaying `POST /tickets/approve` returns the
same ticket key with `created=false`, so a repeated approval cannot open a
duplicate.

*Screenshot 6 — created ticket confirmation.*

### 5:00 – 5:40 · Audit trail

Open the **Audit** tab of the Evidence panel. (Rate an answer with the
thumbs first and a sixth `feedback` entry appears, tied to that answer's
trace id.)

Five entries: `message`, `ticket_drafted`, `answered`, `ticket_approved`,
`ticket_created` — each with actor, timestamp and trace id.

*Screenshot 7 — the audit trail.*

### 5:40 – 7:10 · The acceptance scenario

New conversation. Paste:

> Investigate recurring high-severity alarms for Boiler Feed Pump 101 over
> the last 90 days, identify likely contributing factors, retrieve the
> relevant operating procedure, and provide recommended actions with source
> evidence.

Call out each required element as it appears:

1. asset resolution through `search_assets`;
2. multi-step chaining — `summarize_alarms`, `get_alarm_trends`,
   `correlate_alarms`;
3. the 90-day window, extracted from the wording;
4. document retrieval returning **OP-114**, the operating procedure for that
   exact pump;
5. combined reasoning in the answer;
6. citations;
7. the MCP execution trace;
8. and mention that `tests/e2e/test_incident_workflow.py` asserts all of
   this automatically.

*Screenshot 8 — the acceptance scenario with OP-114 cited.*

### 7:10 – 8:10 · Degraded scenarios

**No relevant documents.** Ask: *"What is our policy on expense claims?"*

Show that it reports low confidence, cites nothing, and says so — rather
than inventing an answer. Open the degradation notice.

*Screenshot 9 — the low-confidence response.*

**A source system down.** In the second terminal:

```bash
docker compose stop ticketing-api
```

Ask: *"Find similar historical tickets for a pump vibration problem."*

Show that the answer still arrives, the similar-tickets panel is empty, and
a degradation notice explains why. Restart it:

```bash
docker compose start ticketing-api
```

*Screenshot 10 — a degradation notice.*

### 8:10 – 9:00 · Trace propagation and the MCP server standalone

Switch to the logs terminal. Grep one trace id:

```bash
docker compose logs | grep trace-<id-from-the-GUI>
```

Show the same id appearing in the backend, the MCP server, the alarm API and
the ticketing API.

Then show the MCP server runs independently:

```bash
docker compose exec alarm-mcp python -c "print('server is its own process')"
curl -s localhost:9000/mcp -X POST \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"demo","version":"1"}}}'
```

### 9:00 – 10:00 · Tests and close

```bash
make test
```

Show 325 passing. Mention the split: simulator contract, ticketing, the LLM
adapters, the Postman chaining flows replayed, MCP contracts, MCP over a
real socket, retry and timeout behaviour, orchestration, RAG, and the
end-to-end scenario — **none of which need an API key**.

Close on the two things that matter: MCP and RAG are one workflow, not two
demonstrations; and the only write in the system is gated three ways behind
a human.

---

## Screenshot checklist

Save these to `docs/screenshots/`:

| # | File | Shows |
|---|---|---|
| 1 | `01-tool-discovery.png` | Sidebar with 20 discovered tools |
| 2 | `02-mcp-trace.png` | Execution trace with timings and upstream counts |
| 3 | `03-citations.png` | Expanded citation with excerpt and score |
| 4 | `04-similar-tickets.png` | Historical ticket with root cause |
| 5 | `05-ticket-draft.png` | Editable draft with priority derivation |
| 6 | `06-ticket-created.png` | Created ticket confirmation |
| 7 | `07-audit-trail.png` | Five audit entries |
| 8 | `08-acceptance-scenario.png` | BFP-101 investigation citing OP-114 |
| 9 | `09-low-confidence.png` | Honest "I don't know" |
| 10 | `10-degraded.png` | Degradation notice with a source system down |

## Uploading

Put the video somewhere the evaluator can reach it — a GitHub release asset,
a shared drive link, or an unlisted video platform upload — and link it from
the README's Demo section.
