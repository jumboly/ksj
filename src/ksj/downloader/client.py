"""httpx ベースの ZIP ダウンローダ。

Range レジュームと並列制御 (ホスト別レート) を行い、1 ファイル = 1 DownloadResult を返す。
個別ファイルの失敗が他のファイル取得をキャンセルしないよう、例外は DownloadResult に
格納して返すのがこの層の契約。呼び出し側 (CLI) が集約して表示する。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ksj._http import (
    RETRYABLE_HTTP,
    HostRateLimiter,
    build_default_limiters,
    host_from_url,
)

# .zip として open される前に読まれるリスクがあるので、未完了ファイルは別名で保持する
PART_SUFFIX = ".part"

_DEFAULT_CHUNK_SIZE = 1024 * 256

OnProgress = Callable[[str, int, int | None], None]  # (url, bytes_read, total)
OnFileDone = Callable[["DownloadResult"], None]  # 1 ファイルの完了 (成功 or 失敗) ごとに呼ぶ
OnStart = Callable[[int], None]  # DL 開始時に targets 総数 1 回だけ通知


@dataclass(slots=True)
class DownloadTarget:
    """1 件のダウンロード対象。dest_path は最終配置先 (.zip 拡張子を含む)。"""

    url: str
    dest_path: Path
    expected_size: int | None = None


@dataclass(slots=True)
class DownloadResult:
    """ダウンロード実行結果 (成功 or 失敗)。"""

    url: str
    path: Path
    downloaded_bytes: int
    skipped: bool
    resumed: bool
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def filename_from_url(url: str) -> str:
    """URL パスの末尾をファイル名として使う。空ならホスト名 + index.bin にフォールバック。"""
    path = urlparse(url).path
    name = unquote(path.rsplit("/", 1)[-1])
    if not name:
        return "download.bin"
    return name


async def download_file(
    client: httpx.AsyncClient,
    target: DownloadTarget,
    limiter: HostRateLimiter,
    *,
    on_progress: OnProgress | None = None,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
) -> DownloadResult:
    """1 URL を取得する。`.part` を使った Range レジュームと skip を実装する。"""
    dest = target.dest_path
    part = dest.with_suffix(dest.suffix + PART_SUFFIX)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # expected_size 未指定でも、ファイル実在ならひとまず skip 扱いにしない。
    # manifest 側 (CLI) で最終判断するが、同一サイズが分かっているときは即 skip できる。
    if dest.exists() and target.expected_size is not None:
        actual = dest.stat().st_size
        if actual == target.expected_size:
            return DownloadResult(
                url=target.url,
                path=dest,
                downloaded_bytes=0,
                skipped=True,
                resumed=False,
            )

    existing_bytes = part.stat().st_size if part.exists() else 0
    headers: dict[str, str] = {}
    if existing_bytes > 0:
        headers["Range"] = f"bytes={existing_bytes}-"

    try:
        downloaded, resumed = await _stream_with_retry(
            client=client,
            url=target.url,
            part_path=part,
            existing_bytes=existing_bytes,
            headers=headers,
            limiter=limiter,
            chunk_size=chunk_size,
            on_progress=on_progress,
        )
    except Exception as exc:
        return DownloadResult(
            url=target.url,
            path=dest,
            downloaded_bytes=0,
            skipped=False,
            resumed=existing_bytes > 0,
            error=f"{type(exc).__name__}: {exc}",
        )

    # atomic rename: 完了した瞬間に正規ファイル名で見えるようにする
    part.replace(dest)
    return DownloadResult(
        url=target.url,
        path=dest,
        downloaded_bytes=downloaded,
        skipped=False,
        resumed=resumed,
    )


async def _stream_with_retry(
    *,
    client: httpx.AsyncClient,
    url: str,
    part_path: Path,
    existing_bytes: int,
    headers: dict[str, str],
    limiter: HostRateLimiter,
    chunk_size: int,
    on_progress: OnProgress | None,
) -> tuple[int, bool]:
    """tenacity でリトライしつつ 1 回分のストリームを回す。戻り値 = (追加バイト数, resumed フラグ)。"""
    resumed_flag = existing_bytes > 0
    cursor = existing_bytes
    downloaded_delta = 0

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1.0, min=1.0, max=10.0),
        retry=retry_if_exception_type((*RETRYABLE_HTTP, httpx.HTTPStatusError)),
        reraise=True,
    ):
        with attempt:
            await limiter.acquire()
            try:
                async with client.stream(
                    "GET", url, headers=headers, follow_redirects=True
                ) as resp:
                    # サーバが Range をサポートしない場合 200 が返る。part をリセットして 0 からやり直す
                    if cursor > 0 and resp.status_code == 200:
                        part_path.unlink(missing_ok=True)
                        cursor = 0
                        resumed_flag = False
                        headers.pop("Range", None)

                    if 500 <= resp.status_code < 600:
                        resp.raise_for_status()
                    resp.raise_for_status()

                    total = _content_length_total(resp, cursor)
                    mode = "ab" if cursor > 0 else "wb"
                    with part_path.open(mode) as f:
                        async for chunk in resp.aiter_bytes(chunk_size):
                            if not chunk:
                                continue
                            f.write(chunk)
                            cursor += len(chunk)
                            downloaded_delta += len(chunk)
                            if on_progress is not None:
                                on_progress(url, cursor, total)
            finally:
                limiter.release()
    return downloaded_delta, resumed_flag


def _content_length_total(resp: httpx.Response, cursor: int) -> int | None:
    """進捗表示用のトータルサイズを推定する。

    206 の Content-Range から total を取り、無ければ Content-Length + 既読量を足す。
    どれも得られなければ None (進捗バーはインジケータ表示)。
    """
    if resp.status_code == 206:
        content_range = resp.headers.get("Content-Range", "")
        # "bytes 1000-1999/5000" → 5000
        total_part = content_range.rsplit("/", 1)[-1] if "/" in content_range else ""
        if total_part.isdigit():
            return int(total_part)
    length = resp.headers.get("Content-Length")
    if length is not None and length.isdigit():
        return cursor + int(length) - (cursor if resp.status_code == 206 else 0)
    return None


async def download_many(
    targets: list[DownloadTarget],
    *,
    parallel: int = 2,
    rate_per_sec: float = 1.0,
    client: httpx.AsyncClient | None = None,
    limiters: dict[str, HostRateLimiter] | None = None,
    on_progress: OnProgress | None = None,
    on_file_done: OnFileDone | None = None,
    http_timeout: float = 60.0,
) -> list[DownloadResult]:
    """複数 URL を並列取得する。失敗は DownloadResult の error に集める。

    ``on_file_done`` は 1 ファイル完了ごと (成功・失敗問わず) に 1 回だけ呼ばれる。
    CLI の進捗バー更新用。ホスト未許可で即失敗するケースでも同様に呼ばれる。
    """
    owns_client = client is None
    if limiters is None:
        limiters = build_default_limiters(parallel=parallel, rate_per_sec=rate_per_sec)

    async def _wrap(coro: Coroutine[Any, Any, DownloadResult]) -> DownloadResult:
        result = await coro
        if on_file_done is not None:
            on_file_done(result)
        return result

    async def _runner(cl: httpx.AsyncClient) -> list[DownloadResult]:
        tasks: list[asyncio.Task[DownloadResult]] = []
        for target in targets:
            host = host_from_url(target.url)
            limiter = limiters.get(host)
            if limiter is None:
                # ホスト未許可はその 1 件だけ失敗として返す。他ファイルは続行させる
                tasks.append(
                    asyncio.create_task(
                        _wrap(
                            _fail_fast(
                                target=target,
                                message=f"host {host} はレートリミット対象外 ({target.url})",
                            )
                        )
                    )
                )
                continue
            tasks.append(
                asyncio.create_task(
                    _wrap(download_file(cl, target, limiter, on_progress=on_progress))
                )
            )
        return await asyncio.gather(*tasks)

    if owns_client:
        async with httpx.AsyncClient(
            timeout=http_timeout,
            headers={"User-Agent": "ksj-tool/0.1"},
        ) as cl:
            return await _runner(cl)
    return await _runner(client)  # type: ignore[arg-type]


async def _fail_fast(*, target: DownloadTarget, message: str) -> DownloadResult:
    return DownloadResult(
        url=target.url,
        path=target.dest_path,
        downloaded_bytes=0,
        skipped=False,
        resumed=False,
        error=message,
    )


__all__ = [
    "PART_SUFFIX",
    "DownloadResult",
    "DownloadTarget",
    "OnFileDone",
    "OnProgress",
    "download_file",
    "download_many",
    "filename_from_url",
]
