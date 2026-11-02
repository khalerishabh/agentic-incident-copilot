from prometheus_client import Counter, Histogram

REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests",
    ["service", "route", "method", "status"],
)

LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["service", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

UPSTREAM_ERRORS = Counter(
    "upstream_errors_total",
    "Failed calls to downstream services",
    ["service", "upstream"],
)
