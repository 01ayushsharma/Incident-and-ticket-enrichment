"""Command line entry point for building the retrieval index.

    python -m rag.ingestion.cli --rebuild
    make ingest

Also usable as a smoke test of retrieval quality::

    python -m rag.ingestion.cli --query "pump discharge temperature rising"
"""

from __future__ import annotations

import argparse
import sys

from connectors.observability import configure_logging
from rag.config import get_settings
from rag.ingestion.pipeline import ingest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rag-ingest",
        description="Build the document retrieval index for the copilot.",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Drop the existing collection before indexing. Use after editing documents.",
    )
    parser.add_argument(
        "--documents",
        help="Override the document directory (default: DOCUMENT_PATH).",
    )
    parser.add_argument(
        "--query",
        help="After indexing, run this query and print the top results.",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Results to show for --query.")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-document log lines.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging("rag-ingest", level="WARNING" if args.quiet else "INFO", fmt="console")

    settings = get_settings()
    if args.documents:
        settings.document_path = args.documents

    try:
        report = ingest(rebuild=args.rebuild, settings=settings)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print()
    print(
        f"Indexed {report.chunks} chunks from {report.documents} documents "
        f"in {report.duration_ms:.0f}ms"
    )
    print(f"  collection : {report.collection}")
    print(f"  index path : {report.index_path}")
    print(f"  tokens     : ~{report.total_tokens_estimate:,}")
    print("  by type    : " + ", ".join(f"{k}={v}" for k, v in sorted(report.by_doc_type.items())))
    if report.skipped:
        print(f"  skipped    : {len(report.skipped)}")
        for entry in report.skipped:
            print(f"      - {entry}")

    if args.query:
        from rag.retrieval.service import RetrievalService

        result = RetrievalService(settings=settings).retrieve(args.query, top_k=args.top_k)
        print()
        print(f'Query: "{args.query}"')
        print(
            f"  best score {result.best_score} | "
            f"low_confidence={result.low_confidence} | "
            f"{result.duration_ms:.0f}ms"
        )
        if result.is_empty:
            print("  no results above the score floor")
        for citation, chunk in zip(result.citations, result.chunks, strict=True):
            print()
            print(f"  {citation.marker} {citation.title} > {citation.heading}")
            print(
                f"      score {chunk.score}  "
                f"(dense {chunk.dense_score}, lexical {chunk.lexical_score}, "
                f"via {'+'.join(chunk.retrieved_by)})"
            )
            print(f"      {citation.excerpt[:220]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
