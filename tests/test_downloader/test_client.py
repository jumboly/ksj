from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from ksj._http import HostRateLimiter
from ksj.downloader.client import (
    PART_SUFFIX,
    DownloadTarget,
    download_file,
    download_many,
    filename_from_url,
)


def test_filename_from_url_basic() -> None:
    assert (
        filename_from_url("https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2025/N03.zip") == "N03.zip"
    )


def test_filename_from_url_unescapes() -> None:
    # 日本語ファイル名や空白入りを許容する
    assert filename_from_url("https://example.com/path/foo%20bar.zip") == "foo bar.zip"


def test_filename_from_url_fallback() -> None:
    assert filename_from_url("https://example.com/") == "download.bin"


@respx.mock
async def test_download_file_success(tmp_path: Path) -> None:
    url = "https://nlftp.mlit.go.jp/data/simple.zip"
    payload = b"A" * 2048
    respx.get(url).mock(return_value=httpx.Response(200, content=payload))

    target = DownloadTarget(url=url, dest_path=tmp_path / "simple.zip")
    limiter = HostRateLimiter(parallel=1, rate_per_sec=100.0)
    async with httpx.AsyncClient() as client:
        result = await download_file(client, target, limiter)

    assert result.ok
    assert not result.skipped
    assert not result.resumed
    assert target.dest_path.read_bytes() == payload
    # .part は完了時に rename される
    assert not (tmp_path / ("simple.zip" + PART_SUFFIX)).exists()


@respx.mock
async def test_download_file_resume_with_206(tmp_path: Path) -> None:
    """既存の .part があれば Range ヘッダで残り分だけ取得する。"""
    url = "https://nlftp.mlit.go.jp/data/resume.zip"
    full = b"X" * 1000
    prefix_size = 400
    (tmp_path / ("resume.zip" + PART_SUFFIX)).write_bytes(full[:prefix_size])

    route = respx.get(url).mock(
        return_value=httpx.Response(
            206,
            content=full[prefix_size:],
            headers={"Content-Range": f"bytes {prefix_size}-999/1000"},
        )
    )

    target = DownloadTarget(url=url, dest_path=tmp_path / "resume.zip")
    limiter = HostRateLimiter(parallel=1, rate_per_sec=100.0)
    async with httpx.AsyncClient() as client:
        result = await download_file(client, target, limiter)

    assert result.ok
    assert result.resumed
    assert target.dest_path.read_bytes() == full
    # Range ヘッダが送出されていること
    sent = route.calls[0].request
    assert sent.headers.get("Range") == f"bytes={prefix_size}-"


@respx.mock
async def test_download_file_server_returns_200_reset_part(tmp_path: Path) -> None:
    """サーバが Range を無視して 200 を返した場合、part を捨てて最初から取り直す。"""
    url = "https://nlftp.mlit.go.jp/data/reset.zip"
    full = b"Y" * 600
    (tmp_path / ("reset.zip" + PART_SUFFIX)).write_bytes(b"OLD" * 10)

    respx.get(url).mock(return_value=httpx.Response(200, content=full))

    target = DownloadTarget(url=url, dest_path=tmp_path / "reset.zip")
    limiter = HostRateLimiter(parallel=1, rate_per_sec=100.0)
    async with httpx.AsyncClient() as client:
        result = await download_file(client, target, limiter)

    assert result.ok
    # Range 要求だったが 200 応答なので resumed フラグは下ろされる
    assert not result.resumed
    assert target.dest_path.read_bytes() == full


@respx.mock
async def test_download_file_skips_when_size_matches(tmp_path: Path) -> None:
    """既存ファイル + expected_size 一致なら HTTP リクエストを打たず skip。"""
    url = "https://nlftp.mlit.go.jp/data/skip.zip"
    existing = b"Z" * 128
    dest = tmp_path / "skip.zip"
    dest.write_bytes(existing)

    route = respx.get(url).mock(return_value=httpx.Response(200, content=b""))

    target = DownloadTarget(url=url, dest_path=dest, expected_size=len(existing))
    limiter = HostRateLimiter(parallel=1, rate_per_sec=100.0)
    async with httpx.AsyncClient() as client:
        result = await download_file(client, target, limiter)

    assert result.skipped
    assert result.ok
    assert not route.called


