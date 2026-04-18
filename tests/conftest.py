"""共通フィクスチャ。

`tiny_geodataframe` と `write_shapefile_zip` は reader / writer / pipeline テストで
使い回す。geopandas / shapely は公式型スタブを持たないため `Any` で受ける。
Phase 5 で分割統合テスト用に `legacy_geodataframe` と `write_prefecture_zips` を追加。
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def make_vector_layer() -> Callable[..., Any]:
    """VectorLayer を最小情報 (name, gdf) から組み立てるファクトリ。

    writer / reader テストで毎ファイル同じ定義を書いていた _layer ヘルパを
    conftest に集約する。format はテスト上無視されるので固定値で良い。
    """
    from ksj.reader.vector import VectorLayer

    def _factory(name: str, gdf: Any, *, format: str = "shp") -> Any:
        return VectorLayer(layer_name=name, source_path=Path(name), format=format, gdf=gdf)

    return _factory


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


@pytest.fixture
def stage_zip() -> Callable[[Path, Path], Path]:
    """``write_shapefile_zip`` の出力を ``data/raw/<code>/<year>/`` に配置するヘルパ。

    pipeline は manifest の path から ZIP を解決するので、テストでは fixture ZIP を
    raw 配下にコピーして配置する必要がある。
    """

    def _stage(raw_dir: Path, src_zip: Path) -> Path:
        raw_dir.mkdir(parents=True, exist_ok=True)
        dest = raw_dir / src_zip.name
        dest.write_bytes(src_zip.read_bytes())
        return dest

    return _stage


@pytest.fixture
def seed_manifest() -> Callable[..., None]:
    """``ksj.downloader.manifest`` を直接書き込んで integrate の事前状態を作るヘルパ。

    entries の dict は ``url`` / ``rel_path`` / ``size`` を必須とし、``scope`` /
    ``scope_identifier`` / ``format`` は entry 個別 → 引数フォールバックの順で解決する。
    pipeline._build_manifest_index は ``url`` で catalog FileEntry と一致を取るので、
    呼び出し側は url を catalog 側と揃える必要がある。
    """
    from ksj.downloader.manifest import ManifestEntry, load_manifest, save_manifest

    def _seed(
        data_dir: Path,
        code: str,
        year: str,
        *,
        entries: list[dict[str, Any]],
        scope: str | None = None,
        format: str = "shp",
    ) -> None:
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
                    scope=e.get("scope", scope),
                    scope_identifier=e.get("scope_identifier", ""),
                    format=e.get("format", format),
                )
                for e in entries
            ],
        )
        save_manifest(manifest, data_dir)

    return _seed
