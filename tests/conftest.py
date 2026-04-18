"""共通フィクスチャ。

`tiny_geodataframe` と `write_shapefile_zip` は reader / writer / pipeline テストで
使い回す。geopandas / shapely は公式型スタブを持たないため `Any` で受ける。
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def tiny_geodataframe() -> Any:
    """4 ポイントの最小 GeoDataFrame (CRS=EPSG:6668)。"""
    import geopandas as gpd
    from shapely.geometry import Point

    return gpd.GeoDataFrame(
        {
            "name": ["a", "b", "c", "d"],
            "value": [1, 2, 3, 4],
        },
        geometry=[Point(140, 35), Point(140.1, 35.1), Point(140.2, 35.2), Point(140.3, 35.3)],
        crs="EPSG:6668",
    )


@pytest.fixture
def write_shapefile_zip(tmp_path: Path) -> Callable[..., Path]:
    """``write_shapefile_zip(gdf, "stem")`` で SHP セットを ZIP 化したパスを返すヘルパ。"""

    def _factory(gdf: Any, stem: str, extra_layers: Mapping[str, Any] | None = None) -> Path:
        work = tmp_path / "shp_src" / stem
        work.mkdir(parents=True, exist_ok=True)
        gdf.to_file(work / f"{stem}.shp", driver="ESRI Shapefile")
        if extra_layers:
            for extra_stem, extra_gdf in extra_layers.items():
                extra_gdf.to_file(work / f"{extra_stem}.shp", driver="ESRI Shapefile")

        zip_path = tmp_path / f"{stem}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in work.iterdir():
                zf.write(path, arcname=path.name)
        return zip_path

    return _factory
