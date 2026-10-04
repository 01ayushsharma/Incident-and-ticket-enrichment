"""Bearer-token authentication for the ticketing API.

Deliberately a *different* token from the alarm simulator's, so that the MCP
server has to manage per-source-system credentials rather than one shared
secret - which is what a real multi-source integration looks like.
"""

from __future__ import annotations

import secrets

from fastapi import Request

from connectors.http_errors import AuthenticationError
from ticketing_api.config import get_settings


def require_bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, credential = header.partition(" ")

    if not header:
        raise AuthenticationError(
            "Missing Authorization header. Expected 'Authorization: Bearer <token>'."
        )
    if scheme.lower() != "bearer" or not credential:
        raise AuthenticationError(
            "Malformed Authorization header. Expected 'Authorization: Bearer <token>'.",
            details={"received_scheme": scheme[:32] or "<none>"},
        )
    if not secrets.compare_digest(credential.strip(), get_settings().token):
        raise AuthenticationError("Invalid bearer token.")
    return "ticketing-api-service"
