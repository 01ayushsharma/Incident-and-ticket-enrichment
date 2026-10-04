"""Asset search and metadata endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query

from alarm_api.domain import store
from alarm_api.schemas import AssetMetadata, AssetSearchResponse
from alarm_api.security import require_bearer_token
from connectors.http_errors import NotFoundError

router = APIRouter(tags=["assets"], dependencies=[Depends(require_bearer_token)])


@router.get(
    "/assets/search",
    response_model=AssetSearchResponse,
    summary="Search assets by name, tag, type or identifier",
)
def search_assets(
    query: str = Query(
        ...,
        min_length=1,
        max_length=120,
        description="Free-text fragment matched against asset name, type, tag and id.",
    ),
    site: str | None = Query(None, description="Restrict to a single site."),
    unit: str | None = Query(None, description="Restrict to a single unit."),
    asset_type: str | None = Query(None, description="Restrict to a single asset type."),
    limit: int = Query(10, ge=1, le=100, description="Maximum results to return."),
) -> AssetSearchResponse:
    dataset = store.get_dataset()
    results = store.search_assets(
        dataset, query, site=site, unit=unit, asset_type=asset_type, limit=limit
    )
    return AssetSearchResponse(query=query, count=len(results), results=results)


@router.get(
    "/assets/{asset_id}/metadata",
    response_model=AssetMetadata,
    summary="Full metadata record for one asset",
)
def asset_metadata(
    asset_id: str = Path(..., min_length=1, max_length=64),
) -> AssetMetadata:
    dataset = store.get_dataset()
    asset = store.get_asset(dataset, asset_id)
    if asset is None:
        raise NotFoundError(
            f"No asset with id '{asset_id}'.",
            details={"asset_id": asset_id, "hint": "Use GET /assets/search to resolve a name."},
        )
    return asset
