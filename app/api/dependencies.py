from typing import Annotated

from fastapi import Header, HTTPException

from app.core.config import settings


def require_admin(x_admin_key: Annotated[str | None, Header()] = None) -> None:
    admin_api_key = settings.admin_api_key
    if not admin_api_key:
        raise HTTPException(status_code=500, detail="ADMIN_API_KEY is not configured")
    if x_admin_key != admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")
