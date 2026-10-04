# RAG Design

## 1. Corpus

21 documents, ~15,500 words, in `rag/documents/`. All markdown with YAML
front matter.

| Type | Count | Examples |
|---|---:|---|
| Troubleshooting guide | 6 | TG-201 pump discharge temperature, TG-301 compressor surge |
| Resolution notes | 9 | One per asset class, generated from resolved tickets |
| Operating procedure | 1 | OP-114 boiler feedwater pump |
| Alarm philosophy | 1 | AP-001 severity, floods, rationalization criteria |
| Escalation procedure | 1 | ESC-010 priority matrix and escalation path |
| Safety instruction | 1 | SAF-020 boiler drum level |
| Engineering standard | 1 | STD-040 KPI definitions |
| Maintenance guide | 1 | MNT-030 exchanger fouling |

The nine resolution-note documents are **generated from the 272 resolved
tickets** by `scripts/export_resolution_notes.py`, not written separately.
That matters: a citation the copilot shows carries ticket keys the user can
open in the ticketing system, and the two never disagree. Regenerating after
changing the ticket seed keeps them in step.

The corpus is deliberately written to be *discriminating*. Several documents
cover overlapping equipment, so a retriever that merely matches "pump" will
return the wrong section — which is what makes the relevance tests
meaningful rather than decorative.

## 2. Ingestion

```
discover → extract → parse front matter → chunk → embed → index
```

Run with `make ingest` or `python -m rag.ingestion.cli --rebuild`. Current
output: **202 chunks, ~25,000 tokens, in about 16 seconds.**

### Text extraction

Markdown and plain text are read directly; PDF goes through `pypdf`. A file
type we cannot read is *reported as skipped* rather than silently ignored —
silently dropping a document is how a corpus loses a procedure without
anyone noticing.

### Chunking

**Heading-aware, then size-packed.** These are procedures, so a fixed window
that splits "Step 3" from its heading produces a chunk that is retrievable
but useless — the reader cannot tell what it is a step *of*.

1. Split on markdown headings, building a heading path (`Diagnostic
   sequence > Step 2`). The H1 is excluded because it restates the title.
2. Sections over `RAG_CHUNK_SIZE` (800 chars) are split on paragraph
   boundaries with `RAG_CHUNK_OVERLAP` (120 chars) of overlap.
3. A single paragraph longer than the budget is split on sentences.
4. Fragments under `min_chunk_chars` are merged into the previous chunk.

Each chunk's indexed text is prefixed with `Title > Heading`. This measurably
improves recall for topic-shaped queries, and the prefix is stripped before
the passage is shown to a human or placed in a prompt.

**Chunk ids are content-stable** — `sha1(doc_id | index | text)` — so
re-ingesting an unchanged document upserts in place rather than duplicating.

### Metadata

Front matter is not decoration; it becomes the retrieval filters.

| Field | Used for |
|---|---|
| `doc_id`, `title`, `doc_type` | Citations and `doc_type` filtering |
| `applies_to_asset_types` | Scope filtering (pump, compressor, motor, …) |
| `applies_to_alarms` | Scope filtering by alarm name |
| `applies_to_assets`, `sites`, `units` | Narrower scoping |
| `revision`, `effective_date`, `owner` | Provenance shown in a citation |
| `tags` | Free-text discovery |

Chroma accepts only scalar metadata, so list fields are stored `|`-joined
and matched as substrings. That is adequate because these are controlled
vocabularies, not free text — and a test asserts the flattening holds.

## 3. Retrieval

**Hybrid: dense + lexical, fused by weighted score.**

| Component | Implementation |
|---|---|
| Dense | ChromaDB, cosine, `all-MiniLM-L6-v2` exported to **ONNX** (384-dim) |
| Lexical | BM25 (`rank-bm25`) over the same chunk texts |
| Fusion | `0.6 × dense + 0.4 × lexical` (`RAG_DENSE_WEIGHT`) |

### Why ONNX rather than sentence-transformers

Identical model, but the sentence-transformers route pulls PyTorch: ~2.5 GB
versus ~79 MB. On a project whose packaging requirement is
`docker compose up --build` on an evaluator's machine, that is the
difference between a workable image and an annoying one. Measured quality on
this corpus: 0.72 cosine on a related pair, 0.06 on an unrelated one.

### Why score fusion rather than reciprocal rank fusion

RRF discards the *margin* between hits, and the margin is exactly what the
low-confidence decision needs. "Best 0.31, next 0.29" is a different
situation from "0.84 and 0.22"; RRF makes them look identical.

### Why BM25 is saturated, not max-normalised

Originally BM25 scores were normalised against the best hit in the result
set. That gave the top result a lexical score of 1.0 for **every** query,
including nonsense — so a garbage query could clear the confidence floor on
lexical score alone. Replaced with a saturation curve, `raw / (raw + 8)`,
which is an absolute scale comparable across queries. This was caught by a
test, and it is the single most consequential retrieval fix in the project.

