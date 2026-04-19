"""`ksj download` の純粋関数実装。

CLI から渡された ``progress`` callback は DL 1 件ごとに呼ばれる。
JSON モードでは ``None`` を渡して Progress UI を一切出さず、最終 Report で
まとめて結果を返す設計。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ksj.catalog import Catalog
from ksj.downloader import (
    DownloadResult,
    DownloadTarget,
    ManifestEntry,
    download_many,
    filename_from_url,
    load_manifest,
    pick_targets,
    save_manifest,
)
from ksj.downloader.client import OnFileDone, OnStart
from ksj.errors import ErrorKind, HandlerError
from ksj.handlers._catalog_loader import load_catalog_or_raise


@dataclass(slots=True)
class _DownloadPlan:
    """DL ターゲットと manifest 書き込みに必要なカタログメタのペア。"""

    target: DownloadTarget
    scope: str
    scope_identifier: str
    format: str


@dataclass(slots=True)
class DownloadReport:
    """download コマンドの結果。

    全件失敗時は ``all_failed`` が True、CLI 側で exit_code=1 を付与する。
    """

    code: str
    year: str
    results: list[DownloadResult] = field(default_factory=list)

    @property
    def succeeded(self) -> list[DownloadResult]:
        return [r for r in self.results if r.ok and not r.skipped]

    @property
    def skipped(self) -> list[DownloadResult]:
        return [r for r in self.results if r.skipped]

    @property
    def failed(self) -> list[DownloadResult]:
        return [r for r in self.results if not r.ok]

    @property
    def downloaded_bytes(self) -> int:
        return sum(r.downloaded_bytes for r in self.succeeded)

    @property
    def all_failed(self) -> bool:
        return bool(self.results) and all(not r.ok for r in self.results)


def _build_plans(
    catalog: Catalog,
    code: str,
    year: str,
    *,
    format_preference: list[str] | None,
    crs_filter: int | None,
    scope_filter: list[str] | None,
    prefer_national: bool,
    dest_root: Path,
) -> list[_DownloadPlan]:
    dataset = catalog.datasets.get(code)
    if dataset is None:
        raise HandlerError(
            ErrorKind.DATASET_NOT_FOUND,
            f"データセット '{code}' はカタログに存在しません",
        )
    if year not in dataset.versions:
        years = ", ".join(sorted(dataset.versions)) or "(登録なし)"
        raise HandlerError(
            ErrorKind.INVALID_ARGUMENT,
            f"{code} に年度 {year} は存在しません  利用可能年度: {years}",
        )

    entries = pick_targets(
        dataset,
        year,
        format_preference=format_preference,
        crs_filter=crs_filter,
        scope_filter=scope_filter,
        prefer_national=prefer_national,
    )
    if not entries:
        raise HandlerError(
            ErrorKind.NO_MATCHING_FILES,
            f"{code}/{year} で条件にマッチするファイルがありません"
            " (--crs / --format-preference / --scope を確認してください)",
        )

    return [
        _DownloadPlan(
            target=DownloadTarget(
                url=f.url,
                dest_path=dest_root / filename_from_url(f.url),
                expected_size=f.size_bytes,
            ),
            scope=str(f.scope),
            scope_identifier=f.scope_identifier,
            format=str(f.format),
        )
        for f in entries
    ]


def download_data(
    code: str,
    year: str,
    *,
    data_dir: Path,
    format_preference: list[str] | None = None,
    crs_filter: int | None = None,
    scope_filter: list[str] | None = None,
    prefer_national: bool = False,
    parallel: int = 2,
    rate: float = 1.0,
    on_start: OnStart | None = None,
    progress: OnFileDone | None = None,
    catalog: Catalog | None = None,
) -> DownloadReport:
    # --scope と --prefer-national の同時指定は概念的に矛盾するので静的に弾く
    if scope_filter and prefer_national:
        raise HandlerError(
            ErrorKind.INVALID_ARGUMENT,
            "--scope と --prefer-national は同時指定できません",
        )

    cat = catalog if catalog is not None else load_catalog_or_raise()
    dest_root = data_dir / "raw" / code / year
    plans = _build_plans(
        cat,
        code,
        year,
        format_preference=format_preference,
        crs_filter=crs_filter,
        scope_filter=scope_filter,
        prefer_national=prefer_national,
        dest_root=dest_root,
    )
    targets = [p.target for p in plans]
    if on_start is not None:
        on_start(len(targets))

    results = asyncio.run(
        download_many(
            targets,
            parallel=parallel,
            rate_per_sec=rate,
            on_file_done=progress,
        )
    )

    manifest = load_manifest(data_dir)
    previous = {e.url: e for e in manifest.get_entries(code, year)}
    plan_by_url = {p.target.url: p for p in plans}
    now = datetime.now(UTC).replace(microsecond=0)
    merged: dict[str, ManifestEntry] = dict(previous)
    for result in results:
        if not result.ok:
            continue
        plan = plan_by_url[result.url]
        # skip は「前回取得した状態のまま」なので downloaded_at を更新しない
        downloaded_at = (
            previous[result.url].downloaded_at
            if (result.skipped and result.url in previous)
            else now
        )
        merged[result.url] = ManifestEntry(
            url=result.url,
            path=str(result.path.relative_to(data_dir)),
            size_bytes=result.path.stat().st_size,
            downloaded_at=downloaded_at,
            scope=plan.scope,
            scope_identifier=plan.scope_identifier,
            format=plan.format,
        )

    manifest.set_entries(code, year, list(merged.values()))
    save_manifest(manifest, data_dir)

    return DownloadReport(code=code, year=year, results=results)
