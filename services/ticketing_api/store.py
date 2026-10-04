"""In-memory ticket store with BM25-backed similarity search.

The historical corpus is loaded from ``test-data/seed_tickets.json``, a
build-time fixture produced by ``scripts/generate_ticket_seed.py``. Loading a
plain JSON file keeps this service free of any import dependency on the alarm
simulator - they are separate source systems in the architecture and are
wired together only through the MCP layer.

Writes mutate the in-process store and are lost on restart. That is an
explicit, documented limitation: the assignment asks for a mock ticketing
system, not a durable one.
"""

from __future__ import annotations

import builtins
import json
import re
import threading
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from rank_bm25 import BM25Okapi

from ticketing_api.schemas import (
    OPEN_STATUSES,
    Comment,
    CommentCreate,
    Pagination,
    SimilarTicket,
    SimilarTicketRequest,
    Ticket,
    TicketCreate,
    TicketPriority,
    TicketStatus,
    TicketUpdate,
)

_TOKEN = re.compile(r"[a-z0-9]+")

# How much each non-text signal adds to the blended similarity score. Text
# similarity contributes the remainder, so the weights below sum to < 1.
WEIGHT_TEXT = 0.55
WEIGHT_ALARM_NAME = 0.20
WEIGHT_SAME_ASSET = 0.13
WEIGHT_SAME_TYPE = 0.07
WEIGHT_SAME_UNIT = 0.03
WEIGHT_SAME_SITE = 0.02

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "on",
        "in",
        "at",
        "to",
        "for",
        "with",
        "from",
        "by",
        "is",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "as",
        "into",
        "above",
        "below",
        "high",
        "low",
        "alarm",
    ]
)


def tokenise(text: str) -> list[str]:
    """Lowercase alphanumeric tokens with stopwords removed."""
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