### Top-k and final ranking order

`RAG_TOP_K` (default **5**) chunks are returned. Each retriever is asked for
`top_k × RAG_CANDIDATE_MULTIPLIER` (default 4, so 20) candidates first,
because fusion can only promote a chunk that at least one retriever
surfaced - asking both for exactly 5 would let a chunk that ranks 7th dense
and 2nd lexical disappear before it could be fused.

The order a caller receives is the result of four stages, applied in
sequence:

1. **Fuse.** `0.6 × dense + 0.4 × saturated BM25`, over the union of both
   candidate sets. A chunk found by one retriever only scores 0 for the
   other; it is not penalised further.
2. **Filter.** `doc_type` is removed hard. Asset type, alarm name and site
   adjust the score (`+0.08` per matching dimension) or drop a chunk that
   declares a scope and contradicts the query.
3. **Floor.** Anything below `RAG_MIN_SCORE` (default 0.32) is dropped. If
   nothing survives, the result is empty and `low_confidence` is set - the
   copilot says it does not know rather than citing a weak hit.
4. **Sort and cut.** Descending by the adjusted fused score, then the first
   `top_k`. Ties break on `chunk_id`, so the order is stable across runs.

### Filtering

`doc_type` is a hard filter, applied to **both** retrievers. (It originally
applied only to the Chroma query, so lexical hits bypassed it — also caught
by a test.)

Asset type, alarm name and site are **soft** filters:

- A document that *declares* a scope and contradicts the query is dropped.
- A document that declares no scope is kept, unboosted.
- A document that matches gets +0.08 per matching dimension.

Hard-filtering these would discard AP-001 and ESC-010 — general guidance
that applies to everything and declares no asset type — which are often the
most useful documents in an incident.

## 4. Citations

Every returned chunk produces a citation carrying `marker`, `doc_id`,
`title`, `heading`, `doc_type`, `source_path`, `score` and `excerpt`.

### A worked example

Query, as the orchestrator issues it for the acceptance scenario:

```python
retrieval.retrieve(
    "Boiler Feed Pump 101 high discharge temperature recurring alarm",
    asset_type="pump",
    alarm_name="High Discharge Temperature",
)
```

23 chunks reached the ranking stage; 5 cleared the floor. What came back,
in the order described above:

| # | Doc | Heading | Type | Fused | Dense | Lexical |
|---|---|---|---|---:|---:|---:|
| 1 | `OP-114` | 6. Recurring degradation | operating_procedure | 0.801 | 0.678 | 0.587 |
| 2 | `TG-201` | Related documents | troubleshooting_guide | 0.730 | 0.630 | 0.480 |
| 3 | `TG-201` | Symptom | troubleshooting_guide | 0.729 | 0.637 | 0.467 |
| 4 | `KB-PUMP` | High Discharge Temperature - Cooling water flow loss | resolution_notes | 0.724 | 0.553 | 0.580 |
| 5 | `OP-114` | 4. Abnormal condition response > 4.2 High discharge temperature | operating_procedure | 0.716 | 0.642 | 0.427 |

Two things in that table are worth reading rather than skimming. Every hit
was found by *both* retrievers, which is what a well-formed query over a
well-chunked corpus looks like. And the top hit is not the obvious one: the
troubleshooting guide for this exact alarm ranks second and third, while
the operating procedure's section on *recurrence* ranks first - because the
query said "recurring", and that is the word the question actually turns on.

The citations handed to the model and rendered in the GUI:

```json
[
  {
    "marker": "[1]",
    "doc_id": "OP-114",
    "title": "Boiler Feedwater Pump Operating Procedure",
    "heading": "6. Recurring degradation",
    "doc_type": "operating_procedure",
    "source_path": "OP-114-boiler-feedwater-pump-operating-procedure.md",
    "score": 0.801,
    "excerpt": "Where the same alarm recurs on one machine more than five times in 90 days, raise an engineering review rather than repeatedly acknowledging it. A recurring high discharge temperature or low suction pressure pattern on a critical feedwater pump is a leading indicator of seal or impeller degradation."
  },
  {
    "marker": "[3]",
    "doc_id": "TG-201",
    "title": "Troubleshooting Guide - Pump High Discharge Temperature",
    "heading": "Symptom",
    "doc_type": "troubleshooting_guide",
    "source_path": "TG-201-pump-high-discharge-temperature.md",
    "score": 0.729,
    "excerpt": "Pump discharge temperature has risen above the configured high alarm limit (typically 95 degC on feedwater service, 85 degC on hydrocarbon service) while the pump remains running."
  },
  {
    "marker": "[4]",
    "doc_id": "KB-PUMP",
    "title": "Historical Resolution Notes - Pump",
    "heading": "High Discharge Temperature - Cooling water flow loss",
    "doc_type": "resolution_notes",
    "source_path": "KB-resolution-notes-pump.md",
    "score": 0.724,
    "excerpt": "Occurred 5 time(s) on this asset class. Tickets: INC-1022, INC-1131, INC-1172, INC-1185, INC-1240. **What was found.** Cooling water isolation valve to the seal cooler had been left 60 percent closed after the previous outage. **What resolved it.** Reopened and car-sealed the cooling water isolation valve."
  }
]
```

