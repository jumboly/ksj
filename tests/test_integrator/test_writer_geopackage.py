from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pyogrio
import pytest

from ksj.reader import VectorLayer
from ksj.writer.geopackage import write_layers


def _layer(name: str, gdf: Any) -> VectorLayer:
    return VectorLayer(layer_name=name, source_path=Path(name), format="shp", gdf=gdf)


def test_write_layers_writes_gpkg_and_metadata(tmp_path: Path, tiny_geodataframe: Any) -> None:
    dest = tmp_path / "out.gpkg"
    metadata = {"dataset_code": "X01", "version_year": "2025", "license": "CC BY 4.0"}

    write_layers([_layer("layer_a", tiny_geodataframe)], dest, metadata=metadata)

    assert dest.exists()
    layers = pyogrio.list_layers(dest)
    assert "layer_a" in [name for name, _ in layers]

    with sqlite3.connect(dest) as conn:
        rows = conn.execute("SELECT md_scope, mime_type, metadata FROM gpkg_metadata").fetchall()
    assert len(rows) == 1
    md_scope, mime_type, payload = rows[0]
    assert md_scope == "dataset"
    assert mime_type == "application/json"
    assert json.loads(payload) == metadata


def test_write_layers_overwrites_existing_file(tmp_path: Path, tiny_geodataframe: Any) -> None:
    dest = tmp_path / "out.gpkg"
    write_layers([_layer("first", tiny_geodataframe)], dest, metadata={})
    write_layers([_layer("second", tiny_geodataframe)], dest, metadata={})

    layer_names = [name for name, _ in pyogrio.list_layers(dest)]
    assert layer_names == ["second"]


def test_write_layers_supports_multi_layer(tmp_path: Path, tiny_geodataframe: Any) -> None:
    dest = tmp_path / "out.gpkg"
    write_layers(
        [_layer("a", tiny_geodataframe), _layer("b", tiny_geodataframe.iloc[:2])],
        dest,
        metadata={},
    )

    names = sorted(name for name, _ in pyogrio.list_layers(dest))
    assert names == ["a", "b"]


def test_write_layers_rejects_empty(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_layers([], tmp_path / "out.gpkg", metadata={})
