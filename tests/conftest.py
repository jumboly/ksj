"""共通フィクスチャ。

`tiny_geodataframe` と `write_shapefile_zip` は reader / writer / pipeline テストで
使い回す。geopandas / shapely は公式型スタブを持たないため `Any` で受ける。
Phase 5 で分割統合テスト用に `legacy_geodataframe` と `write_prefecture_zips` を追加。
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
def legacy_geodataframe() -> Any:
    """4 ポイントの旧測地系 GeoDataFrame (CRS=EPSG:4301, Tokyo Datum)。

    Phase 5 の CRS 変換 WARNING / 座標変換ロジックのテストで使う。
    """
    import geopandas as gpd
    from shapely.geometry import Point

    return gpd.GeoDataFrame(
        {
            "name": ["a", "b", "c", "d"],
            "value": [1, 2, 3, 4],
        },
        geometry=[Point(140, 35), Point(140.1, 35.1), Point(140.2, 35.2), Point(140.3, 35.3)],
        crs="EPSG:4301",
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


@pytest.fixture
def write_prefecture_zips(
    tmp_path: Path,
    write_shapefile_zip: Callable[..., Path],
) -> Callable[..., dict[int, Path]]:
    """都道府県ごとに単一 Shapefile の ZIP を生成するヘルパ。

    ``write_prefecture_zips(pref_codes=[1, 13, 47])`` で 3 県分の ZIP を作る。
    各県で geometry を少しずらして uniqueness を保つ。属性は pref_code と name。
    """

    def _factory(
        pref_codes: list[int],
        *,
        stem_template: str = "A09-pref-{pref:02d}",
    ) -> dict[int, Path]:
        import geopandas as gpd
        from shapely.geometry import Point

        zips: dict[int, Path] = {}
        for pref in pref_codes:
            gdf = gpd.GeoDataFrame(
                {
                    "pref_code": [pref],
                    "name": [f"pref-{pref:02d}"],
                },
                geometry=[Point(135 + pref * 0.1, 33 + pref * 0.1)],
                crs="EPSG:6668",
            )
            stem = stem_template.format(pref=pref)
            zips[pref] = write_shapefile_zip(gdf, stem)
        return zips

    return _factory
