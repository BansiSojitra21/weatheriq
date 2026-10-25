from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Header

from app.core.config import get_settings
from app.core.errors import WeatherIQError


def keys_match(provided: str | None, expected: str) -> bool:
    if not provided:
        return False
    given = provided.encode("utf-8")
    wanted = expected.encode("utf-8")
    if len(given) != len(wanted):
        return False
    return secrets.compare_digest(given, wanted)


def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    settings = get_settings()
    if not keys_match(x_api_key, settings.api_key):
        raise WeatherIQError(
            "A valid X-API-Key header is required for this action.",
            status_code=401,
            code="unauthorized",
        )
