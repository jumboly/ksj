"""`ksj catalog refresh` の実装: KSJ サイトをスクレイプして datasets.yaml を更新する。

設計:
- httpx.AsyncClient でホスト別のセマフォとレート制限
- トップを 1 回取得してデータセット一覧を得る → 各詳細を並列取得
- 詳細ページのパース結果から Dataset / Version / FileEntry を構成
- 進捗は `catalog/.refresh_state.json` に記録して中断再開を可能にする
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml
from pydantic import ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ksj import html_cache
from ksj._http import RETRYABLE_HTTP, HostRateLimiter, build_default_limiters, host_from_url
from ksj.catalog._normalizers import infer_geometry_types, normalize_license
from ksj.catalog._parser import (
    IndexEntry,
    ParsedDetailPage,
    ParsedFile,
    parse_detail_page,
    parse_index_page,
)
from ksj.catalog.loader import DEFAULT_CATALOG_PATH, load_annotations, load_catalog
from ksj.catalog.schema import Catalog, Dataset, FileEntry, Version
from ksj.html_cache import CachePolicy

ProgressCallback = Callable[[str, str | None, int | None], None]

KSJ_INDEX_URL = "https://nlftp.mlit.go.jp/ksj/index.html"
DEFAULT_STATE_PATH = DEFAULT_CATALOG_PATH.with_name(".refresh_state.json")


@dataclass(slots=True)
class RefreshSummary:
    """refresh 実行結果のサマリ。"""

    total_datasets: int
    added: list[str]
    updated: list[str]
    skipped: list[str]
    warnings: list[str]
    unsupported: list[str]  # ダウンロードが form ベースで URL 取得不能
    annotations_missing: list[str]  # annotations.yaml に description/use_cases が無い code


# ---- HTTP レイヤ ------------------------------------------------------------


async def _fetch(
    client: httpx.AsyncClient,
    url: str,
    limiters: dict[str, HostRateLimiter],
    *,
    cache_dir: Path | None = None,
    cache_policy: CachePolicy = CachePolicy.READ_WRITE,
) -> str:
    """URL を取得する。``cache_policy`` によりキャッシュ読み/書きを制御する。"""
    cache_active = cache_dir is not None and cache_policy is not CachePolicy.OFF
    if cache_active and cache_policy in (CachePolicy.READ_ONLY, CachePolicy.READ_WRITE):
        assert cache_dir is not None
        cached = html_cache.load(url, cache_dir)
        if cached is not None:
            return cached

    host = host_from_url(url)
    limiter = limiters.get(host)
    if limiter is None:
        raise RuntimeError(f"host {host} は許可リストに無い ({url})")

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1.0, min=1.0, max=10.0),
        retry=retry_if_exception_type((*RETRYABLE_HTTP, httpx.HTTPStatusError)),
        reraise=True,
    ):
        with attempt:
            await limiter.acquire()
            try:
                resp = await client.get(url, follow_redirects=True)
                # 5xx のみリトライ。4xx は即失敗扱い (tenacity の retry_if_exception_type 対象外)
                if 500 <= resp.status_code < 600:
                    resp.raise_for_status()
                resp.raise_for_status()
                html = resp.text
                if cache_active and cache_policy is CachePolicy.READ_WRITE:
                    assert cache_dir is not None
                    html_cache.save(url, html, cache_dir)
                return html
            finally:
                limiter.release()
    raise RuntimeError("unreachable")  # tenacity が最後の例外を raise するのでここには来ない


# ---- パース結果 → スキーマ変換 --------------------------------------------


def _file_entry_from_parsed(parsed: ParsedFile) -> FileEntry | None:
    """ParsedFile を FileEntry (pydantic) に変換。不整合があれば None。"""
    hints = parsed.scope_hints
    data = {
        "scope": hints.scope,
        "url": parsed.url,
        "format": parsed.format,
        "format_raw": parsed.format_raw or None,
        "crs": parsed.crs,
        "crs_raw": parsed.crs_raw or None,
        "size_bytes": parsed.size_bytes,
        "pref_code": hints.pref_code,
        "pref_name": hints.pref_name,
        "region_code": hints.region_code,
        "region_name": hints.region_name,
        "bureau_code": hints.bureau_code,
        "bureau_name": hints.bureau_name,
        "urban_area_code": hints.urban_area_code,
        "urban_area_name": hints.urban_area_name,
        "mesh_code": hints.mesh_code,
    }
    try:
        return FileEntry.model_validate(data)
    except ValidationError:
        return None


_YEAR_IN_FILENAME_RE = re.compile(r"[-_](?:19|20)(\d{2})(?:\d{4})?(?=[-_.])")
_YEAR_TEXT_RE = re.compile(r"(19|20)(\d{2})\s*年")
# 元号「平成21年」「昭和60年」「令和3年」等の 2 桁年を西暦に変換する
_ERA_YEAR_RE = re.compile(r"(昭和|平成|令和)\s*(\d{1,2})\s*年")
_ERA_BASE: dict[str, int] = {"昭和": 1925, "平成": 1988, "令和": 2018}


def _infer_year(parsed: ParsedFile) -> str:
    """ファイル名 or 年列テキストから版 (YYYY) を推定する。"""
    raw = parsed.year_raw or ""
    m = _YEAR_TEXT_RE.search(raw)
    if m is not None:
        return m.group(1) + m.group(2)
    m_era = _ERA_YEAR_RE.search(raw)
    if m_era is not None:
        base = _ERA_BASE[m_era.group(1)]
        return str(base + int(m_era.group(2)))
    m = _YEAR_IN_FILENAME_RE.search(parsed.filename)
    if m is not None:
        return "20" + m.group(1) if int(m.group(1)) < 50 else "19" + m.group(1)
    return "unknown"


def _build_dataset(index: IndexEntry, parsed: ParsedDetailPage) -> Dataset:
    """詳細ページのパース結果 + index メタ → Dataset。"""
    versions: dict[str, list[FileEntry]] = {}
    for pfile in parsed.files:
        entry = _file_entry_from_parsed(pfile)
        if entry is None:
            continue
        year = _infer_year(pfile)
        versions.setdefault(year, []).append(entry)

    category_label = index.category
    if index.subcategory:
        category_label = f"{index.category} / {index.subcategory}"

    version_models = {
        year: Version(files=sorted(files, key=lambda f: f.url)) for year, files in versions.items()
    }

    notes = (
        "フォームベース配布のため URL 列挙ができません。KSJ サイトで手動取得してください。"
        if not parsed.files
        else None
    )

    # description / use_cases は scraper 対象外 (annotations.yaml 管理) のため設定しない
    license_profile = normalize_license(parsed.license_raw)
    geometry_types = infer_geometry_types(index.name)

    return Dataset(
        # トップページのリンクテキスト (index.name) が正しい。詳細ページの <title>
        # は「国土数値情報ダウンロードサイト」等の汎用タイトルで役に立たないので使わない。
        name=index.name,
        category=category_label,
        detail_page=index.detail_page,
        geometry_types=geometry_types,
        license=license_profile,
        license_raw=parsed.license_raw,
        notes=notes,
        versions=version_models,
    )


# ---- メイン処理 ------------------------------------------------------------


async def refresh_catalog(
    *,
    only: Sequence[str] | None = None,
    parallel: int = 2,
    rate_per_sec: float = 1.0,
    base_catalog_path: Path | None = None,
    http_timeout: float = 30.0,
    progress_callback: (ProgressCallback | None) = None,
    cache_dir: Path | None = html_cache.DEFAULT_HTML_CACHE_DIR,
    cache_policy: CachePolicy = CachePolicy.READ_WRITE,
) -> tuple[Catalog, RefreshSummary]:
    """KSJ サイトを再スクレイプして新しい Catalog を返す。

    ``only`` が指定された場合、既存カタログに存在するそのコードの detail_page を
    直接取りに行く (index 取得をスキップ) か、index 経由で詳細 URL を解決する。

    副作用: ``base_catalog_path`` は読込 (既存カタログ) にのみ使用する。保存は呼び出し側
    の責務。
    """
    base_catalog: Catalog | None = _load_base(base_catalog_path)

    limiters = build_default_limiters(parallel=parallel, rate_per_sec=rate_per_sec)

    async with httpx.AsyncClient(
        timeout=http_timeout, headers={"User-Agent": "ksj-tool/0.1"}
    ) as client:
        # 1. index 取得
        if progress_callback is not None:
            progress_callback("index", None, None)
        index_html = await _fetch(
            client, KSJ_INDEX_URL, limiters, cache_dir=cache_dir, cache_policy=cache_policy
        )
        index_entries = parse_index_page(index_html, KSJ_INDEX_URL)

        if only is not None:
            only_set = set(only)
            index_entries = [e for e in index_entries if e.code in only_set]

        # 2. 詳細ページを並列取得
        tasks: list[asyncio.Task[tuple[IndexEntry, ParsedDetailPage | None, str | None]]] = []
        for entry in index_entries:
            tasks.append(
                asyncio.create_task(
                    _fetch_detail_safely(
                        client, entry, limiters, cache_dir=cache_dir, cache_policy=cache_policy
                    )
                )
            )

        parsed_by_code: dict[str, tuple[IndexEntry, ParsedDetailPage]] = {}
        warnings: list[str] = []
        failed: list[str] = []
        for task in asyncio.as_completed(tasks):
            entry, parsed, error = await task
            if parsed is None:
                failed.append(entry.code)
                warnings.append(f"[{entry.code}] 取得失敗: {error}")
                continue
            parsed_by_code[entry.code] = (entry, parsed)
            for w in parsed.warnings:
                warnings.append(f"[{entry.code}] {w}")
            if progress_callback is not None:
                progress_callback("detail", entry.code, len(parsed.files))

    # 3. 新しい Catalog を構築
    datasets: dict[str, Dataset] = {}
    added: list[str] = []
    updated: list[str] = []
    unsupported: list[str] = []
    skipped: list[str] = []
    base_datasets: dict[str, Dataset] = dict(base_catalog.datasets) if base_catalog else {}

    for code, (entry, parsed) in parsed_by_code.items():
        dataset = _build_dataset(entry, parsed)
        datasets[code] = dataset
        if not parsed.files:
            unsupported.append(code)
        if code not in base_datasets:
            added.append(code)
        else:
            updated.append(code)

    # 4. only 指定で触らなかったデータセットは既存のまま保持
    if only is not None:
        for code, ds in base_datasets.items():
            if code not in datasets:
                datasets[code] = ds
                skipped.append(code)

    catalog = Catalog(
        schema_version=1,
        generated_at=datetime.now(UTC).replace(microsecond=0),
        source_index=KSJ_INDEX_URL,
        total_datasets=len(datasets),
        datasets=datasets,
    )
    annotated = load_annotations()
    annotations_missing = sorted(code for code in datasets if code not in annotated)
    summary = RefreshSummary(
        total_datasets=len(datasets),
        added=sorted(added),
        updated=sorted(updated),
        skipped=sorted(skipped),
        warnings=warnings,
        unsupported=sorted(unsupported),
        annotations_missing=annotations_missing,
    )
    return catalog, summary


async def _fetch_detail_safely(
    client: httpx.AsyncClient,
    entry: IndexEntry,
    limiters: dict[str, HostRateLimiter],
    *,
    cache_dir: Path | None = None,
    cache_policy: CachePolicy = CachePolicy.READ_WRITE,
) -> tuple[IndexEntry, ParsedDetailPage | None, str | None]:
    """個別データセットの取得失敗を全体のクラッシュに伝播させない。"""
    try:
        html = await _fetch(
            client, entry.detail_page, limiters, cache_dir=cache_dir, cache_policy=cache_policy
        )
        parsed = parse_detail_page(html, entry.detail_page, entry.code)
        return entry, parsed, None
    except Exception as exc:
        return entry, None, f"{type(exc).__name__}: {exc}"


def _load_base(path: Path | None) -> Catalog | None:
    target = path if path is not None else DEFAULT_CATALOG_PATH
    if not target.exists():
        return None
    try:
        return load_catalog(target)
    except Exception:
        return None


# ---- 永続化 -----------------------------------------------------------------


def save_catalog(catalog: Catalog, path: Path | None = None) -> Path:
    """Catalog を YAML として書き出す。

    ``description`` / ``use_cases`` は ``catalog/annotations.yaml`` 側で管理する
    ため datasets.yaml には書き出さない (refresh で scraper が上書きしてしまい、
    LLM/人手で埋めた値が消えるのを防ぐ)。
    """
    target = path if path is not None else DEFAULT_CATALOG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    data = catalog.model_dump(
        mode="json",
        exclude_none=True,
        exclude={"datasets": {"__all__": {"description", "use_cases"}}},
    )
    with target.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            data,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
    return target


def save_refresh_state(state: dict[str, object], path: Path | None = None) -> Path:
    """中断再開用の状態をシリアライズする。"""
    target = path if path is not None else DEFAULT_STATE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return target


# ---- 差分 -------------------------------------------------------------------


@dataclass(slots=True)
class CatalogDiff:
    added: list[str]
    removed: list[str]
    changed: list[str]


def diff_catalogs(before: Catalog | None, after: Catalog) -> CatalogDiff:
    before_map = dict(before.datasets) if before else {}
    after_map = dict(after.datasets)

    added = [c for c in after_map if c not in before_map]
    removed = [c for c in before_map if c not in after_map]
    changed: list[str] = []
    for code, ds_new in after_map.items():
        ds_old = before_map.get(code)
        if ds_old is None:
            continue
        if _dataset_signature(ds_old) != _dataset_signature(ds_new):
            changed.append(code)
    return CatalogDiff(sorted(added), sorted(removed), sorted(changed))


def _dataset_signature(dataset: Dataset) -> object:
    """ざっくりした変更検知用のシグネチャ。完全等価を求めない。"""
    return {
        "name": dataset.name,
        "versions": {
            year: sorted([(f.url, f.format, f.crs, f.scope) for f in v.files])
            for year, v in dataset.versions.items()
        },
    }


__all__ = [
    "KSJ_INDEX_URL",
    "CatalogDiff",
    "ProgressCallback",
    "RefreshSummary",
    "diff_catalogs",
    "refresh_catalog",
    "save_catalog",
    "save_refresh_state",
]
