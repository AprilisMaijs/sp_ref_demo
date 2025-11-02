
import os
import random
import time
import statistics
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import uvicorn
import asyncio
import socket
from typing import Dict

app = FastAPI(title="service-b", version="1.0.0")

# Config via env
FAILURE_RATE = float(os.getenv("FAILURE_RATE", "0.3"))  # 30% chance of 500
MAX_LATENCY_MS = int(os.getenv("MAX_LATENCY_MS", "800"))  # up to 800ms extra delay
BASE_LATENCY_MS = int(os.getenv("BASE_LATENCY_MS", "30"))  # base work

# basic in-memory metrics
class Metrics:
    def __init__(self):
        self.total_requests = 0
        self.total_success = 0
        self.total_fail = 0
        self.latencies = []

    def record(self, ok: bool, latency_s: float):
        self.total_requests += 1
        if ok:
            self.total_success += 1
        else:
            self.total_fail += 1
        self.latencies.append(latency_s)

    def snapshot(self) -> Dict[str, float]:
        avg = statistics.mean(self.latencies) if self.latencies else 0.0
        p95 = 0.0
        if self.latencies:
            sorted_lats = sorted(self.latencies)
            idx = int(len(sorted_lats) * 0.95) - 1
            idx = max(0, min(idx, len(sorted_lats)-1))
            p95 = sorted_lats[idx]
        return {
            "total_requests": self.total_requests,
            "total_success": self.total_success,
            "total_fail": self.total_fail,
            "avg_latency_ms": avg * 1000,
            "p95_latency_ms": p95 * 1000,
        }

metrics = Metrics()

class WorkResponse(BaseModel):
    status: str
    host: str
    processing_ms: int

@app.get("/work", response_model=WorkResponse)
async def do_work():
    start = time.perf_counter()

    # simulate base work
    base_delay = BASE_LATENCY_MS / 1000.0
    await asyncio.sleep(base_delay)

    # simulate random extra latency
    extra_delay_ms = random.randint(0, MAX_LATENCY_MS)
    await asyncio.sleep(extra_delay_ms / 1000.0)

    # simulate random failure
    failed = random.random() < FAILURE_RATE
    latency_s = time.perf_counter() - start
    metrics.record(not failed, latency_s)

    if failed:
        # FastAPI will turn this into 500
        # We raise RuntimeError instead of HTTPException on purpose
        # to simulate "unexpected" server crash behavior.
        raise RuntimeError("simulated internal failure")

    return WorkResponse(
        status="ok",
        host=socket.gethostname(),
        processing_ms=int(latency_s * 1000),
    )

@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    snap = metrics.snapshot()
    lines = [
        "# HELP service_b_requests_total Total requests to service B",
        "# TYPE service_b_requests_total counter",
        f"service_b_requests_total {snap['total_requests']}",
        "# HELP service_b_success_total Successful responses from service B",
        "# TYPE service_b_success_total counter",
        f"service_b_success_total {snap['total_success']}",
        "# HELP service_b_fail_total Failed responses from service B",
        "# TYPE service_b_fail_total counter",
        f"service_b_fail_total {snap['total_fail']}",
        "# HELP service_b_latency_avg_ms Average latency ms for service B",
        "# TYPE service_b_latency_avg_ms gauge",
        f"service_b_latency_avg_ms {snap['avg_latency_ms']}",
        "# HELP service_b_latency_p95_ms P95 latency ms for service B",
        "# TYPE service_b_latency_p95_ms gauge",
        f"service_b_latency_p95_ms {snap['p95_latency_ms']}",
    ]
    return "\n".join(lines) + "\n"

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8001")),
        reload=False,
    )
