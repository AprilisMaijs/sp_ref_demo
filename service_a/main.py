
import os
import time
import statistics
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import uvicorn
from typing import Dict, Any
from resilience import ResilientHTTPClient, CircuitBreaker

SERVICE_B_URL = os.getenv("SERVICE_B_URL", "http://service-b:8001")
REQUEST_TIMEOUT_S = float(os.getenv("REQUEST_TIMEOUT_S", "0.5"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))
FAILURE_THRESHOLD = int(os.getenv("FAILURE_THRESHOLD", "5"))
COOL_DOWN_SECONDS = float(os.getenv("COOL_DOWN_SECONDS", "5.0"))

app = FastAPI(title="service-a", version="1.0.0")

breaker = CircuitBreaker(
    failure_threshold=FAILURE_THRESHOLD,
    cool_down_seconds=COOL_DOWN_SECONDS,
)

client = ResilientHTTPClient(
    base_url=SERVICE_B_URL,
    timeout_s=REQUEST_TIMEOUT_S,
    max_retries=MAX_RETRIES,
    retry_backoff_base=0.05,
    breaker=breaker,
)

class ProcessResponse(BaseModel):
    ok: bool
    data: Dict[str, Any] | None
    attempts: int
    breaker_state: str
    total_latency_ms: float
    note: str

class Metrics:
    def __init__(self):
        self.total_requests = 0
        self.total_success = 0
        self.total_fail = 0
        self.latencies_total = []  # total roundtrip latency
        self.latencies_single = [] # first successful attempt latency (inner)

    def record(self, ok: bool, total_latency_ms: float, single_latency_ms: float | None):
        self.total_requests += 1
        if ok:
            self.total_success += 1
        else:
            self.total_fail += 1
        self.latencies_total.append(total_latency_ms)
        if single_latency_ms is not None:
            self.latencies_single.append(single_latency_ms)

    def _p95(self, arr):
        if not arr:
            return 0.0
        srt = sorted(arr)
        idx = int(len(srt) * 0.95) - 1
        idx = max(0, min(idx, len(srt)-1))
        return srt[idx]

    def snapshot(self):
        avg_total = statistics.mean(self.latencies_total) if self.latencies_total else 0.0
        p95_total = self._p95(self.latencies_total)
        avg_single = statistics.mean(self.latencies_single) if self.latencies_single else 0.0
        p95_single = self._p95(self.latencies_single)
        return {
            "a_total_requests": self.total_requests,
            "a_total_success": self.total_success,
            "a_total_fail": self.total_fail,
            "a_avg_total_latency_ms": avg_total,
            "a_p95_total_latency_ms": p95_total,
            "a_avg_single_attempt_latency_ms": avg_single,
            "a_p95_single_attempt_latency_ms": p95_single,
        }

metrics = Metrics()

@app.get("/process", response_model=ProcessResponse)
async def process():
    start = time.perf_counter()
    try:
        data, attempts, breaker_state, total_latency_ms, single_latency_ms = await client.get_json("/work")
        note = "success"
        ok = True
    except Exception as e_tuple:
        if isinstance(e_tuple, tuple):
            e = e_tuple[0]
            attempts = e_tuple[1] if len(e_tuple) > 1 else -1
            breaker_state = e_tuple[2] if len(e_tuple) > 2 else "unknown"
            total_latency_ms = e_tuple[3] if len(e_tuple) > 3 else (time.perf_counter() - start)*1000
            single_latency_ms = None
        else:
            e = e_tuple
            attempts = -1
            breaker_state = breaker.current_state()
            total_latency_ms = (time.perf_counter() - start)*1000
            single_latency_ms = None

        data = None
        note = f"failure: {e}"
        ok = False

    metrics.record(ok, total_latency_ms, single_latency_ms)
    return ProcessResponse(
        ok=ok,
        data=data,
        attempts=attempts,
        breaker_state=breaker_state,
        total_latency_ms=total_latency_ms,
        note=note,
    )

@app.get("/health")
async def health():
    return {"ok": True, "breaker_state": breaker.current_state()}

@app.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    snap = metrics.snapshot()
    lines = [
        "# HELP service_a_requests_total Total requests to service A",
        "# TYPE service_a_requests_total counter",
        f"service_a_requests_total {snap['a_total_requests']}",
        "# HELP service_a_success_total Successful responses from A",
        "# TYPE service_a_success_total counter",
        f"service_a_success_total {snap['a_total_success']}",
        "# HELP service_a_fail_total Failed responses from A",
        "# TYPE service_a_fail_total counter",
        f"service_a_fail_total {snap['a_total_fail']}",
        "# HELP service_a_total_latency_avg_ms Avg end-to-end latency ms",
        "# TYPE service_a_total_latency_avg_ms gauge",
        f"service_a_total_latency_avg_ms {snap['a_avg_total_latency_ms']}",
        "# HELP service_a_total_latency_p95_ms P95 end-to-end latency ms",
        "# TYPE service_a_total_latency_p95_ms gauge",
        f"service_a_total_latency_p95_ms {snap['a_p95_total_latency_ms']}",
        "# HELP service_a_single_attempt_latency_avg_ms Avg single-attempt latency ms",
        "# TYPE service_a_single_attempt_latency_avg_ms gauge",
        f"service_a_single_attempt_latency_avg_ms {snap['a_avg_single_attempt_latency_ms']}",
        "# HELP service_a_single_attempt_latency_p95_ms P95 single-attempt latency ms",
        "# TYPE service_a_single_attempt_latency_p95_ms gauge",
        f"service_a_single_attempt_latency_p95_ms {snap['a_p95_single_attempt_latency_ms']}",
    ]
    return "\n".join(lines) + "\n"

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
