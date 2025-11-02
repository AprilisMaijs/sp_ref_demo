
# tiny-resilient-service

A minimal 2-service demo you on scalability, reliability and resilience and the trade-offs between them.

### TL;DR
- `service-a` = client / gateway
  - Calls `service-b`
  - Has:
    - timeout
    - retries with exponential backoff + jitter
    - simple circuit breaker
    - `/metrics` and `/health`
- `service-b` = flaky dependency
  - Random latency
  - Random failures
  - `/metrics` and `/health`

You can:
1. run both with Docker Compose
2. hit `/process` on service-a
3. run a simple load test to generate real numbers for your slides

---

## 1. Run the stack

```bash
docker compose up --build
```

That gives you:
- service-a on http://localhost:8000
- service-b on http://localhost:8001

Now call:
```bash
curl http://localhost:8000/process | jq
```

Output looks like:
```json
{
  "ok": true,
  "data": {
    "status": "ok",
    "host": "service-b-container-id",
    "processing_ms": 412
  },
  "attempts": 1,
  "breaker_state": "closed",
  "total_latency_ms": 420.12,
  "note": "success"
}
```

When things are failing or slow, you'll sometimes get:
```json
{
  "ok": false,
  "data": null,
  "attempts": 3,
  "breaker_state": "open",
  "total_latency_ms": 517.33,
  "note": "failure: all retries failed: upstream 500"
}
```

You can also check metrics:
```bash
curl http://localhost:8000/metrics
curl http://localhost:8001/metrics
```

---

## 2. Load test

The repo includes `loadtest.py`, which hammers `service-a` and prints summary stats.

1. Start the stack:
```bash
docker compose up --build
```

2. In another shell:
```bash
python3 loadtest.py --rps 20 --seconds 10
```

You'll get output like:
```text
=== load test summary ===
Total requests: 200
Success: 156 (78.0%)

Latency (all):
  avg: 310.11ms
  p95: 702.92ms

Latency (successful only):
  avg: 244.88ms
  p95: 501.03ms

Breaker states seen:
  closed: 126
  half_open: 21
  open: 53
```

---

## 3. Tweak knobs (for live demos)

You can tune behavior **without changing code**, using env vars.

### service-b:
- `FAILURE_RATE`: `"0.3"` means 30% of calls fail with a 500.
- `MAX_LATENCY_MS`: `"800"` upper bound for extra delay.
- `BASE_LATENCY_MS`: `"30"` base cost per request.

To make it evil:
```yaml
FAILURE_RATE: "0.6"
MAX_LATENCY_MS: "1500"
```

### service-a:
- `REQUEST_TIMEOUT_S`: timeout per attempt when talking to service-b.
- `MAX_RETRIES`: how many times we'll retry (2 means 1 original + 2 retries).
- `FAILURE_THRESHOLD`: how many consecutive failures until breaker opens.
- `COOL_DOWN_SECONDS`: how long the breaker stays open before trying again.

## 4. Repo layout

```text
tiny-resilient-service/
├── docker-compose.yml
├── service_a.Dockerfile
├── service_b.Dockerfile
├── loadtest.py
├── README.md
├── service_a/
│   ├── main.py
│   ├── resilience.py
│   └── requirements.txt
└── service_b/
    ├── main.py
    └── requirements.txt
```

---

