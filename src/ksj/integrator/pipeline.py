"""統合パイプラインの本体。

``select_sources`` で複数ファイルを決め、各 ZIP を読込 → CRS 変換 →
``schema_unify.unify`` で 1 レイヤに集約 → GPKG + メタデータ埋込 の順で処理する。
national 戦略のときは 1 ソースを通すだけで、パイプライン構造は共通。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import pyproj

from ksj import __version__
from ksj.catalog.schema import Catalog, Dataset, FileEntry, Version
from ksj.downloader.manifest import Manifest, ManifestEntry, load_manifest
from ksj.integrator import schema_unify
from ksj.integrator.source_selector import (
    SelectedSource,
    SelectionPlan,
    select_sources,
)
from ksj.reader import VectorLayer, default_encoding_for, read_zip
from ksj.writer import write_layers

DEFAULT_TARGET_CRS = "EPSG:6668"

logger = logging.getLogger(__name__)

# pyproj 標準変換は旧測地系 (Tokyo Datum) から新測地系へ 数m 誤差で変換する。
# 高精度が必要な用途では TKY2JGD / PatchJGD グリッドが要るので、変換時に警告を出す。
_LEGACY_DATUM_EPSG = {4301}


class DownloadRequiredError(LookupError):
    """対象 ZIP が manifest に登録されていないとき送出する。

    自動 DL はフェーズ境界 (副作用の有無) を曖昧にするため行わず、
    ユーザに ``ksj download`` を促す方針。
    """


@dataclass(slots=True)
class IntegrateResult:
    """統合結果のサマリ。CLI の表示用。"""

    output_path: Path
    layer_names: list[str]
    source_zips: list[Path]
    target_crs: str
    crs_converted: bool
    strategy: str
    source_count: int


@dataclass(slots=True)
class _LoadResult:
    """読込 + CRS 変換の中間結果。pipeline 内でのみ使う。"""

    frames: list[tuple[SelectedSource, gpd.GeoDataFrame]] = field(default_factory=list)
    source_zips: list[Path] = field(default_factory=list)
    used_sources: list[SelectedSource] = field(default_factory=list)
    skipped_notes: list[str] = field(default_factory=list)
    crs_converted: bool = False


def integrate(
    catalog: Catalog,
    code: str,
    year: str,
    *,
    data_dir: Path,
    target_crs: str = DEFAULT_TARGET_CRS,
    format_preference: Iterable[str] | None = None,
    strict_year: bool = False,
    allow_partial: bool = False,
) -> IntegrateResult:
    """``code``/``year`` を統合し GPKG を書き出す。"""
    dataset = catalog.datasets.get(code)
    if dataset is None:
        raise KeyError(f"データセット '{code}' はカタログに存在しない")

    prefs_list = list(format_preference) if format_preference is not None else None
    plan = select_sources(
        dataset, year, strict_year=strict_year, format_preference=prefs_list
    )
    target = pyproj.CRS.from_user_input(target_crs)

    manifest = load_manifest(data_dir)
    manifest_index = _build_manifest_index(manifest, code, plan)
    loaded = _load_and_reproject(
        plan=plan,
        manifest_index=manifest_index,
        data_dir=data_dir,
        code=code,
        target=target,
        format_preference=prefs_list,
        allow_partial=allow_partial,
    )
    if not loaded.frames:
        raise DownloadRequiredError(
            f"{code}/{year} で統合に使えるファイルが 0 件"
            f" (`uv run ksj download` で取得してください)"
        )

    unified = schema_unify.unify(
        loaded.frames,
        null_values=dataset.versions[year].null_values,
        target_crs=target_crs,
    )
    layer_name = f"{code}_{year}"
    final_layers = [
        VectorLayer(
            layer_name=layer_name,
            source_path=loaded.source_zips[0],
            format=loaded.used_sources[0].file_entry.format,
            gdf=unified,
        )
    ]

    metadata = _build_metadata(
        code=code,
        year=year,
        dataset=dataset,
        plan=plan,
        used_sources=loaded.used_sources,
        target_crs=target_crs,
        source_zips=loaded.source_zips,
        layer_names=[layer_name],
        extra_notes=loaded.skipped_notes,
    )

    output_path = data_dir / "integrated" / f"{code}-{year}.gpkg"
    write_layers(final_layers, output_path, metadata=metadata)

    return IntegrateResult(
        output_path=output_path,
        layer_names=[layer_name],
        source_zips=loaded.source_zips,
        target_crs=target_crs,
        crs_converted=loaded.crs_converted,
        strategy=plan.strategy,
        source_count=len(loaded.used_sources),
    )


def _build_manifest_index(
    manifest: Manifest, code: str, plan: SelectionPlan
) -> dict[tuple[str, str], ManifestEntry]:
    """(year, url) → ManifestEntry の逆引き辞書を 1 回だけ構築する。

    plan.sources ごとに ``get_entries`` + 線形探索すると 47 prefecture で
    O(N^2) になる。plan に現れる year のみキャッシュするので無駄読込も無い。
    """
    needed_years = {s.year for s in plan.sources}
    index: dict[tuple[str, str], ManifestEntry] = {}
    for year in needed_years:
        for entry in manifest.get_entries(code, year):
            index[(year, entry.url)] = entry
    return index


def _load_and_reproject(
    *,
    plan: SelectionPlan,
    manifest_index: dict[tuple[str, str], ManifestEntry],
    data_dir: Path,
    code: str,
    target: pyproj.CRS,
    format_preference: Iterable[str] | None,
    allow_partial: bool,
) -> _LoadResult:
    """各 SelectedSource を manifest で解決 → 読込 → CRS 変換する。

    ``allow_partial`` が True かつ manifest に無いソースがあればスキップし、
    スキップ内容を skipped_notes に積む。False なら即エラー。
    """
    prefs_list = list(format_preference) if format_preference is not None else None
    result = _LoadResult()

    for source in plan.sources:
        entry = manifest_index.get((source.year, source.file_entry.url))
        if entry is None:
            msg = (
                f"{code}/{source.year} の {source.file_entry.scope}/"
                f"{source.file_entry.scope_identifier} が未取得"
                f" (`uv run ksj download {code} --year {source.year}` を実行)"
            )
            if allow_partial:
                logger.warning("manifest 欠落をスキップ: %s", msg)
                result.skipped_notes.append(f"manifest 欠落: {source.file_entry.url}")
                continue
            raise DownloadRequiredError(msg)

        zip_path = data_dir / entry.path
        if not zip_path.exists():
            if allow_partial:
                logger.warning("ファイル本体なし (スキップ): %s", zip_path)
                result.skipped_notes.append(f"ファイル本体なし: {zip_path}")
                continue
            raise DownloadRequiredError(f"manifest には記録があるがファイル本体が無い: {zip_path}")

        encoding = source.file_entry.encoding or default_encoding_for(source.file_entry.format)
        layers = read_zip(zip_path, format_preference=prefs_list, encoding=encoding)
        for layer in layers:
            gdf, converted = _reproject(layer.gdf, source.file_entry, target)
            result.frames.append((source, gdf))
            result.crs_converted = result.crs_converted or converted

        result.source_zips.append(zip_path)
        result.used_sources.append(source)

    return result


def _reproject(
    gdf: gpd.GeoDataFrame,
    file_entry: FileEntry,
    target: pyproj.CRS,
) -> tuple[gpd.GeoDataFrame, bool]:
    """``gdf`` を target CRS に揃える。PRJ 欠落時はカタログの EPSG で補填。"""
    if gdf.crs is None:
        if file_entry.crs is None:
            return gdf, False
        gdf = gdf.set_crs(epsg=file_entry.crs)
    if gdf.crs.equals(target):
        return gdf, False

    source_epsg = gdf.crs.to_epsg()
    if source_epsg in _LEGACY_DATUM_EPSG:
        logger.warning(
            "旧測地系 (EPSG:%s) → %s 変換 (数m 精度の誤差あり)",
            source_epsg,
            target.to_string(),
        )
    return gdf.to_crs(target), True


def _build_metadata(
    *,
    code: str,
    year: str,
    dataset: Dataset,
    plan: SelectionPlan,
    used_sources: list[SelectedSource],
    target_crs: str,
    source_zips: list[Path],
    layer_names: list[str],
    extra_notes: list[str],
) -> dict[str, Any]:
    """docs/integration.md のスキーマに沿った出典 JSON を生成する。"""
    version: Version = dataset.versions[year]
    return {
        "dataset_code": code,
        "dataset_name": dataset.name,
        "version_year": year,
        "reference_date": version.reference_date,
        "source_index": "https://nlftp.mlit.go.jp/ksj/index.html",
        "source_detail": dataset.detail_page,
        "license": dataset.license,
        "license_notes": dataset.notes,
        "target_crs": target_crs,
        "source_files": [
            {
                "url": source.file_entry.url,
                "scope": source.file_entry.scope,
                "scope_identifier": source.file_entry.scope_identifier,
                "source_year": source.year,
                "crs": source.file_entry.crs,
                "format": source.file_entry.format,
            }
            for source in used_sources
        ],
        "source_zips": [str(p) for p in source_zips],
        "layers": layer_names,
        "coverage_summary": _build_coverage_summary(plan, extra_notes),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "ksj_tool_version": __version__,
    }


def _build_coverage_summary(plan: SelectionPlan, extra_notes: list[str]) -> dict[str, Any]:
    """``SelectionPlan.coverage`` を docs/integration.md のメタデータ構造に変換する。

    scope キーを top-level に平たく展開する (docs 例示に整合)。mesh1..mesh6 は
    まとめて "mesh" キーに寄せる。
    """
    summary: dict[str, Any] = {
        "strategy": plan.strategy,
        "national_year": plan.national_year,
        "notes": list(plan.notes) + extra_notes,
    }
    for bucket in plan.coverage:
        key = "mesh" if bucket.scope.startswith("mesh") else bucket.scope
        summary[key] = bucket.to_payload()
    return summary


__all__ = [
    "DEFAULT_TARGET_CRS",
    "DownloadRequiredError",
    "IntegrateResult",
    "integrate",
]
