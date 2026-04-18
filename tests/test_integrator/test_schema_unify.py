from __future__ import annotations

from typing import Any

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from ksj.catalog.schema import FileEntry
from ksj.integrator.schema_unify import unify
from ksj.integrator.source_selector import SelectedSource


def _source(year: str, *, pref_code: int = 1) -> SelectedSource:
    entry = FileEntry.model_validate(
        {
            "scope": "prefecture",
            "url": f"https://example.com/{pref_code:02d}-{year}.zip",
            "format": "shp",
            "pref_code": pref_code,
        }
    )
    return SelectedSource(file_entry=entry, year=year)


def _frame(**cols: Any) -> gpd.GeoDataFrame:
    nrows = len(next(iter(cols.values())))
    geometry = [Point(140 + i * 0.1, 35 + i * 0.1) for i in range(nrows)]
    return gpd.GeoDataFrame(cols, geometry=geometry, crs="EPSG:6668")


def test_unify_adds_source_year_column() -> None:
    frames = [
        (_source("2018"), _frame(name=["a", "b"])),
        (_source("2015", pref_code=47), _frame(name=["c"])),
    ]
    result = unify(frames)
    assert list(result["source_year"]) == ["2018", "2018", "2015"]
    assert len(result) == 3


def test_unify_takes_column_union() -> None:
    # 2018 は col_a のみ、2015 は col_b のみ。concat 後は両方入り、欠けは NaN
    frames = [
        (_source("2018"), _frame(col_a=[1, 2])),
        (_source("2015", pref_code=47), _frame(col_b=["x"])),
    ]
    result = unify(frames)
    assert set(result.columns) >= {"col_a", "col_b", "source_year", "geometry"}
    # col_a は 2015 行で NaN、col_b は 2018 行で NaN
    assert pd.isna(result.loc[result["source_year"] == "2015", "col_a"]).all()
    assert pd.isna(result.loc[result["source_year"] == "2018", "col_b"]).all()


def test_unify_replaces_numeric_null_values_only_on_numeric_columns() -> None:
    frames = [
        (_source("2020"), _frame(score=[1, -999, 3], label=["a", "-999", "c"])),
    ]
    result = unify(frames, null_values=[-999])
    # 数値列だけ NaN 化されること
    assert pd.isna(result["score"].iloc[1])
    # 文字列列 "-999" はそのまま残る (意図しない文字列列置換を避けるため)
    assert result["label"].iloc[1] == "-999"


def test_unify_replaces_string_null_values_only_on_string_columns() -> None:
    frames = [
        (_source("2020"), _frame(score=[1, 2, 3], label=["a", "不明", "c"])),
    ]
    result = unify(frames, null_values=["不明"])
    assert pd.isna(result["label"].iloc[1])
    # 数値列には文字列 null は適用されない
    assert result["score"].iloc[1] == 2


def test_unify_raises_on_empty() -> None:
    with pytest.raises(ValueError, match="unify"):
        unify([])


def test_unify_preserves_target_crs() -> None:
    frames = [(_source("2020"), _frame(x=[1, 2]))]
    result = unify(frames, target_crs="EPSG:4326")
    assert result.crs is not None
    assert result.crs.to_string() == "EPSG:4326"
