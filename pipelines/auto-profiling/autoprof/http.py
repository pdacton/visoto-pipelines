"""Async HTTP: overall and per-host concurrency, retries with backoff."""
import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import httpx

USER_AGENT = "visoto-pipelines/auto-profiling"
RETRY_STATUS = {429, 500, 502, 503, 504}
ATTEMPTS = 3


class Client:
    def __init__(self, concurrency: int, per_host: int, timeout: float, deadline: float = 300):
        self.deadline = deadline
        self._all = asyncio.Semaphore(concurrency)
        self._hosts = defaultdict(lambda: asyncio.Semaphore(per_host))
        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=min(timeout, 15)), follow_redirects=True,
            headers={"User-Agent": USER_AGENT}, limits=httpx.Limits(max_connections=concurrency * 2))

    async def close(self):
        await self.http.aclose()

    @asynccontextmanager
    async def slot(self, url: str):
        # Host first: a task queued for a busy host must not hold one of the global slots.
        async with self._hosts[urlparse(url).netloc], self._all:
            yield

    async def request(self, method: str, url: str, **kw) -> httpx.Response:
        """A complete (non-streamed) request with retries."""
        async with self.slot(url):
            async with asyncio.timeout(self.deadline):    # counted from holding the slot, not queueing
                return await self._retry(lambda: self.http.request(method, url, **kw))

    @asynccontextmanager
    async def stream(self, method: str, url: str, **kw):
        """A streamed response; retries only cover failures before the body starts."""
        async with self.slot(url):
            for attempt in range(ATTEMPTS):
                cm = self.http.stream(method, url, **kw)
                try:
                    r = await cm.__aenter__()
                except (httpx.TransportError, httpx.TimeoutException):
                    if attempt == ATTEMPTS - 1:
                        raise
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                if r.status_code in RETRY_STATUS and attempt < ATTEMPTS - 1:
                    await cm.__aexit__(None, None, None)
                    await asyncio.sleep(_delay(r, attempt))
                    continue
                try:
                    yield r
                finally:
                    await cm.__aexit__(None, None, None)
                return

    async def _retry(self, call) -> httpx.Response:
        for attempt in range(ATTEMPTS):
            try:
                r = await call()
                if r.status_code in RETRY_STATUS and attempt < ATTEMPTS - 1:
                    await asyncio.sleep(_delay(r, attempt))
                    continue
                return r
            except (httpx.TransportError, httpx.TimeoutException):
                if attempt == ATTEMPTS - 1:
                    raise
                await asyncio.sleep(2 ** (attempt + 1))


def _delay(r: httpx.Response, attempt: int) -> float:
    try:
        return min(float(r.headers.get("retry-after", "")), 30)
    except ValueError:
        return 2 ** (attempt + 1)
