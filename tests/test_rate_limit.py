from starlette.requests import Request

from app.core import rate_limit as rate_limit_module
from app.core.rate_limit import get_rate_limit_key


def _request(client_host: str | None, forwarded_for: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("utf-8")))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": headers,
        "client": (client_host, 12345) if client_host is not None else None,
        "server": ("testserver", 80),
    }
    return Request(scope)


def test_rate_limit_key_uses_client_host_without_proxy_trust(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit_module.settings, "rate_limit_trust_proxy_headers", False)

    request = _request("127.0.0.1", "203.0.113.10")

    assert get_rate_limit_key(request) == "127.0.0.1"


def test_rate_limit_key_uses_first_forwarded_ip_for_trusted_proxy(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit_module.settings, "rate_limit_trust_proxy_headers", True)
    monkeypatch.setattr(rate_limit_module.settings, "rate_limit_trusted_proxy_ips", ["10.0.0.1"])

    request = _request("10.0.0.1", "203.0.113.10, 70.41.3.18")

    assert get_rate_limit_key(request) == "203.0.113.10"


def test_rate_limit_key_ignores_untrusted_proxy(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit_module.settings, "rate_limit_trust_proxy_headers", True)
    monkeypatch.setattr(rate_limit_module.settings, "rate_limit_trusted_proxy_ips", ["10.0.0.1"])

    request = _request("127.0.0.1", "203.0.113.10")

    assert get_rate_limit_key(request) == "127.0.0.1"


def test_rate_limit_key_ignores_malformed_forwarded_ip(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit_module.settings, "rate_limit_trust_proxy_headers", True)
    monkeypatch.setattr(rate_limit_module.settings, "rate_limit_trusted_proxy_ips", ["10.0.0.1"])

    request = _request("10.0.0.1", "not-an-ip")

    assert get_rate_limit_key(request) == "10.0.0.1"


def test_rate_limit_key_returns_unknown_when_client_missing(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit_module.settings, "rate_limit_trust_proxy_headers", True)
    monkeypatch.setattr(rate_limit_module.settings, "rate_limit_trusted_proxy_ips", ["10.0.0.1"])

    request = _request(None, "203.0.113.10")

    assert get_rate_limit_key(request) == "unknown"
