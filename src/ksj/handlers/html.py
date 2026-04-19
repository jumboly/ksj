"""`ksj html list` / `ksj html fetch` の純粋関数実装。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ksj import html_cache
from ksj.catalog.refresh import RefreshSummary, refresh_catalog


@dataclass(slots=True)
class HtmlListRow:
    relative_path: str
    size_bytes: int
    modified_at: datetime


@dataclass(slots=True)
class HtmlListResult:
    cache_dir: Path
    entries: list[HtmlListRow]
    total_bytes: int

    @property
    def is_empty(self) -> bool:
        return not self.entries


@dataclass(slots=True)
class HtmlFetchReport:
    """`ksj html fetch` の結果。

    refresh の summary も含むのは、fetch が refresh と同じスクレイパで HTML を
    取ってキャッシュだけ残す構造 (カタログ YAML は書き換えない) のため。
    """

    summary: RefreshSummary
    cache_dir: Path
    cache_stats: html_cache.CacheSummary


def html_list_data(
    *,
    cache_dir: Path = html_cache.DEFAULT_HTML_CACHE_DIR,
) -> HtmlListResult:
    rows: list[HtmlListRow] = []
    total_bytes = 0
    for entry in html_cache.iter_cached(cache_dir):
        rows.append(
            HtmlListRow(
                relative_path=str(entry.path.relative_to(cache_dir)),
                size_bytes=entry.size_bytes,
                modified_at=entry.modified_at,
            )
        )
        total_bytes += entry.size_bytes
    return HtmlListResult(cache_dir=cache_dir, entries=rows, total_bytes=total_bytes)


def html_fetch_data(
    *,
    only: list[str] | None = None,
    parallel: int = 2,
    rate: float = 1.0,
    cache_dir: Path = html_cache.DEFAULT_HTML_CACHE_DIR,
    cache_policy: html_cache.CachePolicy = html_cache.CachePolicy.READ_WRITE,
) -> HtmlFetchReport:
    _, summary = asyncio.run(
        refresh_catalog(
            only=only,
            parallel=parallel,
            rate_per_sec=rate,
            cache_dir=cache_dir,
            cache_policy=cache_policy,
        )
    )
    stats = html_cache.summary(cache_dir)
    return HtmlFetchReport(summary=summary, cache_dir=cache_dir, cache_stats=stats)
