# API Integration

How the MCP server talks to the two source systems, and how the Alarm
Management API simulator was built from the Postman collections.

## 1. The Alarm Management API contract

The simulator implements the contract defined by the Postman collections in
`postman/`. Those collections are the specification; this is the surface
they define.

Note: `postman/Alarm-API-Simulator.postman_collection.json` and
`postman/scenarios/Alarm-API-Scenarios.postman_collection.json` are
byte-identical, so there are two distinct specifications in that folder, not
three.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness and dataset fingerprint (**unauthenticated**) |
| GET | `/assets/search` | Resolve a name, tag or type to assets |
| GET | `/assets/{asset_id}/metadata` | Full engineering record |
| GET | `/alarms` | Filtered, paginated, sorted alarm list |
| GET | `/alarms/{alarm_id}` | One alarm with asset context |
| POST | `/alarms/summary` | Grouped KPI rollup |
| POST | `/alarms/trends` | Bucketed time series |
| POST | `/alarms/correlation` | Co-occurrence analysis |
| POST | `/alarms/flood-analysis` | EEMUA 191 flood windows |
| POST | `/alarms/rationalization-candidates` | Recurring, stale, chattering alarms |
| POST | `/alarms/priority-score` | Explainable multi-factor score |
| POST | `/recommendations/operator-actions` | Ranked actions and likely causes |
| POST | `/calculation-code/generate` | Source for a named KPI calculation |
| POST | `/calculation-code/execute` | Run a generated calculation |
| GET | `/analytics/kpi-definitions` | KPI catalogue with formulas |

### Authentication

Collection-level bearer token, with `/health` marked `noauth` — so that is
exactly the policy implemented. The token is compared with
`secrets.compare_digest` to avoid leaking its length through timing, and it
never appears in an error or a log line.

```
Authorization: Bearer demo-token
```

### Trace headers

The collections send a bare `trace_id` header, so that spelling is
authoritative. `x-trace-id` and W3C `traceparent` are accepted as aliases
because the MCP server and copilot emit those. Every response echoes
`trace_id`, `x-request-id`, and the client and metadata tags when supplied.

| Header | Direction | Meaning |
|---|---|---|
| `trace_id` | in, echoed | Correlation id across all six processes |
| `x-client-id` | in, echoed | Calling client identity |
| `x-metadata-tag` | in, echoed | Free-form tag for grouping calls |
| `x-request-id` | out | Per-request id, generated if absent |
| `x-response-time-ms` | out | Server-side duration |

### Error envelope

Every non-2xx response — including FastAPI's own validation failures and any
unhandled exception — uses one shape, so the MCP server has one thing to map
rather than three:

```json
{
  "error": {
    "code": "not_found",
    "message": "No asset with id 'AST-9999'.",
    "details": {"asset_id": "AST-9999", "hint": "Use GET /assets/search to resolve a name."}
  },
  "trace_id": "trace-postman-001"
}
```

| Status | `code` | When |
|---|---|---|
| 400 | `bad_request` | Semantically invalid arguments |
| 401 | `unauthenticated` | Missing or wrong bearer token |
| 404 | `not_found` | Unknown asset, alarm or calculation id |
| 422 | `validation_error` | Schema validation failed; `details.fields` lists paths |
| 503 | `service_unavailable` | Injected fault (retryable) |

An unknown `asset_id` returns **404, not an empty list**. An empty result is
indistinguishable from a typo, which makes a multi-step chain very hard to
debug.

### Pagination

`page` and `page_size` on `GET /alarms`, capped at `ALARM_API_MAX_PAGE_SIZE`
(500). Responses carry `total_items`, `total_pages`, `has_next`,
`has_previous`. Sorting is total — the secondary key is always `alarm_id` —
because offset pagination over a partially-ordered set silently drops and
duplicates rows.

## 2. The ticketing API

