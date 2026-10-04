"""Operator recommendation endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from alarm_api.domain import analytics, store
from alarm_api.schemas import RecommendationRequest, RecommendationResponse
from alarm_api.security import require_bearer_token
from connectors.http_errors import NotFoundError

router = APIRouter(tags=["recommendations"], dependencies=[Depends(require_bearer_token)])


@router.post(
    "/recommendations/operator-actions",
    response_model=RecommendationResponse,
    summary="Ranked operator actions and likely causes for one alarm",
)
def operator_actions(req: RecommendationRequest) -> RecommendationResponse:
    dataset = store.get_dataset()
    alarm = store.get_alarm(dataset, req.alarm_id)
    if alarm is None:
        raise NotFoundError(
            f"No alarm with id '{req.alarm_id}'.",
            details={"alarm_id": req.alarm_id, "hint": "Resolve an alarm id via GET /alarms."},
        )
    return analytics.operator_recommendations(dataset, alarm, req)
