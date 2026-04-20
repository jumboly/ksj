"""CLI smoke テスト: MVP 5 scope を `ksj integrate` の CliRunner 経由で通す。

`tests/test_integrator/test_pipeline.py` が `integrate()` を Python から直接呼ぶ
統合テストを担うのに対し、こちらは Typer のオプション解析・終了コード・rich 出力
を含む CLI 全体のレイヤを検証する。Phase 7 の MVP (N03 / L03-a / L03-a 旧測地系
/ A03 / A53) 相当を 1 ケースずつ網羅する。

`ksj integrate` は handler 経由で同梱 datasets.yaml を読みに行くため、テスト中は
monkeypatch で fixture catalog に差し替える。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from ksj.catalog.schema import Catalog, Dataset, FileEntry, Version
from ksj.cli import app


def _patch_catalog(monkeypatch: pytest.MonkeyPatch, catalog: Catalog) -> None:
    """handler 側の ``load_catalog_or_raise`` が呼ぶ ``load_catalog`` を差し替える。"""
    monkeypatch.setattr("ksj.handlers._catalog_loader.load_catalog", lambda: catalog)


def _read_metadata(gpkg_path: Path) -> dict[str, Any]:
    with sqlite3.connect(gpkg_path) as conn:
        (payload,) = conn.execute("SELECT metadata FROM gpkg_metadata").fetchone()
    return dict(json.loads(payload))


def _row_count(gpkg_path: Path, layer: str) -> int:
    # KSJ コードはハイフンを含む (例: L03-a) ため SQLite 識別子としてはクオートが必要
    with sqlite3.connect(gpkg_path) as conn:
        (count,) = conn.execute(f'SELECT COUNT(*) FROM "{layer}"').fetchone()
    return int(count)


def _invoke_integrate(data_dir: Path, code: str, year: str) -> Any:
    runner = CliRunner()
    return runner.invoke(
        app,
        ["integrate", code, "--year", year, "--data-dir", str(data_dir)],
    )


def test_smoke_national(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_shapefile_zip: Callable[..., Path],
    stage_zip: Callable[[Path, Path], Path],
    seed_manifest: Callable[..., None],
    tiny_geodataframe: Any,
) -> None:
    """N03 相当: national scope, JGD2011, ZIP 1 本で完結。"""
    data_dir = tmp_path / "data"
    src_zip = write_shapefile_zip(tiny_geodataframe, "N03-2025")
    dest = stage_zip(data_dir / "raw" / "N03" / "2025", src_zip)

    url = "https://example.com/N03-2025.zip"
    catalog = Catalog(
        datasets={
            "N03": Dataset(
                name="行政区域",
                license_raw="CC BY 4.0",
                detail_page="https://example.com/N03.html",
                versions={
                    "2025": Version(
                        files=[
                            FileEntry.model_validate(
                                {
                                    "scope": "national",
                                    "url": url,
                                    "format": "shp",
                                    "crs": 6668,
                                }
                            )
                        ]
                    )
                },
            )
        }
    )
    seed_manifest(
        data_dir,
        "N03",
        "2025",
        entries=[
            {
                "url": url,
                "rel_path": str(dest.relative_to(data_dir)),
                "size": dest.stat().st_size,
                "scope": "national",
                "format": "shp",
            }
        ],
    )
    _patch_catalog(monkeypatch, catalog)

    result = _invoke_integrate(data_dir, "N03", "2025")

    assert result.exit_code == 0, result.output
    out_path = data_dir / "integrated" / "N03-2025.gpkg"
    assert out_path.exists()
    assert _row_count(out_path, "N03_2025") == 4
    metadata = _read_metadata(out_path)
    assert metadata["dataset_code"] == "N03"
    assert metadata["coverage_summary"]["strategy"] == "national"


def test_smoke_mesh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_shapefile_zip: Callable[..., Path],
    stage_zip: Callable[[Path, Path], Path],
    seed_manifest: Callable[..., None],
    tiny_geodataframe: Any,
) -> None:
    """L03-a 2021 相当: mesh3 を 3 メッシュ分 union (latest-fill, JGD2011)。"""
    import geopandas as gpd
    from shapely.geometry import Point

    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw" / "L03-a" / "2021"

    mesh_codes = ["5339", "5340", "5439"]
    catalog_files: list[dict[str, Any]] = []
    manifest_entries: list[dict[str, Any]] = []
    for i, mesh in enumerate(mesh_codes):
        gdf = gpd.GeoDataFrame(
            {"mesh": [mesh], "value": [i]},
            geometry=[Point(139 + i * 0.1, 35 + i * 0.1)],
            crs="EPSG:6668",
        )
        src_zip = write_shapefile_zip(gdf, f"L03-a-2021-{mesh}")
        dest = stage_zip(raw_dir, src_zip)
        url = f"https://example.com/L03-a-2021-{mesh}.zip"
        catalog_files.append(
            {
                "scope": "mesh3",
                "url": url,
                "format": "shp",
                "crs": 6668,
                "mesh_code": mesh,
            }
        )
        manifest_entries.append(
            {
                "url": url,
                "rel_path": str(dest.relative_to(data_dir)),
                "size": dest.stat().st_size,
                "scope": "mesh3",
                "scope_identifier": mesh,
                "format": "shp",
            }
        )

    catalog = Catalog(
        datasets={
            "L03-a": Dataset(
                name="土地利用細分メッシュ",
                license_raw="CC BY 4.0",
                detail_page="https://example.com/L03-a.html",
                versions={
                    "2021": Version(files=[FileEntry.model_validate(f) for f in catalog_files])
                },
            )
        }
    )
    seed_manifest(data_dir, "L03-a", "2021", entries=manifest_entries)
    _patch_catalog(monkeypatch, catalog)

    result = _invoke_integrate(data_dir, "L03-a", "2021")

    assert result.exit_code == 0, result.output
    out_path = data_dir / "integrated" / "L03-a-2021.gpkg"
    assert _row_count(out_path, "L03-a_2021") == 3
    metadata = _read_metadata(out_path)
    assert metadata["coverage_summary"]["strategy"] == "latest-fill"
    mesh_cov = metadata["coverage_summary"]["mesh"]
    assert mesh_cov["covered"] == 3
    assert mesh_cov["expected"] == 3


def test_smoke_legacy_crs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_shapefile_zip: Callable[..., Path],
    stage_zip: Callable[[Path, Path], Path],
    seed_manifest: Callable[..., None],
    legacy_geodataframe: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """L03-a 1976 相当: 旧測地系 (Tokyo Datum / EPSG:4301) → JGD2011 変換 + WARNING。"""
    data_dir = tmp_path / "data"
    src_zip = write_shapefile_zip(legacy_geodataframe, "L03-a-1976-5339")
    dest = stage_zip(data_dir / "raw" / "L03-a" / "1976", src_zip)

    url = "https://example.com/L03-a-1976-5339.zip"
    catalog = Catalog(
        datasets={
            "L03-a": Dataset(
                name="土地利用細分メッシュ",
                license_raw="CC BY 4.0",
                detail_page="https://example.com/L03-a.html",
                versions={
                    "1976": Version(
                        files=[
                            FileEntry.model_validate(
                                {
                                    "scope": "mesh3",
                                    "url": url,
                                    "format": "shp",
                                    "crs": 4301,
                                    "mesh_code": "5339",
                                }
                            )
                        ]
                    )
                },
            )
        }
    )
    seed_manifest(
        data_dir,
        "L03-a",
        "1976",
        entries=[
            {
                "url": url,
                "rel_path": str(dest.relative_to(data_dir)),
                "size": dest.stat().st_size,
                "scope": "mesh3",
                "scope_identifier": "5339",
                "format": "shp",
            }
        ],
    )
    _patch_catalog(monkeypatch, catalog)

    with caplog.at_level("WARNING", logger="ksj.integrator.pipeline"):
        result = _invoke_integrate(data_dir, "L03-a", "1976")

    assert result.exit_code == 0, result.output
    out_path = data_dir / "integrated" / "L03-a-1976.gpkg"
    assert out_path.exists()
    assert any("旧測地系" in rec.message for rec in caplog.records)
    metadata = _read_metadata(out_path)
    assert metadata["target_crs"] == "EPSG:6668"
    assert metadata["source_files"][0]["crs"] == 4301


def test_smoke_urban_area(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_shapefile_zip: Callable[..., Path],
    stage_zip: Callable[[Path, Path], Path],
    seed_manifest: Callable[..., None],
) -> None:
    """A03 相当: urban_area (SYUTO/CHUBU/KINKI) の partial 統合。"""
    import geopandas as gpd
    from shapely.geometry import Point

    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw" / "A03" / "2003"

    areas = ["SYUTO", "CHUBU", "KINKI"]
    catalog_files: list[dict[str, Any]] = []
    manifest_entries: list[dict[str, Any]] = []
    for i, area in enumerate(areas):
        gdf = gpd.GeoDataFrame(
            {"area": [area]},
            geometry=[Point(139 + i, 35 + i * 0.5)],
            crs="EPSG:6668",
        )
        src_zip = write_shapefile_zip(gdf, f"A03-2003-{area}")
        dest = stage_zip(raw_dir, src_zip)
        url = f"https://example.com/A03-2003-{area}.zip"
        catalog_files.append(
            {
                "scope": "urban_area",
                "url": url,
                "format": "shp",
                "crs": 6668,
                "urban_area_code": area,
                "urban_area_name": area,
            }
        )
        manifest_entries.append(
            {
                "url": url,
                "rel_path": str(dest.relative_to(data_dir)),
                "size": dest.stat().st_size,
                "scope": "urban_area",
                "scope_identifier": area,
                "format": "shp",
            }
        )

    catalog = Catalog(
        datasets={
            "A03": Dataset(
                name="三大都市圏計画区域",
                license_raw="CC BY 4.0",
                detail_page="https://example.com/A03.html",
                versions={
                    "2003": Version(files=[FileEntry.model_validate(f) for f in catalog_files])
                },
            )
        }
    )
    seed_manifest(data_dir, "A03", "2003", entries=manifest_entries)
    _patch_catalog(monkeypatch, catalog)

    result = _invoke_integrate(data_dir, "A03", "2003")

    assert result.exit_code == 0, result.output
    out_path = data_dir / "integrated" / "A03-2003.gpkg"
    assert _row_count(out_path, "A03_2003") == 3
    metadata = _read_metadata(out_path)
    ua_cov = metadata["coverage_summary"]["urban_area"]
    assert ua_cov["covered"] == 3


def test_smoke_regional_bureau(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_shapefile_zip: Callable[..., Path],
    stage_zip: Callable[[Path, Path], Path],
    seed_manifest: Callable[..., None],
) -> None:
    """A53 相当: regional_bureau × 3 整備局の union。"""
    import geopandas as gpd
    from shapely.geometry import Point

    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw" / "A53" / "2024"

    bureaus = ["hokkaido", "tohoku", "kanto"]
    catalog_files: list[dict[str, Any]] = []
    manifest_entries: list[dict[str, Any]] = []
    for i, bureau in enumerate(bureaus):
        gdf = gpd.GeoDataFrame(
            {"bureau": [bureau]},
            geometry=[Point(140 + i, 38 + i * 0.5)],
            crs="EPSG:6668",
        )
        src_zip = write_shapefile_zip(gdf, f"A53-2024-{bureau}")
        dest = stage_zip(raw_dir, src_zip)
        url = f"https://example.com/A53-2024-{bureau}.zip"
        catalog_files.append(
            {
                "scope": "regional_bureau",
                "url": url,
                "format": "shp",
                "crs": 6668,
                "bureau_code": bureau,
                "bureau_name": bureau,
            }
        )
        manifest_entries.append(
            {
                "url": url,
                "rel_path": str(dest.relative_to(data_dir)),
                "size": dest.stat().st_size,
                "scope": "regional_bureau",
                "scope_identifier": bureau,
                "format": "shp",
            }
        )

    catalog = Catalog(
        datasets={
            "A53": Dataset(
                name="医療圏",
                license_raw="CC BY 4.0",
                detail_page="https://example.com/A53.html",
                versions={
                    "2024": Version(files=[FileEntry.model_validate(f) for f in catalog_files])
                },
            )
        }
    )
    seed_manifest(data_dir, "A53", "2024", entries=manifest_entries)
    _patch_catalog(monkeypatch, catalog)

    result = _invoke_integrate(data_dir, "A53", "2024")

    assert result.exit_code == 0, result.output
    out_path = data_dir / "integrated" / "A53-2024.gpkg"
    assert _row_count(out_path, "A53_2024") == 3
    metadata = _read_metadata(out_path)
    rb_cov = metadata["coverage_summary"]["regional_bureau"]
    assert rb_cov["covered"] == 3