class TicketStore:
    """Thread-safe in-memory ticket store."""

    def __init__(self, tickets: list[Ticket], *, source: str = "memory") -> None:
        self._lock = threading.RLock()
        self._tickets: dict[str, Ticket] = {t.key: t for t in tickets}
        self._idempotency: dict[str, str] = {}
        self.source = source
        self._next_number = self._highest_key_number() + 1
        self._rebuild_index()

    # -- construction -------------------------------------------------------
    @classmethod
    def from_file(cls, path: Path) -> TicketStore:
        payload = json.loads(path.read_text(encoding="utf-8"))
        tickets = [Ticket.model_validate(raw) for raw in payload["tickets"]]
        return cls(tickets, source=str(path))

    def _highest_key_number(self) -> int:
        numbers = [
            int(m.group(1)) for key in self._tickets if (m := re.fullmatch(r"INC-(\d+)", key))
        ]
        return max(numbers, default=1000)

    def _rebuild_index(self) -> None:
        """Rebuild the BM25 index. Called on load and after every write."""
        self._ordered: list[Ticket] = sorted(self._tickets.values(), key=lambda t: t.key)
        corpus = [tokenise(self._searchable_text(t)) for t in self._ordered]
        # BM25Okapi rejects an empty corpus, and an all-empty corpus divides
        # by zero on average document length.
        self._bm25 = BM25Okapi(corpus) if any(corpus) else None

    @staticmethod
    def _searchable_text(ticket: Ticket) -> str:
        parts = [
            ticket.title,
            ticket.description,
            ticket.alarm_name or "",
            ticket.asset_name or "",
            ticket.asset_type or "",
            ticket.root_cause or "",
            ticket.resolution or "",
            " ".join(ticket.labels),
        ]
        return " ".join(p for p in parts if p)

    # -- reads --------------------------------------------------------------
    @property
    def count(self) -> int:
        return len(self._tickets)

    def summary(self) -> dict[str, object]:
        by_status: dict[str, int] = {}
        for ticket in self._tickets.values():
            by_status[ticket.status.value] = by_status.get(ticket.status.value, 0) + 1
        return {
            "tickets": len(self._tickets),
            "by_status": by_status,
            "open_tickets": sum(1 for t in self._tickets.values() if t.status in OPEN_STATUSES),
            "source": self.source,
        }

    def get(self, key: str) -> Ticket | None:
        return self._tickets.get(key)

    def list(
        self,
        *,
        status: Iterable[TicketStatus] | None = None,
        priority: Iterable[TicketPriority] | None = None,
        asset_id: str | None = None,
        asset_ids: Iterable[str] | None = None,
        site: str | None = None,
        unit: str | None = None,
        alarm_name: str | None = None,
        label: str | None = None,
        query: str | None = None,
        open_only: bool = False,
        page: int = 1,
        page_size: int = 25,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[list[Ticket], Pagination]:
        status_set = set(status) if status else None
        priority_set = set(priority) if priority else None
        id_set = set(asset_ids) if asset_ids else None
        needle = query.lower() if query else None

        matches: list[Ticket] = []
        for ticket in self._tickets.values():
            if status_set and ticket.status not in status_set:
                continue
            if open_only and ticket.status not in OPEN_STATUSES:
                continue
            if priority_set and ticket.priority not in priority_set:
                continue
            if asset_id and ticket.asset_id != asset_id:
                continue
            if id_set and ticket.asset_id not in id_set:
                continue
            if site and ticket.site != site:
                continue
            if unit and ticket.unit != unit:
                continue
            if alarm_name and (ticket.alarm_name or "").lower() != alarm_name.lower():
                continue
            if label and label not in ticket.labels:
                continue
            if needle and needle not in self._searchable_text(ticket).lower():
                continue
            matches.append(ticket)

        reverse = sort_order.lower() == "desc"
        matches.sort(key=lambda t: (getattr(t, sort_by, t.created_at), t.key), reverse=reverse)

        total = len(matches)
        total_pages = max(1, -(-total // page_size))
        start = (page - 1) * page_size
        return matches[start : start + page_size], Pagination(
            page=page,
            page_size=page_size,
            total_items=total,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1,
        )

    # -- similarity ---------------------------------------------------------
    def find_similar(self, req: SimilarTicketRequest) -> builtins.list[SimilarTicket]:
        """Blend BM25 text similarity with structured-field agreement.

        Text alone conflates "High Vibration on a fan" with "High Vibration on
        a compressor"; structured agreement alone ignores the free text an
        operator actually typed. The blend is what makes the result useful,
        and ``matched_on`` reports which signals fired so the GUI can explain
        the match rather than presenting an unexplained number.
        """
        query_terms = " ".join(part for part in (req.query, req.alarm_name, req.asset_type) if part)
        tokens = tokenise(query_terms)

        # Normalise BM25 scores to [0, 1] against the best hit for this query;
        # raw BM25 is unbounded and not comparable across queries.
        raw_scores: list[float] = []
        if self._bm25 is not None and tokens:
            raw_scores = list(self._bm25.get_scores(tokens))
        best_raw = max(raw_scores, default=0.0)

        results: list[SimilarTicket] = []
        for index, ticket in enumerate(self._ordered):
            if ticket.key in req.exclude_keys:
                continue
            if req.statuses and ticket.status not in req.statuses:
                continue
            if req.resolved_only and not ticket.resolution:
                continue
            if req.site and ticket.site != req.site:
                continue
            if req.unit and ticket.unit != req.unit:
                continue

            matched: list[str] = []
            score = 0.0

            if raw_scores and best_raw > 0:
                text_score = raw_scores[index] / best_raw
                if text_score > 0.02:
                    score += WEIGHT_TEXT * text_score
                    matched.append("text")

            if req.alarm_name and ticket.alarm_name == req.alarm_name:
                score += WEIGHT_ALARM_NAME
                matched.append("alarm_name")
            if req.asset_id and ticket.asset_id == req.asset_id:
                score += WEIGHT_SAME_ASSET
                matched.append("asset")
            if req.asset_type and ticket.asset_type == req.asset_type:
                score += WEIGHT_SAME_TYPE
                matched.append("asset_type")
            if req.unit and ticket.unit == req.unit:
                score += WEIGHT_SAME_UNIT
                matched.append("unit")
            if req.site and ticket.site == req.site:
                score += WEIGHT_SAME_SITE
                matched.append("site")

            if not matched:
                continue
            results.append(
                SimilarTicket(ticket=ticket, score=round(min(score, 1.0), 4), matched_on=matched)
            )

        results.sort(key=lambda r: (-r.score, r.ticket.key))
        return results[: req.limit]

    # -- writes -------------------------------------------------------------
    def create(self, payload: TicketCreate, idempotency_key: str) -> tuple[Ticket, bool]:
        """Create a ticket. Returns ``(ticket, created)``.

        ``created`` is False when ``idempotency_key`` has been seen before, in
        which case the original ticket is returned unchanged. This matters
        because the MCP server retries on 5xx and a retried create must not
        produce a duplicate ticket.
        """
        with self._lock:
            existing_key = self._idempotency.get(idempotency_key)
            if existing_key is not None:
                return self._tickets[existing_key], False

            now = datetime.now(UTC)
            key = f"INC-{self._next_number}"
            self._next_number += 1

            ticket = Ticket(
                key=key,
                title=payload.title,
                description=payload.description,
                status=payload.status,
                priority=payload.priority,
                asset_id=payload.asset_id,
                asset_name=payload.asset_name,
                site=payload.site,
                unit=payload.unit,
                alarm_name=payload.alarm_name,
                labels=sorted(set(payload.labels)),
                assignee=payload.assignee,
                reporter=payload.reporter,
                created_at=now,
                updated_at=now,
                linked_alarm_ids=list(dict.fromkeys(payload.linked_alarm_ids)),
            )
            self._tickets[key] = ticket
            self._idempotency[idempotency_key] = key
            self._rebuild_index()
            return ticket, True

    def update(self, key: str, payload: TicketUpdate) -> Ticket | None:
        with self._lock:
            ticket = self._tickets.get(key)
            if ticket is None:
                return None
            changes = payload.model_dump(exclude_unset=True, exclude={"confirmed"})
            updated = ticket.model_copy(update=changes)
            updated.updated_at = datetime.now(UTC)
            if (
                payload.status in {TicketStatus.RESOLVED, TicketStatus.CLOSED}
                and ticket.resolved_at is None
            ):
                updated.resolved_at = updated.updated_at
                updated.time_to_resolve_hours = round(
                    (updated.updated_at - ticket.created_at).total_seconds() / 3600, 2
                )
            self._tickets[key] = updated
            self._rebuild_index()
            return updated

    def add_comment(self, key: str, payload: CommentCreate) -> Ticket | None:
        with self._lock:
            ticket = self._tickets.get(key)
            if ticket is None:
                return None
            comment = Comment(
                comment_id=f"CMT-{uuid.uuid4().hex[:12]}",
                author=payload.author,
                body=payload.body,
                created_at=datetime.now(UTC),
            )
            updated = ticket.model_copy(
                update={
                    "comments": [*ticket.comments, comment],
                    "updated_at": comment.created_at,
                }
            )
            self._tickets[key] = updated
            return updated

    def distinct_labels(self) -> builtins.list[str]:
        return sorted({label for t in self._tickets.values() for label in t.labels})

    def distinct_assignees(self) -> builtins.list[str]:
        return sorted({t.assignee for t in self._tickets.values() if t.assignee})


# --------------------------------------------------------------------------
# Process-wide store
# --------------------------------------------------------------------------
_store: TicketStore | None = None


def get_store() -> TicketStore:
    global _store
    if _store is None:
        from ticketing_api.config import get_settings

        _store = TicketStore.from_file(Path(get_settings().seed_file))
    return _store


def reset_store() -> None:
    """Drop the store so the next call reloads it from disk (tests)."""
    global _store
    _store = None
