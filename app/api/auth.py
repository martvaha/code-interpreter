import secrets
from typing import Optional

from fastapi import Header, HTTPException

from app.shared.config import get_settings


async def verify_api_key(x_api_key: Optional[str] = Header(None)) -> None:
    """Require a matching x-api-key header when an API key is configured.

    Auth is disabled when ``API_KEY`` is unset. Settings are read at request
    time so the key can be toggled in tests.
    """
    settings = get_settings()
    if settings.API_KEY is None:
        return
    if x_api_key is None or not secrets.compare_digest(x_api_key, settings.API_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")
