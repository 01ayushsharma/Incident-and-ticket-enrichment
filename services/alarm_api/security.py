"""Bearer-token authentication for the simulator.

The Postman collections authenticate at collection level with
``Authorization: Bearer {{auth_token}}`` and mark only ``GET /health`` as
``noauth``, so that is exactly the policy implemented here.

The token is compared with :func:`secrets.compare_digest` to avoid leaking
its length or content through response timing, and it is never echoed back
in an error message or a log record.
"""

from __future__ import annotations

import secrets

from fastapi import Request

from alarm_api.config import get_settings
from connectors.http_errors import AuthenticationError


def require_bearer_token(request: Request) -> str:
    """FastAPI dependency enforcing a valid bearer token.

    Returns the authenticated principal, which the simulator models as a
    single service identity. Raises :class:`AuthenticationError` otherwise.
    """
    header = request.headers.get("authorization", "")
    scheme, _, credential = header.partition(" ")

    if not header:
        raise AuthenticationError(
            "Missing Authorization header. Expected 'Authorization: Bearer <token>'.",
        )
    if scheme.lower() != "bearer" or not credential:
        raise AuthenticationError(
            "Malformed Authorization header. Expected 'Authorization: Bearer <token>'.",
            details={"received_scheme": scheme[:32] or "<none>"},
        )

    expected = get_settings().token
    if not secrets.compare_digest(credential.strip(), expected):
        # Deliberately opaque: no hint about which part of the token is wrong.
        raise AuthenticationError("Invalid bearer token.")

    return "alarm-api-service"
