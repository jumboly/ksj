from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ksj.reader.vector import (
    NoMatchingFormatError,
    read_zip,
)


def test_read_zip_returns_layer_per_shapefile(
    write_shapefile_zip: Callable[..., Path],
    tiny_geodataframe: Any,
) -> None:
    zip_path = write_shapefile_zip(
        tiny_geodataframe,
        "main",
        extra_layers={"main_subset": tiny_geodataframe.iloc[:2]},
    )
    layers = read_zip(zip_path)
    names = sorted(layer.layer_name for layer in layers)
    assert names == ["main", "main_subset"]
    assert all(layer.format == "shp" for layer in layers)
    assert all(len(layer.gdf) > 0 for layer in layers)


def test_read_zip_uses_vsizip_path(
    write_shapefile_zip: Callable[..., Path],
    tiny_geodataframe: Any,
) -> None:
    zip_path = write_shapefile_zip(tiny_geodataframe, "vsi")
    (layer,) = read_zip(zip_path)
    assert str(layer.source_path).startswith("/vsizip/")
    assert str(layer.source_path).endswith("vsi.shp")


def test_read_zip_format_preference_skips_unmatching(
    write_shapefile_zip: Callable[..., Path],
    tiny_geodataframe: Any,
) -> None:
    zip_path = write_shapefile_zip(tiny_geodataframe, "only_shp")
    with pytest.raises(NoMatchingFormatError):
        read_zip(zip_path, format_preference=["geojson"])


def test_read_zip_format_preference_picks_alias(
    write_shapefile_zip: Callable[..., Path],
    tiny_geodataframe: Any,
) -> None:
    zip_path = write_shapefile_zip(tiny_geodataframe, "alias")
    layers = read_zip(zip_path, format_preference=["shapefile"])
    assert len(layers) == 1
    assert layers[0].format == "shp"