`[2]` and `[5]` are elided here for length; the full set is what the model
receives. In the answer these appear inline, so a reader can check any
sentence against the document it came from:

> Raise an engineering review rather than continuing to acknowledge the
> alarm: OP-114 sets the threshold at more than five recurrences in 90 days,
> and this asset is past it **[1]**. The immediate checks are the
> minimum-flow recirculation line and cooling water to the seal cooler
> **[3]**. On this asset class the same symptom has resolved five times by
> reopening a cooling water isolation valve left partly closed after an
> outage **[4]**.

A citation is only worth something if it is **checkable**. A test verifies
that the longest sentence of each excerpt appears verbatim in the named
source file, so a citation cannot point somewhere the text does not exist.

The synthesis prompt is given the exact markers available and told to use no
others. If the model cites a marker that was not retrieved, the response is
appended with a visible citation warning and the discrepancy is logged —
fabricated citations are the failure mode that most undermines trust, so
they are surfaced rather than quietly passed through.

## 5. Low-confidence handling

Retrieval returns nothing below `RAG_MIN_SCORE` and sets `low_confidence`.

The floor is **0.32**, chosen from measurement rather than intuition:

| Query | Best score | Outcome |
|---|---:|---|
| boiler feed pump discharge temperature seal | 0.644 | answered |
| EEMUA 191 flood index | 0.533 | answered |
| drum level low response | 0.526 | answered |
| quarterly marketing budget spreadsheet | 0.256 | low confidence |
| tax law and pension contributions | 0.049 | low confidence |

0.32 sits in the gap with margin on both sides. The measurement is recorded
next to the constant in `rag/config.py`, so anyone changing the corpus or
the embedding model knows to re-measure.

When confidence is low the copilot says so — in the answer, in a degradation
notice, and in the GUI — rather than presenting weak matches as guidance.

## 6. Prompt-injection protection

A retrieved chunk is **data**, not instruction. But it arrives in the same
prompt as the real instructions, so something has to check. Four layers, in
`rag/retrieval/sanitize.py`:

1. **Detect and neutralise.** Eight pattern families: instruction override,
   role reassignment, system-prompt probing, secret exfiltration,
   unauthorised tool use, approval bypass, fence escape, dangerous URI.
   Matched spans are replaced, not the whole chunk dropped — a real document
   may contain one bad sentence among useful procedure.
2. **Fence.** Every chunk is wrapped in `<untrusted_document id="{nonce}">`
   with a per-request nonce, so a document cannot close the fence and escape
   into the instruction context.
3. **Instruct.** The system prompt states that fenced content is untrusted
   reference material that cannot change the task or grant permission.
4. **Gate the write.** Ticket creation requires human approval that no
   retrieved text can supply.

**Layer 4 is the one that matters.** Layers 1–3 reduce how often an attempt
lands; only the approval gate bounds the damage if they all fail. That is
stated in the code comments too, rather than implying the regexes are a
solution.

Precision matters as much as recall here: a detector that fires on
"Disregard the reading if the transmitter has failed" is unusable in a plant
corpus. Tests assert both directions — seven attack payloads detected, five
pieces of legitimate engineering prose left alone.

`test-data/injection-corpus/` holds a tampered document used to test the
whole pipeline end to end. It is deliberately **not** in the shipped corpus.

## 7. Index refresh

```bash
make ingest                              # incremental; stable ids upsert
python -m rag.ingestion.cli --rebuild    # drop and rebuild
python -m rag.ingestion.cli --query "…"  # smoke-test retrieval quality
```

In Docker the `rag-ingest` service runs `--rebuild` once at startup, and the
backend waits on `service_completed_successfully` so it never starts against
an empty index. The `rag-index` volume persists the index and the cached
embedding model across restarts.

## 8. Tests

50 tests in `rag/tests/`:

- 12 parametrised relevance cases, one per document, asserting the right
  document *and* the right section
- hybrid behaviour: a rare token ("EEMUA 191") found lexically, a
  vocabulary-free paraphrase found densely
- citation integrity, including verbatim verification against source files
- filter correctness, including that unscoped general guidance survives
- low-confidence and empty-query handling
- injection detection, false-positive avoidance, neutralisation, and fence
  integrity against a forged closing tag

## 9. Known limitations

See [known-limitations.md](known-limitations.md). The main ones: BM25 is
rebuilt in memory from the store on load, which suits a corpus of this size
but not a large one; there is no reranking stage; and chunk-level retrieval
without parent-document expansion occasionally returns a step without its
surrounding procedure.