A second, independent source system with its **own** bearer token, so the
MCP server manages per-system credentials rather than one shared secret.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness (**unauthenticated**) |
| GET | `/tickets` | Filtered list; `asset_ids` repeats for correlated assets |
| POST | `/tickets/search` | Similarity search (read-only despite being POST) |
| GET | `/tickets/fields` | Allowed statuses, priorities, labels, assignees |
| GET | `/tickets/{key}` | One ticket |
| POST | `/tickets` | **Create — the only write in the system** |
| PATCH | `/tickets/{key}` | Update |
| POST | `/tickets/{key}/comments` | Append a comment |

### The write contract

`POST /tickets` requires both:

- `confirmed: true` in the body — a second, independent gate behind the
  copilot's own approval step;
- an `Idempotency-Key` header, 8–128 characters.

A repeated key returns the original ticket with **200** instead of creating a
duplicate with **201**. That status difference is how the connector reports
`created` truthfully; inferring it from timestamps was tried first and was
wrong on replays.

### Similarity search

Blends BM25 over ticket text with agreement on structured fields:

| Signal | Weight |
|---|---:|
| Text (BM25, normalised) | 0.55 |
| Same alarm name | 0.20 |
| Same asset | 0.13 |
| Same asset type | 0.07 |
| Same unit | 0.03 |
| Same site | 0.02 |

Text alone conflates "High Vibration on a fan" with "High Vibration on a
compressor"; structured agreement alone ignores what the operator typed.
`matched_on` reports which signals fired, so the GUI can explain a match
rather than showing an unexplained number.

## 3. The connector layer

`connectors/source_client.py` owns everything cross-cutting. The per-system
clients (`alarm_client.py`, `ticketing_client.py`) are thin: they know URL
shapes and parameter names and nothing else.

### Retry policy

| Aspect | Behaviour |
|---|---|
| Retryable statuses | 408, 425, 429, 500, 502, 503, 504 |
| Retryable transport | Timeouts and connection errors |
| Attempts | `1 + ALARM_API_MAX_RETRIES` (default 4 total) |
| Backoff | Exponential with **full jitter**, capped at 4s |
| Idempotent methods | GET, HEAD, OPTIONS, PUT, DELETE — retried by default |
| Read-only POSTs | Marked `retry_safe=True` explicitly (summary, correlation, search) |
| `POST /tickets` | Retried **because** it carries an idempotency key |
| `POST /comments` | **Not** retried — append-only with no key, a replay would double-post |

Full jitter rather than fixed backoff so that concurrent tool calls do not
retry in lockstep and re-hammer a struggling upstream at the same instant.

### Error normalisation

Every failure becomes a `SourceSystemError` carrying `system`, `operation`,
`status_code`, `code`, `retryable`, `attempts` and `trace_id`. The upstream
`code` and `message` are lifted from the shared error envelope when present,
and the upstream's own `trace_id` is preferred — it is the one in its logs.

### Credential handling

Tokens are attached in `_headers()` and nowhere else. The logging processor
in `connectors/observability.py` redacts any field whose key contains
`token`, `secret`, `password`, `api_key`, `authorization`, `credential`,
`bearer` or `cookie`, recursing into nested structures. A test asserts that
a 401 response contains neither the sent nor the expected token.

## 4. Verifying against the collections

`tests/integration/test_postman_chaining.py` replays all ten CHAIN flows
from `postman/chaining/`, including the variable chaining the collection
performs in its `pm.collectionVariables.set` scripts and the assertions it
makes. If the simulator drifts from the collections, those tests fail.

The dataset is seeded to satisfy every assertion the collections make: named
assets exist, EastRefinery has active alarms, Unit 2 contains a flood
window, motors exist in Unit 5, and compressors are findable by name.

To run the collections directly:

```bash
make run-alarm-api
newman run postman/chaining/Alarm-API-Chaining.postman_collection.json \
  --env-var baseUrl=http://localhost:8000 \
  --env-var auth_token=demo-token
```

## 5. Fault injection

The simulator can fail deliberately, so the MCP server's retry and timeout
handling is exercised rather than merely configured:

```bash
ALARM_API_FAULT_RATE=0.3 ALARM_API_FAULT_DELAY_SECONDS=0.5 make run-alarm-api
```

`/health` is exempt so container health checks stay meaningful.
