"""統合パイプラインの本体 (Phase 4: national 単一ファイル)。

カタログ → 対象 FileEntry 選択 → manifest から ZIP 解決 → 読込 → CRS 変換 →
GPKG 書出 + メタデータ埋込 のフローをここで統括する。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyproj

from ksj import __version__
from ksj.catalog.schema import Catalog, Dataset, Version
from ksj.downloader.manifest import ManifestEntry, load_manifest
from ksj.integrator.source_selector import SelectedSource, select_national
from ksj.reader import VectorLayer, read_zip
from ksj.writer import write_layers

DEFAULT_TARGET_CRS = "EPSG:6668"


class DownloadRequiredError(LookupError):
    """対象 ZIP が manifest に登録されていないとき送出する。

    Phase 4 では自動ダウンロードはせず、ユーザに `ksj download` を促す方針。
    自動 DL は Phase 5 以降で検討する (フェーズ間で副作用を増やさないため)。
    """


@dataclass(slots=True)
class IntegrateResult:
    """統合結果のサマリ。CLI の表示用。"""

    output_path: Path
    layer_names: list[str]
    source_zip: Path
    target_crs: str
    crs_converted: bool


def integrate(
    catalog: Catalog,
    code: str,
    year: str,
    *,
    data_dir: Path,
    target_crs: str = DEFAULT_TARGET_CRS,
    format_preference: Iterable[str] | None = None,
) -> IntegrateResult:
    """``code``/``year`` を national として統合し GPKG を書き出す。"""
    dataset = catalog.datasets.get(code)
    if dataset is None:
        raise KeyError(f"データセット '{code}' はカタログに存在しない")

    selected = select_national(dataset, year)
    manifest_entry = _resolve_manifest_entry(data_dir, code, year, selected)
    zip_path = data_dir / manifest_entry.path

    layers = read_zip(zip_path, format_preference=format_preference)

    target = pyproj.CRS.from_user_input(target_crs)
    crs_converted = False
    transformed: list[VectorLayer] = []
    for layer in layers:
        gdf = layer.gdf
        # KSJ 配布物は基本的に PRJ 同梱だが、欠落していたらカタログ値で補う
        if gdf.crs is None and selected.file_entry.crs is not None:
            gdf = gdf.set_crs(epsg=selected.file_entry.crs)
        if gdf.crs is not None and not gdf.crs.equals(target):
            gdf = gdf.to_crs(target)
            crs_converted = True
        transformed.append(
            VectorLayer(
                layer_name=layer.layer_name,
                source_path=layer.source_path,
                format=layer.format,
                gdf=gdf,
            )
        )

    metadata = _build_metadata(
        code=code,
        year=year,
        dataset=dataset,
        selected=selected,
        target_crs=target_crs,
        zip_path=zip_path,
        layers=transformed,
    )

    output_path = data_dir / "integrated" / f"{code}-{year}.gpkg"
    write_layers(transformed, output_path, metadata=metadata)

    return IntegrateResult(
        output_path=output_path,
        layer_names=[layer.layer_name for layer in transformed],
        source_zip=zip_path,
        target_crs=target_crs,
        crs_converted=crs_converted,
    )


def _resolve_manifest_entry(
    data_dir: Path, code: str, year: str, selected: SelectedSource
) -> ManifestEntry:
    """選択した URL に対応する manifest エントリを返す。"""
    manifest = load_manifest(data_dir)
    entry = next(
        (e for e in manifest.get_entries(code, year) if e.url == selected.file_entry.url),
        None,
    )
    if entry is None:
        raise DownloadRequiredError(
            f"{code}/{year} の national ZIP が未取得"
            f" (`uv run ksj download {code} --year {year}` を実行してください)"
        )
    actual_path = data_dir / entry.path
    if not actual_path.exists():
        raise DownloadRequiredError(f"manifest には記録があるがファイル本体が無い: {actual_path}")
    return entry


def _build_metadata(
    *,
    code: str,
    year: str,
    dataset: Dataset,
    selected: SelectedSource,
    target_crs: str,
    zip_path: Path,
    layers: list[VectorLayer],
) -> dict[str, Any]:
    """docs/integration.md のスキーマに沿った出典 JSON を生成する。"""
    version: Version = dataset.versions[year]
    file_entry = selected.file_entry
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
                "url": file_entry.url,
                "scope": file_entry.scope,
                "source_year": selected.year,
                "crs": file_entry.crs,
                "format": file_entry.format,
            }
        ],
        "source_zip": str(zip_path),
        "layers": [layer.layer_name for layer in layers],
        # Phase 5 で prefecture / mesh / regional_bureau の実数値を埋める
        "coverage_summary": {
            "strategy": "national",
            "national_year": selected.year,
            "prefecture": None,
            "regional_bureau": None,
            "mesh": None,
            "notes": [],
        },
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "ksj_tool_version": __version__,
    }
