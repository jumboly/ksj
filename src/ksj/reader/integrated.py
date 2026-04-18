"""統合済みファイル (GeoPackage / GeoParquet) を (layers, metadata) として読む層。

``ksj convert`` や再検証系コマンドから呼ばれる想定で、書き込み専任の writer 側に
復元ロジックを置かないために独立させている。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import geopandas as gpd
import pyarrow.parquet as pq
import pyogrio

from ksj.reader.vector import VectorLayer
from ksj.writer.parquet import KSJ_METADATA_KEY


class UnsupportedIntegratedFormatError(ValueError):
    """拡張子から形式判別できない統合済みファイルを受け取ったとき送出する。"""


def read_integrated(path: Path) -> tuple[list[VectorLayer], dict[str, Any]]:
    """統合済みファイルを読み込み、レイヤと埋め込みメタデータを返す。

    GPKG は ``gpkg_metadata`` テーブルの dataset スコープ行から JSON を復元し、
    Parquet は ``key_value_metadata`` の ``ksj_metadata`` キーを復元する。
    """
    suffix = path.suffix.lower()
    if suffix == ".gpkg":
        return _read_gpkg(path)
    if suffix == ".parquet":
        return _read_parquet(path)
    raise UnsupportedIntegratedFormatError(
        f"統合済みファイルの形式判別に失敗 (拡張子 '{suffix}' は未サポート): {path}"
    )


def _read_gpkg(path: Path) -> tuple[list[VectorLayer], dict[str, Any]]:
    # pyogrio.list_layers は (layer_name, geom_type) の 2 要素シーケンスを numpy
    # structured array 的に返す。tuple アンパックで先頭をレイヤ名として取り出す。
    layers: list[VectorLayer] = []
    for layer_name, _geom_type in pyogrio.list_layers(path):
        name = str(layer_name)
        gdf = pyogrio.read_dataframe(path, layer=name)
        layers.append(
            VectorLayer(
                layer_name=name,
                source_path=path,
                format="gpkg",
                gdf=gdf,
            )
        )
    return layers, _read_gpkg_metadata(path)


def _read_gpkg_metadata(path: Path) -> dict[str, Any]:
    # gpkg_metadata は OGC GeoPackage の Metadata Extension。拡張が宣言されていない
    # (= メタ未埋込) 古いファイルに備えて存在確認してから SELECT する。
    with sqlite3.connect(path) as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='gpkg_metadata'"
        )
        if cursor.fetchone() is None:
            return {}
        row = conn.execute(
            "SELECT metadata FROM gpkg_metadata WHERE md_scope='dataset' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None or not row[0]:
        return {}
    parsed: dict[str, Any] = json.loads(row[0])
    return parsed


def _read_parquet(path: Path) -> tuple[list[VectorLayer], dict[str, Any]]:
    gdf = gpd.read_parquet(path)
    metadata = _read_parquet_metadata(path)
    # 単一テーブル前提 (writer 側で複数レイヤを fail-fast)。レイヤ名はメタ優先。
    layer_name = _resolve_layer_name(metadata, path)
    layers = [
        VectorLayer(
            layer_name=layer_name,
            source_path=path,
            format="parquet",
            gdf=gdf,
        )
    ]
    return layers, metadata


def _resolve_layer_name(metadata: dict[str, Any], path: Path) -> str:
    layers = metadata.get("layers")
    if isinstance(layers, list) and layers:
        first = layers[0]
        if isinstance(first, str) and first:
            return first
    return path.stem


def _read_parquet_metadata(path: Path) -> dict[str, Any]:
    metadata = pq.read_metadata(path).metadata or {}
    raw = metadata.get(KSJ_METADATA_KEY)
    if raw is None:
        return {}
    parsed: dict[str, Any] = json.loads(raw.decode("utf-8"))
    return parsed


__all__ = ["UnsupportedIntegratedFormatError", "read_integrated"]
