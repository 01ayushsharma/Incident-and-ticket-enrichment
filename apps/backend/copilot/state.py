"""Conversation state and the audit trail.

In memory, bounded, and lost on restart. That is a deliberate scope choice
for this assignment rather than an oversight - it is recorded in
docs/known-limitations.md, and the persistence boundary is narrow enough
that swapping in Redis or Postgres touches only this module.

What is *not* optional is the audit trail. The system has one write
operation, and every step from draft to approval to created ticket is
recorded with who did it, when, and against which trace.
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

from copilot.llm.base import LlmMessage
from copilot.models import AuditEntry, TicketDraft


class Conversation:
    """One conversation: its turns, its pending drafts, its audit trail."""

    def __init__(self, conversation_id: str, max_turns: int = 12) -> None:
        self.conversation_id = conversation_id
        self.created_at = datetime.now(UTC)
        self.max_turns = max_turns
        self._turns: list[LlmMessage] = []
        self.drafts: dict[str, TicketDraft] = {}
        self.audit: list[AuditEntry] = []
        self.created_tickets: dict[str, str] = {}  # draft_id -> ticket key

    def add_turn(self, role: str, content: str) -> None:
        self._turns.append(LlmMessage(role=role, content=content))
        # Keep the most recent turns; older context is rarely load-bearing
        # and unbounded history is a cost and a latency problem.
        if len(self._turns) > self.max_turns:
            self._turns = self._turns[-self.max_turns :]

    @property
    def history(self) -> list[LlmMessage]:
        return list(self._turns)

    def record(
        self,
        *,
        actor: str,
        action: str,
        detail: str,
        trace_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            timestamp=datetime.now(UTC),
            conversation_id=self.conversation_id,
            trace_id=trace_id,
            actor=actor,
            action=action,
            detail=detail,
            metadata=metadata or {},
        )
        self.audit.append(entry)
        return entry


class ConversationStore:
    """Bounded, thread-safe conversation registry with LRU eviction."""

    def __init__(self, *, max_conversations: int = 200, max_turns: int = 12) -> None:
        self._lock = threading.RLock()
        self._conversations: OrderedDict[str, Conversation] = OrderedDict()
        self.max_conversations = max_conversations
        self.max_turns = max_turns

    def get_or_create(self, conversation_id: str | None) -> Conversation:
        with self._lock:
            if conversation_id and conversation_id in self._conversations:
                self._conversations.move_to_end(conversation_id)
                return self._conversations[conversation_id]

            new_id = conversation_id or f"conv-{uuid.uuid4().hex[:12]}"
            conversation = Conversation(new_id, max_turns=self.max_turns)
            self._conversations[new_id] = conversation
            while len(self._conversations) > self.max_conversations:
                self._conversations.popitem(last=False)
            return conversation

    def get(self, conversation_id: str) -> Conversation | None:
        with self._lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is not None:
                self._conversations.move_to_end(conversation_id)
            return conversation

    def clear(self) -> None:
        with self._lock:
            self._conversations.clear()

    @property
    def count(self) -> int:
        return len(self._conversations)
