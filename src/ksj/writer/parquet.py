"""GeoParquet 1.1 書き出しと出典 JSON のメタデータ埋め込み。

埋め込み先は GeoParquet 仕様の ``key_value_metadata``。geopandas が付与する
``geo`` キーを保全しつつ、``ksj_metadata`` キーに JSON を追記する。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from ksj.reader.vector import VectorLayer

# GeoParquet 1.1 を明示する。geopandas のデフォルトは 1.0.0 のため、
# bbox/geoarrow 拡張と互換を持たせるには明示指定が要る。
_GEOPARQUET_SCHEMA_VERSION = "1.1.0"

KSJ_METADATA_KEY = b"ksj_metadata"


def write_layers(
    layers: Iterable[VectorLayer],
    dest: Path,
    *,
    metadata: Mapping[str, Any],
) -> Path:
    """``layers`` を ``dest`` に GeoParquet として書き出し、メタデータを埋め込む。

    GeoParquet は単一テーブル前提。複数レイヤ渡されたときは fail-fast する。
    """
    layer_list = list(layers)
    if not layer_list:
        raise ValueError("書き出すレイヤが 0 件")
    if len(layer_list) > 1:
        raise ValueError(
            "GeoParquet は単一レイヤ前提のため、複数レイヤはサポートしません"
            f" (受け取ったレイヤ数: {len(layer_list)})"
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()

    layer = layer_list[0]
    # geopandas の to_parquet は `geo` メタデータを自動で付ける。その後 pyarrow で
    # 読み直して ksj_metadata を追記するため、ここでは WKB + schema_version 1.1 の
    # 既定設定のまま書き出す。
    layer.gdf.to_parquet(dest, schema_version=_GEOPARQUET_SCHEMA_VERSION)

    _embed_dataset_metadata(dest, metadata)
    return dest


def _embed_dataset_metadata(parquet_path: Path, metadata: Mapping[str, Any]) -> None:
    """``key_value_metadata`` に ``ksj_metadata`` キーで JSON を追記する。

    geopandas が付けた ``geo`` キー等の既存メタは全て保全する。
    """
    payload = json.dumps(metadata, ensure_ascii=False, indent=2, default=str).encode("utf-8")

    table = pq.read_table(parquet_path)
    merged: dict[bytes, bytes] = {**(table.schema.metadata or {}), KSJ_METADATA_KEY: payload}
    pq.write_table(table.replace_schema_metadata(merged), parquet_path)


__all__ = ["KSJ_METADATA_KEY", "write_layers"]
