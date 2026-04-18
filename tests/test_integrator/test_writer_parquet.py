from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from ksj.writer.parquet import write_layers


def test_write_layers_writes_parquet_with_ksj_and_geo_metadata(
    tmp_path: Path, tiny_geodataframe: Any, make_vector_layer: Callable[..., Any]
) -> None:
    dest = tmp_path / "out.parquet"
    metadata = {"dataset_code": "X01", "version_year": "2025", "license": "CC BY 4.0"}

    write_layers([make_vector_layer("layer_a", tiny_geodataframe)], dest, metadata=metadata)

    assert dest.exists()
    file_metadata = pq.read_metadata(dest).metadata or {}
    # ksj_metadata: 追記された JSON
    assert b"ksj_metadata" in file_metadata
    assert json.loads(file_metadata[b"ksj_metadata"].decode("utf-8")) == metadata
    # geo: geopandas が付けた GeoParquet 1.1 仕様メタが失われていない
    assert b"geo" in file_metadata
    geo_meta = json.loads(file_metadata[b"geo"].decode("utf-8"))
    assert geo_meta.get("version") == "1.1.0"


def test_write_layers_preserves_crs(
    tmp_path: Path, tiny_geodataframe: Any, make_vector_layer: Callable[..., Any]
) -> None:
    import geopandas as gpd

    dest = tmp_path / "out.parquet"
    write_layers([make_vector_layer("layer_a", tiny_geodataframe)], dest, metadata={})

    restored = gpd.read_parquet(dest)
    assert restored.crs is not None
    assert restored.crs.to_epsg() == 6668
    assert len(restored) == len(tiny_geodataframe)


def test_write_layers_overwrites_existing_file(
    tmp_path: Path, tiny_geodataframe: Any, make_vector_layer: Callable[..., Any]
) -> None:
    import geopandas as gpd

    dest = tmp_path / "out.parquet"
    write_layers(
        [make_vector_layer("first", tiny_geodataframe)], dest, metadata={"dataset_code": "OLD"}
    )
    write_layers(
        [make_vector_layer("second", tiny_geodataframe.iloc[:2])],
        dest,
        metadata={"dataset_code": "NEW"},
    )

    restored = gpd.read_parquet(dest)
    assert len(restored) == 2

    file_metadata = pq.read_metadata(dest).metadata or {}
    assert json.loads(file_metadata[b"ksj_metadata"].decode("utf-8"))["dataset_code"] == "NEW"


def test_write_layers_rejects_empty(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_layers([], tmp_path / "out.parquet", metadata={})


def test_write_layers_rejects_multi_layer(
    tmp_path: Path, tiny_geodataframe: Any, make_vector_layer: Callable[..., Any]
) -> None:
    with pytest.raises(ValueError, match="単一レイヤ前提"):
        write_layers(
            [
                make_vector_layer("a", tiny_geodataframe),
                make_vector_layer("b", tiny_geodataframe.iloc[:2]),
            ],
            tmp_path / "out.parquet",
            metadata={},
        )