@respx.mock
async def test_download_file_retries_on_5xx(tmp_path: Path) -> None:
    url = "https://nlftp.mlit.go.jp/data/retry.zip"
    full = b"R" * 64
    respx.get(url).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(200, content=full),
        ]
    )

    target = DownloadTarget(url=url, dest_path=tmp_path / "retry.zip")
    limiter = HostRateLimiter(parallel=1, rate_per_sec=100.0)
    async with httpx.AsyncClient() as client:
        result = await download_file(client, target, limiter)

    assert result.ok
    assert target.dest_path.read_bytes() == full


@respx.mock
async def test_download_file_captures_failure(tmp_path: Path) -> None:
    url = "https://nlftp.mlit.go.jp/data/404.zip"
    respx.get(url).mock(return_value=httpx.Response(404))

    target = DownloadTarget(url=url, dest_path=tmp_path / "missing.zip")
    limiter = HostRateLimiter(parallel=1, rate_per_sec=100.0)
    async with httpx.AsyncClient() as client:
        result = await download_file(client, target, limiter)

    assert not result.ok
    assert result.error is not None
    assert not target.dest_path.exists()


@respx.mock
async def test_download_many_mixed_outcomes(tmp_path: Path) -> None:
    """複数 URL を並列取得。片方失敗しても他方が完了する。"""
    good = "https://nlftp.mlit.go.jp/data/good.zip"
    bad = "https://nlftp.mlit.go.jp/data/bad.zip"
    respx.get(good).mock(return_value=httpx.Response(200, content=b"G" * 32))
    respx.get(bad).mock(return_value=httpx.Response(404))

    targets = [
        DownloadTarget(url=good, dest_path=tmp_path / "good.zip"),
        DownloadTarget(url=bad, dest_path=tmp_path / "bad.zip"),
    ]
    results = await download_many(targets, parallel=2, rate_per_sec=100.0)

    by_url = {r.url: r for r in results}
    assert by_url[good].ok
    assert not by_url[bad].ok
    assert (tmp_path / "good.zip").exists()


@respx.mock
async def test_download_many_invokes_on_file_done(tmp_path: Path) -> None:
    """各ファイル完了ごとに on_file_done が呼ばれる (進捗表示用)。"""
    urls = [
        "https://nlftp.mlit.go.jp/data/p1.zip",
        "https://nlftp.mlit.go.jp/data/p2.zip",
        "https://nlftp.mlit.go.jp/data/p3.zip",
    ]
    for u in urls:
        respx.get(u).mock(return_value=httpx.Response(200, content=b"X" * 8))

    targets = [DownloadTarget(url=u, dest_path=tmp_path / Path(u).name) for u in urls]
    seen: list[str] = []
    await download_many(
        targets,
        parallel=2,
        rate_per_sec=100.0,
        on_file_done=lambda r: seen.append(r.url),
    )
    assert sorted(seen) == sorted(urls)


@respx.mock
async def test_download_many_unknown_host_fails_one_not_all(tmp_path: Path) -> None:
    known = "https://nlftp.mlit.go.jp/data/known.zip"
    unknown = "https://unknown.example.com/data/any.zip"
    respx.get(known).mock(return_value=httpx.Response(200, content=b"K" * 16))

    targets = [
        DownloadTarget(url=known, dest_path=tmp_path / "known.zip"),
        DownloadTarget(url=unknown, dest_path=tmp_path / "any.zip"),
    ]
    results = await download_many(targets, parallel=2, rate_per_sec=100.0)
    by_url = {r.url: r for r in results}
    assert by_url[known].ok
    assert not by_url[unknown].ok
    assert "レートリミット" in (by_url[unknown].error or "")


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
