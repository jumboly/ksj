from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyogrio
import pytest

from ksj.catalog.schema import Catalog, Dataset, FileEntry, Version
from ksj.downloader.manifest import ManifestEntry, load_manifest, save_manifest
from ksj.integrator.pipeline import DownloadRequiredError, integrate


def _build_catalog(zip_url: str) -> Catalog:
    return Catalog(
        datasets={
            "X01": Dataset(
                name="サンプル",
                license="CC BY 4.0",
                detail_page="https://example.com/X01.html",
                versions={
                    "2025": Version(
                        reference_date=None,
                        files=[
                            FileEntry.model_validate(
                                {
                                    "scope": "national",
                                    "url": zip_url,
                                    "format": "shp",
                                    "crs": 6668,
                                }
                            ),
                        ],
                    ),
                },
            ),
        }
    )


def _seed_manifest(
    data_dir: Path,
    code: str,
    year: str,
    *,
    entries: list[dict[str, Any]],
    scope: str = "national",
) -> None:
    """manifest を entries で更新する。data_dir に既存の manifest があればマージ。"""
    manifest = load_manifest(data_dir)
    manifest.set_entries(
        code,
        year,
        [
            ManifestEntry(
                url=e["url"],
                path=e["rel_path"],
                size_bytes=e["size"],
                downloaded_at=datetime.now(UTC).replace(microsecond=0),
                scope=scope,
                scope_identifier=e.get("scope_identifier", ""),
                format="shp",
            )
            for e in entries
        ],
    )
    save_manifest(manifest, data_dir)


def test_integrate_writes_gpkg_with_metadata(
    tmp_path: Path,
    write_shapefile_zip: Callable[..., Path],
    tiny_geodataframe: Any,
) -> None:
    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw" / "X01" / "2025"
    raw_dir.mkdir(parents=True)

    src_zip = write_shapefile_zip(tiny_geodataframe, "X01-2025")
    dest_zip = raw_dir / src_zip.name
    dest_zip.write_bytes(src_zip.read_bytes())

    url = "https://example.com/X01-2025.zip"
    _seed_manifest(
        data_dir,
        "X01",
        "2025",
        entries=[
            {
                "url": url,
                "rel_path": str(dest_zip.relative_to(data_dir)),
                "size": dest_zip.stat().st_size,
            }
        ],
    )

    catalog = _build_catalog(url)

    result = integrate(catalog, "X01", "2025", data_dir=data_dir)

    assert result.output_path == data_dir / "integrated" / "X01-2025.gpkg"
    assert result.output_path.exists()
    assert result.layer_names == ["X01_2025"]
    assert result.crs_converted is False  # 既に EPSG:6668
    assert result.strategy == "national"
    assert result.source_count == 1

    layers = [name for name, _ in pyogrio.list_layers(result.output_path)]
    assert "X01_2025" in layers

    with sqlite3.connect(result.output_path) as conn:
        (payload,) = conn.execute("SELECT metadata FROM gpkg_metadata").fetchone()
    metadata = json.loads(payload)
    assert metadata["dataset_code"] == "X01"
    assert metadata["target_crs"] == "EPSG:6668"
    assert metadata["coverage_summary"]["strategy"] == "national"
    assert metadata["coverage_summary"]["national_year"] == "2025"
    assert metadata["source_files"][0]["url"] == url
    assert metadata["source_files"][0]["source_year"] == "2025"


def test_integrate_writes_parquet_with_metadata(
    tmp_path: Path,
    write_shapefile_zip: Callable[..., Path],
    tiny_geodataframe: Any,
) -> None:
    import pyarrow.parquet as pq

    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw" / "X01" / "2025"
    raw_dir.mkdir(parents=True)

    src_zip = write_shapefile_zip(tiny_geodataframe, "X01-2025")
    dest_zip = raw_dir / src_zip.name
    dest_zip.write_bytes(src_zip.read_bytes())

    url = "https://example.com/X01-2025.zip"
    _seed_manifest(
        data_dir,
        "X01",
        "2025",
        entries=[
            {
                "url": url,
                "rel_path": str(dest_zip.relative_to(data_dir)),
                "size": dest_zip.stat().st_size,
            }
        ],
    )
    catalog = _build_catalog(url)

    result = integrate(
        catalog,
        "X01",
        "2025",
        data_dir=data_dir,
        output_format="parquet",
    )

    assert result.output_path == data_dir / "integrated" / "X01-2025.parquet"
    assert result.output_path.exists()

    file_metadata = pq.read_metadata(result.output_path).metadata or {}
    assert b"ksj_metadata" in file_metadata
    payload = json.loads(file_metadata[b"ksj_metadata"].decode("utf-8"))
    assert payload["dataset_code"] == "X01"
    assert payload["coverage_summary"]["strategy"] == "national"


