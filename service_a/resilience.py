
import time
import httpx
import asyncio
from typing import Optional

class CircuitBreaker:
    """
    very simple circuit breaker:
    - closed: calls allowed, track consecutive failures
    - open: calls blocked until cool_down expires
    - half_open: allow 1 trial call; if success -> closed, else -> open again
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        cool_down_seconds: float = 5.0,
    ):
        self.failure_threshold = failure_threshold
        self.cool_down_seconds = cool_down_seconds

        self.state = "closed"
        self.consecutive_failures = 0
        self.opened_at = 0.0

    def can_call(self) -> bool:
        now = time.monotonic()
        if self.state == "closed":
            return True
        if self.state == "open":
            # check cool down
            if now - self.opened_at >= self.cool_down_seconds:
                # move to half_open
                self.state = "half_open"
                return True
            return False
        if self.state == "half_open":
            # allow exactly 1 attempt
            return True
        return True

    def record_success(self):
        self.consecutive_failures = 0
        self.state = "closed"

    def record_failure(self):
        self.consecutive_failures += 1
        if self.state == "half_open":
            # immediately re-open
            self.state = "open"
            self.opened_at = time.monotonic()
            return
        if self.consecutive_failures >= self.failure_threshold:
            self.state = "open"
            self.opened_at = time.monotonic()

    def current_state(self) -> str:
        return self.state

class ResilientHTTPClient:
    def __init__(
        self,
        base_url: str,
        timeout_s: float = 0.5,
        max_retries: int = 2,
        retry_backoff_base: float = 0.05,
        breaker: Optional[CircuitBreaker] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.retry_backoff_base = retry_backoff_base
        self.breaker = breaker or CircuitBreaker()
        self._client = httpx.AsyncClient()

    async def get_json(self, path: str):
        """
        perform GET with:
        - timeout
        - retries + exponential backoff + jitter
        - circuit breaker
        returns (response_json, attempts, breaker_state, latency_ms)
        """
        attempts = 0
        start_all = time.perf_counter()

        if not self.breaker.can_call():
            total_latency_ms = (time.perf_counter() - start_all) * 1000
            raise RuntimeError(f"CircuitBreakerOpen (state={self.breaker.current_state()})")


        while True:
            attempts += 1
            try:
                # time the single attempt
                single_start = time.perf_counter()
                resp = await self._client.get(
                    f"{self.base_url}{path}",
                    timeout=self.timeout_s,
                )
                single_latency_ms = (time.perf_counter() - single_start) * 1000

                if resp.status_code >= 500:
                    raise RuntimeError(f"upstream {resp.status_code}")

                data = resp.json()
                self.breaker.record_success()
                total_latency_ms = (time.perf_counter() - start_all) * 1000
                return data, attempts, self.breaker.current_state(), total_latency_ms, single_latency_ms

            except Exception as e:
                # record failure in breaker
                self.breaker.record_failure()

                # check if we exceeded retries
                if attempts > self.max_retries:
                    total_latency_ms = (time.perf_counter() - start_all) * 1000
                    raise RuntimeError(f"all retries failed: {e}")

                # backoff with jitter
                backoff = self.retry_backoff_base * (2 ** (attempts - 1))
                jitter = backoff * 0.2
                await asyncio.sleep(backoff + jitter)

    async def close(self):
        await self._client.aclose()
