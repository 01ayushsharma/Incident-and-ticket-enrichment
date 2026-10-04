"""In-memory store for operator feedback on recommendations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from alarm_api.schemas import (
    FEEDBACK_EMOJI,
    FeedbackListResponse,
    FeedbackRequest,
    FeedbackResponse,
)

_feedback: list[FeedbackResponse] = []


def submit(req: FeedbackRequest) -> FeedbackResponse:
    entry = FeedbackResponse(
        feedback_id=str(uuid.uuid4()),
        alarm_id=req.alarm_id,
        rating=req.rating,
        emoji=FEEDBACK_EMOJI[req.rating],
        comment=req.comment,
        created_at=datetime.now(tz=UTC),
    )
    _feedback.append(entry)
    return entry


def list_all(alarm_id: str | None = None) -> FeedbackListResponse:
    items = _feedback if alarm_id is None else [f for f in _feedback if f.alarm_id == alarm_id]
    return FeedbackListResponse(total=len(items), feedback=items)
