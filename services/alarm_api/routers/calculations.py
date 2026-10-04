"""Calculation-code generation and execution.

The simulator does *not* execute caller-supplied code. ``generate`` returns
the source of a named, pre-vetted calculation for transparency, and
``execute`` runs the corresponding audited Python implementation selected by
identifier. There is no ``eval`` or ``exec`` anywhere in this path.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from alarm_api.domain import analytics, store
from alarm_api.schemas import (
    CalculationExecuteRequest,
    CalculationExecuteResponse,
    CalculationGenerateRequest,
    CalculationGenerateResponse,
    KpiDefinitionsResponse,
)
from alarm_api.security import require_bearer_token
from connectors.http_errors import NotFoundError

router = APIRouter(tags=["analytics"], dependencies=[Depends(require_bearer_token)])


@router.post(
    "/calculation-code/generate",
    response_model=CalculationGenerateResponse,
    summary="Generate the source for a named KPI calculation",
)
def generate_calculation(req: CalculationGenerateRequest) -> CalculationGenerateResponse:
    return analytics.generate_calculation(req.calculation_type, req.filters)


@router.post(
    "/calculation-code/execute",
    response_model=CalculationExecuteResponse,
    summary="Execute a previously generated calculation",
)
def execute_calculation(req: CalculationExecuteRequest) -> CalculationExecuteResponse:
    dataset = store.get_dataset()
    try:
        return analytics.execute_calculation(dataset, req.calculation_id, req.filters)
    except analytics.UnknownCalculationError as exc:
        raise NotFoundError(
            f"No calculation with id '{req.calculation_id}'.",
            details={
                "calculation_id": req.calculation_id,
                "hint": "Calculations are held in memory; call /calculation-code/generate first.",
            },
        ) from exc


@router.get(
    "/analytics/kpi-definitions",
    response_model=KpiDefinitionsResponse,
    summary="Catalogue of supported KPIs and their formulas",
)
def kpi_definitions() -> KpiDefinitionsResponse:
    return KpiDefinitionsResponse(kpis=list(analytics.KPI_DEFINITIONS))
