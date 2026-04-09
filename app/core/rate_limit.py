# Shared rate limiter instance for API routes.

from ipaddress import ip_address

from slowapi import Limiter
from starlette.requests import Request

from app.core.config import settings


def _parse_forwarded_for(header_value: str | None) -> str | None:
    if not header_value:
        return None
    candidate = header_value.split(",", 1)[0].strip()
    if not candidate:
        return None
    try:
        ip_address(candidate)
    except ValueError:
        return None
    return candidate


def _trusted_proxy_hosts() -> set[str]:
    return {host.strip() for host in settings.rate_limit_trusted_proxy_ips if host.strip()}


def get_rate_limit_key(request: Request) -> str:
    remote_host = request.client.host if request.client else "unknown"
    if not settings.rate_limit_trust_proxy_headers:
        return remote_host

    trusted = _trusted_proxy_hosts()
    if remote_host not in trusted:
        return remote_host

    forwarded_host = _parse_forwarded_for(request.headers.get("X-Forwarded-For"))
    return forwarded_host or remote_host


limiter = Limiter(
    key_func=get_rate_limit_key,
    storage_uri=settings.redis_url or "memory://",
)
