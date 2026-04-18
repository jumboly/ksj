from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ksj.reader import read_integrated
from ksj.reader.integrated import UnsupportedIntegratedFormatError
from ksj.writer import write


def test_read_integrated_round_trip_gpkg(
    tmp_path: Path, tiny_geodataframe: Any, make_vector_layer: Callable[..., Any]
) -> None:
    dest = tmp_path / "round.gpkg"
    metadata = {"dataset_code": "X01", "layers": ["X01_2025"]}
    write(
        [make_vector_layer("X01_2025", tiny_geodataframe)],
        dest,
        metadata=metadata,
        format="gpkg",
    )

    layers, recovered = read_integrated(dest)
    assert len(layers) == 1
    assert layers[0].layer_name == "X01_2025"
    assert layers[0].format == "gpkg"
    assert len(layers[0].gdf) == len(tiny_geodataframe)
    assert recovered == metadata


def test_read_integrated_round_trip_parquet(
    tmp_path: Path, tiny_geodataframe: Any, make_vector_layer: Callable[..., Any]
) -> None:
    dest = tmp_path / "round.parquet"
    metadata = {"dataset_code": "X01", "layers": ["X01_2025"]}
    write(
        [make_vector_layer("X01_2025", tiny_geodataframe)],
        dest,
        metadata=metadata,
        format="parquet",
    )

    layers, recovered = read_integrated(dest)
    assert len(layers) == 1
    assert layers[0].layer_name == "X01_2025"
    assert layers[0].format == "parquet"
    assert len(layers[0].gdf) == len(tiny_geodataframe)
    assert recovered == metadata


def test_read_integrated_parquet_falls_back_to_stem_when_layers_missing(
    tmp_path: Path, tiny_geodataframe: Any, make_vector_layer: Callable[..., Any]
) -> None:
    dest = tmp_path / "X03-2020.parquet"
    write([make_vector_layer("whatever", tiny_geodataframe)], dest, metadata={}, format="parquet")

    layers, _ = read_integrated(dest)
    assert layers[0].layer_name == "X03-2020"


def test_read_integrated_gpkg_without_metadata_table(
    tmp_path: Path, tiny_geodataframe: Any
) -> None:
    import pyogrio

    dest = tmp_path / "nometa.gpkg"
    # writer を経由せず直接書き出して gpkg_metadata テーブルが無い状態を再現
    pyogrio.write_dataframe(tiny_geodataframe, dest, driver="GPKG", layer="plain")

    layers, metadata = read_integrated(dest)
    assert metadata == {}
    assert [layer.layer_name for layer in layers] == ["plain"]


def test_read_integrated_rejects_unknown_suffix(tmp_path: Path) -> None:
    path = tmp_path / "data.shp"
    path.write_bytes(b"dummy")
    with pytest.raises(UnsupportedIntegratedFormatError):
        read_integrated(path)
