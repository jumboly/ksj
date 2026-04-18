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
from ksj.downloader.manifest import Manifest, ManifestEntry, save_manifest
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
    data_dir: Path, code: str, year: str, *, url: str, rel_path: str, size: int
) -> None:
    manifest = Manifest()
    manifest.set_entries(
        code,
        year,
        [
            ManifestEntry(
                url=url,
                path=rel_path,
                size_bytes=size,
                downloaded_at=datetime.now(UTC).replace(microsecond=0),
                scope="national",
                format="shp",
            )
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
        url=url,
        rel_path=str(dest_zip.relative_to(data_dir)),
        size=dest_zip.stat().st_size,
    )

    catalog = _build_catalog(url)

    result = integrate(catalog, "X01", "2025", data_dir=data_dir)

    assert result.output_path == data_dir / "integrated" / "X01-2025.gpkg"
    assert result.output_path.exists()
    assert "X01-2025" in result.layer_names
    assert result.crs_converted is False  # 既に EPSG:6668

    layers = [name for name, _ in pyogrio.list_layers(result.output_path)]
    assert "X01-2025" in layers

    with sqlite3.connect(result.output_path) as conn:
        (payload,) = conn.execute("SELECT metadata FROM gpkg_metadata").fetchone()
    metadata = json.loads(payload)
    assert metadata["dataset_code"] == "X01"
    assert metadata["target_crs"] == "EPSG:6668"
    assert metadata["coverage_summary"]["strategy"] == "national"
    assert metadata["source_files"][0]["url"] == url


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
        url=url,
        rel_path=str(dest_zip.relative_to(data_dir)),
        size=dest_zip.stat().st_size,
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
