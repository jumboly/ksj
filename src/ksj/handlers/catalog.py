"""カタログ操作 (diff / refresh / summary) の純粋関数実装。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from ksj import html_cache
from ksj.catalog import Catalog
from ksj.catalog.refresh import (
    RefreshSummary,
    diff_catalogs,
    refresh_catalog,
    save_catalog,
)
from ksj.handlers._catalog_loader import load_catalog_or_raise


@dataclass(slots=True)
class CatalogDiffResult:
    added: list[str]
    removed: list[str]
    changed: list[str]

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


@dataclass(slots=True)
class RefreshReport:
    """`ksj catalog refresh` の実行結果。

    dry_run 時は ``saved_path`` が None になる。
    """

    summary: RefreshSummary
    saved_path: Path | None = None


@dataclass(slots=True)
class CatalogSummary:
    """カタログ全体のメタ集計 (per-dataset は含めない)。

    AI エージェントが「全体像」を把握するための軽量な payload を意図する。
    個別 dataset の詳細は ``ksj_info`` 相当で取得する想定。
    """

    total_datasets: int
    categories: dict[str, int] = field(default_factory=dict)
    scope_histogram: dict[str, int] = field(default_factory=dict)
    years_seen: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def catalog_diff_data(
    *,
    current: Catalog | None = None,
) -> CatalogDiffResult:
    """既存カタログと最新スクレイプ結果の差分を計算する。

    ネットワークに出るので blocking 時間が長い。rich 表示側では spinner で囲む
    が、handler 自身は進捗表示に関与しない。
    """
    base = current if current is not None else load_catalog_or_raise()
    fresh, _ = asyncio.run(refresh_catalog())
    raw = diff_catalogs(base, fresh)
    return CatalogDiffResult(added=raw.added, removed=raw.removed, changed=raw.changed)


def catalog_refresh_data(
    *,
    only: list[str] | None = None,
    parallel: int = 2,
    rate: float = 1.0,
    cache_dir: Path = html_cache.DEFAULT_HTML_CACHE_DIR,
    cache_policy: html_cache.CachePolicy = html_cache.CachePolicy.READ_WRITE,
    dry_run: bool = False,
) -> RefreshReport:
    catalog, summary = asyncio.run(
        refresh_catalog(
            only=only,
            parallel=parallel,
            rate_per_sec=rate,
            cache_dir=cache_dir,
            cache_policy=cache_policy,
        )
    )
    if dry_run:
        return RefreshReport(summary=summary, saved_path=None)
    path = save_catalog(catalog)
    return RefreshReport(summary=summary, saved_path=path)


def catalog_summary_data(*, catalog: Catalog | None = None) -> CatalogSummary:
    cat = catalog if catalog is not None else load_catalog_or_raise()

    categories: dict[str, int] = {}
    scope_hist: dict[str, int] = {}
    years: set[str] = set()
    for dataset in cat.datasets.values():
        key = dataset.category or "(uncategorized)"
        categories[key] = categories.get(key, 0) + 1
        # scope は dataset 単位でユニーク化 (同じ dataset に複数ファイルがあっても 1 カウント)。
        # ファイル数ベースだと大規模メッシュ系だけ突出して使いづらいため。
        ds_scopes = {str(f.scope) for version in dataset.versions.values() for f in version.files}
        for scope in ds_scopes:
            scope_hist[scope] = scope_hist.get(scope, 0) + 1
        years.update(dataset.versions.keys())

    return CatalogSummary(
        total_datasets=len(cat.datasets),
        categories=dict(sorted(categories.items(), key=lambda kv: (-kv[1], kv[0]))),
        scope_histogram=dict(sorted(scope_hist.items(), key=lambda kv: (-kv[1], kv[0]))),
        years_seen=sorted(years),
        warnings=[],
    )
