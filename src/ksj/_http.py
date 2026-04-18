"""httpx ベースの通信ユーティリティ (レート制限・リトライ対象例外)。

catalog.refresh と downloader の両方から共通利用する。KSJ は別ホスト (nlftp.mlit.go.jp /
www.gsi.go.jp) に配布が分散しているため、ホスト別にセマフォと秒間上限を独立管理する
仕組みを 1 箇所に集約する。
"""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlparse

import httpx

DEFAULT_LIMITER_HOSTS: tuple[str, ...] = (
    "nlftp.mlit.go.jp",
    "www.gsi.go.jp",
)

RETRYABLE_HTTP: tuple[type[Exception], ...] = (
    httpx.TransportError,
    httpx.ReadTimeout,
)


class HostRateLimiter:
    """1 ホストあたりの「同時接続数」と「秒間リクエスト数」を制御する。"""

    def __init__(self, parallel: int, rate_per_sec: float) -> None:
        self._semaphore = asyncio.Semaphore(parallel)
        self._min_interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0
        self._last_ts = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        await self._semaphore.acquire()
        async with self._lock:
            delta = time.monotonic() - self._last_ts
            if delta < self._min_interval:
                await asyncio.sleep(self._min_interval - delta)
            self._last_ts = time.monotonic()

    def release(self) -> None:
        self._semaphore.release()


def build_default_limiters(parallel: int, rate_per_sec: float) -> dict[str, HostRateLimiter]:
    """KSJ で実際に出現する配布ホストに対して共通設定のリミッタを束で作る。"""
    return {
        host: HostRateLimiter(parallel=parallel, rate_per_sec=rate_per_sec)
        for host in DEFAULT_LIMITER_HOSTS
    }


def host_from_url(url: str) -> str:
    """URL からホスト名を取り出す (無ければ空文字)。リミッタのキーに用いる。"""
    return urlparse(url).hostname or ""


__all__ = [
    "DEFAULT_LIMITER_HOSTS",
    "RETRYABLE_HTTP",
    "HostRateLimiter",
    "build_default_limiters",
    "host_from_url",
]
