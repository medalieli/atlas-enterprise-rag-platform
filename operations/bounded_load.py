"""Bounded HTTP load sampler; use only with synthetic fixtures and fake providers."""
from __future__ import annotations
import argparse, asyncio, json, statistics, time
import httpx

async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8000/health/ready")
    p.add_argument("--requests", type=int, default=100)
    p.add_argument("--concurrency", type=int, default=10)
    a = p.parse_args()
    if not 1 <= a.requests <= 1000 or not 1 <= a.concurrency <= 25:
        raise SystemExit("bounded limits: requests 1..1000, concurrency 1..25")
    sem, latencies, statuses = asyncio.Semaphore(a.concurrency), [], []
    async with httpx.AsyncClient(timeout=10) as client:
        async def one() -> None:
            async with sem:
                start = time.perf_counter(); response = await client.get(a.url)
                latencies.append((time.perf_counter()-start)*1000); statuses.append(response.status_code)
        started=time.perf_counter(); await asyncio.gather(*(one() for _ in range(a.requests))); duration=time.perf_counter()-started
    ordered=sorted(latencies)
    percentile=lambda q: ordered[min(len(ordered)-1, round(q*(len(ordered)-1)))]
    print(json.dumps({"environment":"local synthetic fixture; not production capacity","requests":a.requests,"concurrency":a.concurrency,"throughput_rps":round(a.requests/duration,2),"error_rate":round(sum(s>=400 for s in statuses)/a.requests,4),"p50_ms":round(statistics.median(ordered),2),"p95_ms":round(percentile(.95),2),"p99_ms":round(percentile(.99),2)}, sort_keys=True))

if __name__ == "__main__": asyncio.run(main())
