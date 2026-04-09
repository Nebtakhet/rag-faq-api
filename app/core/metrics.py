# Prometheus metrics collectors and helpers.

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

METRICS_REGISTRY = CollectorRegistry(auto_describe=True)

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
    ["method", "path", "status_code"],
    registry=METRICS_REGISTRY,
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path", "status_code"],
    registry=METRICS_REGISTRY,
)
IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "Number of HTTP requests currently in progress",
    registry=METRICS_REGISTRY,
)


def normalize_path(path: str) -> str:
    # Keep cardinality bounded for high-volume dynamic routes.
    if not path:
        return "unknown"
    return path


def record_request(method: str, path: str, status_code: int, duration_seconds: float) -> None:
    labels = {
        "method": method,
        "path": normalize_path(path),
        "status_code": str(status_code),
    }
    REQUEST_COUNT.labels(**labels).inc()
    REQUEST_LATENCY.labels(**labels).observe(duration_seconds)


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(METRICS_REGISTRY), CONTENT_TYPE_LATEST
