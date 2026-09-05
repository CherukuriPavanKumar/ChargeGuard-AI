"""Request middleware: correlation IDs, structured logging, latency histograms.

The latency histogram is not decoration.  The system makes a specific,
falsifiable claim -- that the synchronous scoring path stays under a 200 ms p95
budget -- and this module is what lets that claim be checked against live
traffic rather than only against the offline benchmark in ``eval.harness``.

Two things are measured separately and must not be conflated:

* ``Decision.latency_ms`` -- the *decision* path: feature construction, tree
  traversal, calibration, gate evaluation. This is what the SLA is about.
* the histogram here -- the *request* path, which additionally includes JSON
  parsing, Pydantic validation, response serialisation and ASGI overhead.

The second is always larger than the first, and reporting only the first would
be quietly flattering.  ``/v1/metrics/latency`` exposes both.

Storage is a bounded in-process ring buffer.  This is a demonstration service;
a production deployment would export to Prometheus rather than keeping samples
in memory, and the ring buffer is sized so that memory is constant regardless of
uptime.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("sentinel.api")

#: Samples retained per route. Bounded so memory does not grow with uptime.
HISTOGRAM_CAPACITY: int = 5000

#: Header carrying the correlation id, echoed on every response.
REQUEST_ID_HEADER: str = "X-Request-ID"

#: Header carrying server-measured request duration, for client-side checks.
LATENCY_HEADER: str = "X-Response-Time-Ms"


class LatencyHistogram:
    """Thread-safe bounded sample store with percentile queries.

    Percentiles are computed on read by sorting the buffer.  At 5 000 samples
    that is microseconds and happens only when ``/v1/metrics/latency`` is
    polled, which is far cheaper than maintaining an approximate sketch and much
    easier to reason about.
    """

    def __init__(self, capacity: int = HISTOGRAM_CAPACITY) -> None:
        self._samples: dict[str, deque[float]] = {}
        self._capacity = capacity
        self._lock = Lock()

    def record(self, route: str, milliseconds: float) -> None:
        """Record one observation against ``route``."""
        with self._lock:
            bucket = self._samples.get(route)
            if bucket is None:
                bucket = deque(maxlen=self._capacity)
                self._samples[route] = bucket
            bucket.append(milliseconds)

    def _percentiles(self, samples: list[float]) -> dict[str, float]:
        """Compute p50/p95/p99 by linear interpolation between order statistics."""
        if not samples:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "n": 0}

        ordered = sorted(samples)
        n = len(ordered)

        def pct(q: float) -> float:
            if n == 1:
                return round(ordered[0], 4)
            position = q * (n - 1)
            low = int(position)
            high = min(low + 1, n - 1)
            weight = position - low
            return round(ordered[low] * (1 - weight) + ordered[high] * weight, 4)

        return {
            "p50": pct(0.50),
            "p95": pct(0.95),
            "p99": pct(0.99),
            "n": n,
            "min": round(ordered[0], 4),
            "max": round(ordered[-1], 4),
            "mean": round(sum(ordered) / n, 4),
        }

    def snapshot(self) -> dict[str, dict[str, float]]:
        """Return per-route percentiles plus an ``all`` aggregate."""
        with self._lock:
            copied = {route: list(bucket) for route, bucket in self._samples.items()}

        out = {route: self._percentiles(vals) for route, vals in copied.items()}

        combined: list[float] = []
        for values in copied.values():
            combined.extend(values)
        out["all"] = self._percentiles(combined)
        return out

    def reset(self) -> None:
        """Clear every bucket. Used by tests to isolate measurements."""
        with self._lock:
            self._samples.clear()


#: Process-wide histogram for HTTP request durations.
request_histogram = LatencyHistogram()

#: Process-wide histogram for decision-path durations, fed by the score route
#: from ``Decision.latency_ms``. Kept separate so the SLA figure is never
#: silently inflated by transport overhead.
decision_histogram = LatencyHistogram()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a correlation id, time the request, and log the outcome.

    Records latency for failed requests too.  A route that gets slow only when
    it errors is a real and easily-missed production pattern, and excluding
    errors from the histogram would hide it.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
        request.state.request_id = request_id

        route = f"{request.method} {request.url.path}"
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            request_histogram.record(route, elapsed_ms)
            logger.exception(
                "request_failed request_id=%s route=%s duration_ms=%.3f",
                request_id,
                route,
                elapsed_ms,
            )
            raise

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        request_histogram.record(route, elapsed_ms)

        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[LATENCY_HEADER] = f"{elapsed_ms:.3f}"

        logger.info(
            "request request_id=%s route=%s status=%d duration_ms=%.3f",
            request_id,
            route,
            response.status_code,
            elapsed_ms,
        )
        return response


def record_decision_latency(latency_ms: float) -> None:
    """Record a decision-path duration reported by ``Decision.latency_ms``."""
    decision_histogram.record("decision", latency_ms)


def latency_snapshot(sla_ms: float) -> dict[str, object]:
    """Return both histograms plus an explicit SLA verdict.

    The verdict is computed rather than left to the reader, and it is based on
    the decision path -- the thing the budget is actually about.
    """
    decisions = decision_histogram.snapshot()
    decision_all = decisions.get("all", {"p95": 0.0, "n": 0})
    p95 = float(decision_all.get("p95", 0.0))
    n = int(decision_all.get("n", 0))

    return {
        "sla_ms": sla_ms,
        "decision_path": decisions,
        "request_path": request_histogram.snapshot(),
        "within_sla": bool(n > 0 and p95 < sla_ms),
        "observations": n,
        "note": (
            "decision_path is feature construction, inference, calibration and "
            "gate evaluation -- the path the SLA governs. request_path adds JSON "
            "parsing, validation, serialisation and ASGI overhead and is always "
            "larger."
        ),
    }
