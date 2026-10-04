"""HTTP client for the copilot backend.

Kept separate from the Streamlit page so the GUI's rendering logic can be
read without HTTP concerns interleaved, and so failures arrive as a typed
result the page can render as an error state rather than a stack trace.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx2


@dataclass
class ApiResult:
    """Either a payload or a human-readable reason it is missing."""

    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    status_code: int | None = None

    @property
    def payload(self) -> dict[str, Any]:
        return self.data or {}


class CopilotClient:
    def __init__(self, base_url: str | None = None, timeout: float | None = None) -> None:
        self.base_url = (
            base_url or os.getenv("COPILOT_API_URL") or "http://localhost:8080"
        ).rstrip("/")
        self.timeout = timeout or float(os.getenv("COPILOT_API_TIMEOUT", "120"))

    def _request(self, method: str, path: str, **kwargs: Any) -> ApiResult:
        try:
            with httpx2.Client(base_url=self.base_url, timeout=self.timeout) as client:
                response = client.request(method, path, **kwargs)
        except httpx2.TimeoutException:
            return ApiResult(
                ok=False,
                error=(
                    f"The backend did not respond within {self.timeout:.0f}s. "
                    "A long tool chain can take a while on first run; try again."
                ),
            )
        except httpx2.HTTPError as exc:
            return ApiResult(
                ok=False,
                error=(
                    f"Cannot reach the copilot backend at {self.base_url} "
                    f"({type(exc).__name__}). Is it running?"
                ),
            )

        if response.status_code >= 400:
            detail = _extract_error(response)
            return ApiResult(ok=False, error=detail, status_code=response.status_code)
        return ApiResult(ok=True, data=response.json(), status_code=response.status_code)

    # -- endpoints ----------------------------------------------------------
    def health(self) -> ApiResult:
        return self._request("GET", "/health")

    def tools(self) -> ApiResult:
        return self._request("GET", "/tools")

    def chat(self, message: str, conversation_id: str | None = None) -> ApiResult:
        body: dict[str, Any] = {"message": message}
        if conversation_id:
            body["conversation_id"] = conversation_id
        return self._request("POST", "/chat", json=body)

    def approve(
        self,
        *,
        conversation_id: str,
        draft_id: str,
        approved: bool,
        title: str | None = None,
        description: str | None = None,
        priority: str | None = None,
        assignee: str | None = None,
        labels: list[str] | None = None,
    ) -> ApiResult:
        body: dict[str, Any] = {
            "conversation_id": conversation_id,
            "draft_id": draft_id,
            "approved": approved,
        }
        for key, value in (
            ("title", title),
            ("description", description),
            ("priority", priority),
            ("assignee", assignee),
            ("labels", labels),
        ):
            if value is not None:
                body[key] = value
        return self._request("POST", "/tickets/approve", json=body)

    def feedback(
        self,
        conversation_id: str,
        *,
        trace_id: str,
        rating: str,
        comment: str | None = None,
    ) -> ApiResult:
        body: dict[str, Any] = {"trace_id": trace_id, "rating": rating}
        if comment:
            body["comment"] = comment
        return self._request("POST", f"/conversations/{conversation_id}/feedback", json=body)

    def audit(self, conversation_id: str) -> ApiResult:
        result = self._request("GET", f"/conversations/{conversation_id}/audit")
        # The audit endpoint returns a list; wrap it so ApiResult stays uniform.
        if result.ok and isinstance(result.data, list):
            return ApiResult(ok=True, data={"entries": result.data})
        return result


def _extract_error(response: httpx2.Response) -> str:
    """Pull the message out of the shared error envelope."""
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:200]}"

    envelope = body.get("error") if isinstance(body, dict) else None
    if isinstance(envelope, dict):
        message = envelope.get("message", "")
        details = envelope.get("details") or {}
        fields = details.get("fields")
        if fields:
            problems = "; ".join(
                f"{f.get('location', '?')}: {f.get('message', '')}" for f in fields
            )
            return f"{message} ({problems})"
        if details:
            return f"{message} {details}"
        return message or f"HTTP {response.status_code}"
    return f"HTTP {response.status_code}"
