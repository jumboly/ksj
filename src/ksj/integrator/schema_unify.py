"""分割ソース間のスキーマ統一と concat。

source_year 列付与 → 欠損値コード → NaN → 列 union concat の順で適用する。
型昇格は pandas 自動に任せる (Int64 と float が混ざると float64 に倒れる等の
caveat は docs/integration.md に記載)。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import geopandas as gpd
import pandas as pd

from ksj.integrator.source_selector import SelectedSource


def unify(
    frames: list[tuple[SelectedSource, gpd.GeoDataFrame]],
    *,
    null_values: Iterable[int | float | str] = (),
    target_crs: str | None = None,
) -> gpd.GeoDataFrame:
    """複数 GeoDataFrame を 1 本の GeoDataFrame に正規化・結合する。

    - 各フレームに ``source_year`` 列を付与 (どの配布年度から来た行か保持)
    - ``null_values`` で宣言された値を NaN 化 (数値 null は数値列、文字列 null は
      文字列列にのみ適用。意図しない置換を避けるため列 dtype で絞る)
    - 列 union で concat (欠損列は NaN 埋め)
    - ``target_crs`` が指定されていれば最終的に CRS 情報をセット (既に各フレームが
      target に揃っている前提の軽いフォールバック)

    ``frames`` が空なら ValueError。
    """
    if not frames:
        raise ValueError("unify: 入力フレームが 0 件")

    prepared: list[gpd.GeoDataFrame] = []
    for source, gdf in frames:
        work = gdf.copy()
        # concat 前に source_year を足さないと「どの年度由来か」の情報が失われる
        work["source_year"] = source.year
        prepared.append(_apply_null_values(work, null_values))

    # pandas.concat で列 union、join="outer" がデフォルト挙動
    combined = pd.concat(prepared, ignore_index=True)

    geometry_name = prepared[0].geometry.name
    crs = target_crs or prepared[0].crs
    result = gpd.GeoDataFrame(combined, geometry=geometry_name, crs=crs)
    return result


def _apply_null_values(
    gdf: gpd.GeoDataFrame,
    null_values: Iterable[int | float | str],
) -> gpd.GeoDataFrame:
    """``null_values`` を列 dtype に応じて NaN 化する。

    数値 null (``-999`` 等) を文字列列に適用しない、という意図的な制限。
    ``"不明"`` のような文字列を数値列に適用しないのも同理由。
    """
    num_nulls = [v for v in null_values if isinstance(v, int | float) and not isinstance(v, bool)]
    str_nulls = [v for v in null_values if isinstance(v, str)]
    if not num_nulls and not str_nulls:
        return gdf

    for col in gdf.columns:
        if col == gdf.geometry.name:
            continue
        series: pd.Series[Any] = gdf[col]
        if num_nulls and pd.api.types.is_numeric_dtype(series):
            gdf[col] = series.replace(num_nulls, pd.NA)
        elif str_nulls and (
            pd.api.types.is_string_dtype(series) or pd.api.types.is_object_dtype(series)
        ):
            gdf[col] = series.replace(str_nulls, pd.NA)
    return gdf
