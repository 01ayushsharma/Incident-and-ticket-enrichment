# Coverage Summary

Generated from `coverage.xml`. Regenerate with `make coverage`; the full
browsable report is written to `htmlcov/` (git-ignored, since it is a build
artefact).

**Overall: 90%** across 5,137 statements,
from **299 tests** — none of which require an API key.

| Area | Statements | Covered | Coverage |
|---|---:|---:|---:|
| `apps/backend` | 1697 | 1438 | 85% |
| `connectors/alarm_client.py` | 59 | 40 | 68% |
| `connectors/http_errors.py` | 69 | 65 | 94% |
| `connectors/observability.py` | 32 | 32 | 100% |
| `connectors/source_client.py` | 118 | 108 | 92% |
| `connectors/ticketing_client.py` | 35 | 30 | 86% |
| `connectors/tracing.py` | 53 | 52 | 98% |
| `mcp-servers/alarm-management` | 675 | 628 | 93% |
| `rag/config.py` | 27 | 26 | 96% |
| `rag/ingestion` | 258 | 187 | 72% |
| `rag/models.py` | 82 | 82 | 100% |
| `rag/retrieval` | 265 | 255 | 96% |
| `services/alarm_api` | 1324 | 1274 | 96% |
| `services/ticketing_api` | 443 | 424 | 96% |
| **Total** | **5,137** | **4,641** | **90%** |

## Reading these numbers

Coverage is uneven on purpose, and the gaps are worth naming rather than
averaging away.

- **The LLM adapters are covered at 80% against local mocks.** No test
  hits a live endpoint, because CI has no keys. The mocks return each
  provider's documented response shape, so the request body, auth header,
  structured-output wiring and error mapping are all asserted; the network
  call itself is the remaining gap.
- **`rag/ingestion/cli.py` is 0%.** It is an argparse entry point; the
  pipeline it calls is covered at 83%.
- **The GUI is not measured at all.** Streamlit pages need a browser driver
  to test meaningfully, so the GUI is verified by hand against the shot list
  in [demo.md](demo.md).
- **The parts that carry the logic are covered heavily**: the simulator's
  domain and analytics, the MCP server's tool contracts and projections, the
  RAG chunker and sanitiser, and the ticket store.

See [known-limitations.md](known-limitations.md) for the full list.
