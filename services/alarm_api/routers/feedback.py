"""Feedback endpoint — lets operators rate recommendation responses."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from alarm_api.domain import feedback as feedback_store
from alarm_api.schemas import FeedbackListResponse, FeedbackRequest, FeedbackResponse
from alarm_api.security import require_bearer_token

router = APIRouter(tags=["feedback"], dependencies=[Depends(require_bearer_token)])


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=201,
    summary="Submit a rating (😄🙂😐🙁😞) and optional comment for a recommendation response",
)
def submit_feedback(req: FeedbackRequest) -> FeedbackResponse:
    """Rate a recommendation response on a 5-point emoji scale and add an
    optional free-text comment.

    ``rating`` must be one of:
    - ``very_happy`` — 😄
    - ``happy`` — 🙂
    - ``neutral`` — 😐
    - ``unhappy`` — 🙁
    - ``very_unhappy`` — 😞
    """
    return feedback_store.submit(req)


@router.get(
    "/feedback",
    response_model=FeedbackListResponse,
    summary="List all submitted feedback, optionally filtered by alarm",
)
def list_feedback(
    alarm_id: str | None = Query(None, description="Filter by alarm id."),
) -> FeedbackListResponse:
    return feedback_store.list_all(alarm_id=alarm_id)