def test_integrate_honours_output_path_override(
    tmp_path: Path,
    write_shapefile_zip: Callable[..., Path],
    tiny_geodataframe: Any,
) -> None:
    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw" / "X01" / "2025"
    raw_dir.mkdir(parents=True)

    src_zip = write_shapefile_zip(tiny_geodataframe, "X01-2025")
    dest_zip = raw_dir / src_zip.name
    dest_zip.write_bytes(src_zip.read_bytes())

    url = "https://example.com/X01-2025.zip"
    _seed_manifest(
        data_dir,
        "X01",
        "2025",
        entries=[
            {
                "url": url,
                "rel_path": str(dest_zip.relative_to(data_dir)),
                "size": dest_zip.stat().st_size,
            }
        ],
    )
    catalog = _build_catalog(url)

    custom = tmp_path / "custom" / "out.parquet"
    result = integrate(
        catalog,
        "X01",
        "2025",
        data_dir=data_dir,
        output_format="parquet",
        output_path=custom,
    )

    assert result.output_path == custom
    assert custom.exists()


def test_integrate_converts_crs(
    tmp_path: Path,
    write_shapefile_zip: Callable[..., Path],
    tiny_geodataframe: Any,
) -> None:
    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw" / "X01" / "2025"
    raw_dir.mkdir(parents=True)

    src_zip = write_shapefile_zip(tiny_geodataframe, "X01")
    dest_zip = raw_dir / src_zip.name
    dest_zip.write_bytes(src_zip.read_bytes())

    url = "https://example.com/X01.zip"
    _seed_manifest(
        data_dir,
        "X01",
        "2025",
        entries=[
            {
                "url": url,
                "rel_path": str(dest_zip.relative_to(data_dir)),
                "size": dest_zip.stat().st_size,
            }
        ],
    )
    catalog = _build_catalog(url)

    result = integrate(catalog, "X01", "2025", data_dir=data_dir, target_crs="EPSG:4326")
    assert result.crs_converted is True


