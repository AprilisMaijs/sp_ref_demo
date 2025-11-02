
"""
Very dumb load tester
"""

import argparse
import time
import statistics
import httpx
import asyncio
from collections import Counter

async def bombard_once(client):
    start = time.perf_counter()
    try:
        resp = await client.get("http://localhost:8000/process", timeout=1.0)
        lat_ms = (time.perf_counter() - start) * 1000
        data = resp.json()
        return {
            "ok": data.get("ok", False),
            "lat_ms": lat_ms,
            "breaker_state": data.get("breaker_state", "unknown"),
            "attempts": data.get("attempts", -1),
        }
    except Exception as e:
        lat_ms = (time.perf_counter() - start) * 1000
        return {
            "ok": False,
            "lat_ms": lat_ms,
            "breaker_state": "request_failed",
            "attempts": -1,
        }

async def run_load(rps, seconds):
    client = httpx.AsyncClient()
    results = []
    interval = 1.0 / rps
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        results.append(asyncio.create_task(bombard_once(client)))
        await asyncio.sleep(interval)

    final = []
    for t in results:
        final.append(await t)
    await client.aclose()
    return final

def summarize(final):
    lats_ok = [r["lat_ms"] for r in final if r["ok"]]
    lats_all = [r["lat_ms"] for r in final]
    ok_count = sum(1 for r in final if r["ok"])
    total = len(final)

    def p95(vals):
        if not vals: return 0.0
        s = sorted(vals)
        idx = int(len(s)*0.95)-1
        idx = max(0,min(idx,len(s)-1))
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
    args = parser.parse_args()

    final = asyncio.run(run_load(args.rps, args.seconds))
    summarize(final)
