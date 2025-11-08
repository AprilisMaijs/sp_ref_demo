"""
Very dumb load tester (multi-port version)
"""

import argparse
import time
import statistics
import httpx
import asyncio
import random
from collections import Counter


async def bombard_once(client, ports):
    """Send a single request to a random port."""
    port = random.choice(ports)
    start = time.perf_counter()
    try:
        resp = await client.get(f"http://localhost:{port}/process", timeout=1.0)
        lat_ms = (time.perf_counter() - start) * 1000
        data = resp.json()
        return {
            "ok": data.get("ok", False),
            "lat_ms": lat_ms,
            "breaker_state": data.get("breaker_state", "unknown"),
            "attempts": data.get("attempts", -1),
            "port": port,
        }
    except Exception:
        lat_ms = (time.perf_counter() - start) * 1000
        return {
            "ok": False,
            "lat_ms": lat_ms,
            "breaker_state": "request_failed",
            "attempts": -1,
            "port": port,
        }


async def run_load(rps, seconds, ports):
    client = httpx.AsyncClient()
    tasks = []
    interval = 1.0 / rps
    deadline = time.perf_counter() + seconds

    async def schedule_requests():
        while time.perf_counter() < deadline:
            tasks.append(asyncio.create_task(bombard_once(client, ports)))
            await asyncio.sleep(interval)

    await schedule_requests()

    results = await asyncio.gather(*tasks, return_exceptions=False)
    await client.aclose()
    return results



def summarize(final):
    lats_ok = [r["lat_ms"] for r in final if r["ok"]]
    lats_all = [r["lat_ms"] for r in final]
    ok_count = sum(1 for r in final if r["ok"])
    total = len(final)

    def p95(vals):
        if not vals:
            return 0.0
        s = sorted(vals)
        idx = int(len(s) * 0.95) - 1
        idx = max(0, min(idx, len(s) - 1))
        return s[idx]

    breaker_states = Counter([r["breaker_state"] for r in final])

    print("=== load test summary ===")
    print(f"Total requests: {total}")
    print(f"Success: {ok_count} ({ok_count/total*100:.1f}%)")
    print("")
    print("Latency (all):")
    print(f"  avg: {statistics.mean(lats_all):.2f}ms")
    print(f"  p95: {p95(lats_all):.2f}ms")
    print("")
    print("Latency (successful only):")
    if lats_ok:
        print(f"  avg: {statistics.mean(lats_ok):.2f}ms")
        print(f"  p95: {p95(lats_ok):.2f}ms")
    else:
        print("  n/a")
    print("")
    print("Breaker states seen:")
    for st, cnt in breaker_states.items():
        print(f"  {st}: {cnt}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rps", type=float, default=10.0, help="requests per second")
    parser.add_argument("--seconds", type=float, default=10.0, help="how long to run")
    parser.add_argument(
        "--ports",
        type=str,
        default="8000",
        help="comma-separated list of ports to load test, e.g. 8000,8001,8002",
    )
    args = parser.parse_args()

    ports = [p.strip() for p in args.ports.split(",") if p.strip()]

    final = asyncio.run(run_load(args.rps, args.seconds, ports))
    summarize(final)