def test_integrate_raises_when_manifest_missing(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    catalog = _build_catalog("https://example.com/X01.zip")
    with pytest.raises(DownloadRequiredError):
        integrate(catalog, "X01", "2025", data_dir=data_dir)


def test_integrate_raises_for_unknown_dataset(tmp_path: Path) -> None:
    catalog = Catalog()
    with pytest.raises(KeyError):
        integrate(catalog, "ZZZ", "2025", data_dir=tmp_path)


def _build_prefecture_catalog(entries_by_year: dict[str, list[dict[str, Any]]]) -> Catalog:
    """各年度の prefecture FileEntry を dict で受け取り Catalog を組む。"""
    versions = {}
    for year, entries in entries_by_year.items():
        files = [FileEntry.model_validate(e) for e in entries]
        versions[year] = Version(files=files)
    return Catalog(
        datasets={
            "A09": Dataset(
                name="都市地域",
                license="CC BY 4.0",
                detail_page="https://example.com/A09.html",
                versions=versions,
            )
        }
    )


def test_integrate_combines_prefecture_split_into_single_layer(
    tmp_path: Path,
    write_prefecture_zips: Callable[..., dict[int, Path]],
) -> None:
    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw" / "A09" / "2018"
    raw_dir.mkdir(parents=True)

    pref_codes = [1, 13, 47]
    zips = write_prefecture_zips(pref_codes)

    catalog_entries: list[dict[str, Any]] = []
    manifest_entries: list[dict[str, Any]] = []
    for pref in pref_codes:
        src_zip = zips[pref]
        dest = raw_dir / src_zip.name
        dest.write_bytes(src_zip.read_bytes())
        url = f"https://example.com/A09-2018-pref{pref:02d}.zip"
        catalog_entries.append(
            {
                "scope": "prefecture",
                "url": url,
                "format": "shp",
                "crs": 6668,
                "pref_code": pref,
            }
        )
        manifest_entries.append(
            {
                "url": url,
                "rel_path": str(dest.relative_to(data_dir)),
                "size": dest.stat().st_size,
                "pref_code": pref,
            }
        )

    catalog = _build_prefecture_catalog({"2018": catalog_entries})
    _seed_manifest(data_dir, "A09", "2018", entries=manifest_entries, scope="prefecture")

    result = integrate(catalog, "A09", "2018", data_dir=data_dir)

    assert result.strategy == "latest-fill"
    assert result.layer_names == ["A09_2018"]
    assert result.source_count == 3

    layers = [name for name, _ in pyogrio.list_layers(result.output_path)]
    assert layers == ["A09_2018"]

    with sqlite3.connect(result.output_path) as conn:
        (count,) = conn.execute("SELECT COUNT(*) FROM A09_2018").fetchone()
    assert count == 3

    with sqlite3.connect(result.output_path) as conn:
        (payload,) = conn.execute("SELECT metadata FROM gpkg_metadata").fetchone()
    metadata = json.loads(payload)
    assert metadata["coverage_summary"]["strategy"] == "latest-fill"
    pref_cov = metadata["coverage_summary"]["prefecture"]
    assert pref_cov["covered"] == 3
    assert pref_cov["expected"] == 3
    assert pref_cov["year_distribution"] == {"2018": 3}


def test_integrate_latest_fill_supplements_missing_pref_from_past_year(
    tmp_path: Path,
    write_prefecture_zips: Callable[..., dict[int, Path]],
) -> None:
    """本州 46 県 2018、沖縄のみ 2015 というケースの擬似再現 (3 県版)。"""
    data_dir = tmp_path / "data"

    zips_2018 = write_prefecture_zips([1, 13], stem_template="A09-2018-pref{pref:02d}")
    zips_2015 = write_prefecture_zips([47], stem_template="A09-2015-pref{pref:02d}")

    raw_2018 = data_dir / "raw" / "A09" / "2018"
    raw_2018.mkdir(parents=True)
    entries_2018: list[dict[str, Any]] = []
    manifest_2018: list[dict[str, Any]] = []
    for pref, src in zips_2018.items():
        dest = raw_2018 / src.name
        dest.write_bytes(src.read_bytes())
        url = f"https://example.com/A09-2018-pref{pref:02d}.zip"
        entries_2018.append(
            {"scope": "prefecture", "url": url, "format": "shp", "crs": 6668, "pref_code": pref}
        )
        manifest_2018.append(
            {
                "url": url,
                "rel_path": str(dest.relative_to(data_dir)),
                "size": dest.stat().st_size,
                "pref_code": pref,
            }
        )

    raw_2015 = data_dir / "raw" / "A09" / "2015"
    raw_2015.mkdir(parents=True)
    entries_2015: list[dict[str, Any]] = []
    manifest_2015: list[dict[str, Any]] = []
    for pref, src in zips_2015.items():
        dest = raw_2015 / src.name
        dest.write_bytes(src.read_bytes())
        url = f"https://example.com/A09-2015-pref{pref:02d}.zip"
        entries_2015.append(
            {"scope": "prefecture", "url": url, "format": "shp", "crs": 6668, "pref_code": pref}
        )
        manifest_2015.append(
            {
                "url": url,
                "rel_path": str(dest.relative_to(data_dir)),
                "size": dest.stat().st_size,
                "pref_code": pref,
            }
        )

    catalog = _build_prefecture_catalog({"2018": entries_2018, "2015": entries_2015})
    _seed_manifest(data_dir, "A09", "2018", entries=manifest_2018, scope="prefecture")
    _seed_manifest(data_dir, "A09", "2015", entries=manifest_2015, scope="prefecture")

    result = integrate(catalog, "A09", "2018", data_dir=data_dir)

    assert result.source_count == 3

    with sqlite3.connect(result.output_path) as conn:
        (payload,) = conn.execute("SELECT metadata FROM gpkg_metadata").fetchone()
    metadata = json.loads(payload)
    pref_cov = metadata["coverage_summary"]["prefecture"]
    assert pref_cov["covered"] == 3
    assert pref_cov["expected"] == 3
    assert pref_cov["year_distribution"] == {"2018": 2, "2015": 1}
    notes = metadata["coverage_summary"]["notes"]
    assert any("過去年度から補填" in n for n in notes)

    # source_year 列で沖縄 (pref 47) が 2015 由来と分かる
    with sqlite3.connect(result.output_path) as conn:
        rows = conn.execute(
            "SELECT pref_code, source_year FROM A09_2018 ORDER BY pref_code"
        ).fetchall()
    by_pref = dict(rows)
    assert by_pref[1] == "2018"
    assert by_pref[13] == "2018"
    assert by_pref[47] == "2015"


def test_integrate_converts_legacy_tokyo_datum(
    tmp_path: Path,
    write_shapefile_zip: Callable[..., Path],
    legacy_geodataframe: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw" / "X01" / "2025"
    raw_dir.mkdir(parents=True)

    src_zip = write_shapefile_zip(legacy_geodataframe, "X01-legacy")
    dest_zip = raw_dir / src_zip.name
    dest_zip.write_bytes(src_zip.read_bytes())

    url = "https://example.com/X01-legacy.zip"
    # national scope + crs=4301 で登録
    catalog = Catalog(
        datasets={
            "X01": Dataset(
                name="サンプル",
                license="CC BY 4.0",
                detail_page="https://example.com/X01.html",
                versions={
                    "2025": Version(
                        files=[
                            FileEntry.model_validate(
                                {
                                    "scope": "national",
                                    "url": url,
                                    "format": "shp",
                                    "crs": 4301,
                                }
                            )
                        ]
                    )
                },
            )
        }
    )
    _seed_manifest(
        data_dir,
        "X01",
        "2025",
        entries=[
            {
                "url": url,
                "rel_path": str(dest_zip.relative_to(data_dir)),
                "size": dest_zip.stat().st_size,
            }
        ],
    )

    with caplog.at_level("WARNING", logger="ksj.integrator.pipeline"):
        result = integrate(catalog, "X01", "2025", data_dir=data_dir)

    assert result.crs_converted is True
    assert any("旧測地系" in rec.message for rec in caplog.records)
