"""統合結果を GeoPackage / GeoParquet として書き出す層。

フォーマット別の実装は ``geopackage`` / ``parquet`` モジュールに分け、呼び出し側
には ``write`` ディスパッチャだけを公開する (pipeline 側の分岐を最小化する目的)。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any

from ksj.reader.vector import VectorLayer
from ksj.writer import geopackage, parquet


class OutputFormat(StrEnum):
    """統合出力で選べる形式。Typer の choices 生成に使えるよう StrEnum。"""

    GPKG = "gpkg"
    PARQUET = "parquet"


_EXTENSION_BY_FORMAT: dict[OutputFormat, str] = {
    OutputFormat.GPKG: "gpkg",
    OutputFormat.PARQUET: "parquet",
}


def resolve_extension(format: OutputFormat | str) -> str:
    """``OutputFormat`` に対応する拡張子 (gpkg / parquet) を返す。"""
    return _EXTENSION_BY_FORMAT[OutputFormat(format)]


def write(
    layers: Iterable[VectorLayer],
    dest: Path,
    *,
    metadata: Mapping[str, Any],
    format: OutputFormat | str,
) -> Path:
    """``format`` に応じて GPKG / Parquet writer に委譲する。"""
    fmt = OutputFormat(format)
    if fmt is OutputFormat.GPKG:
        return geopackage.write_layers(layers, dest, metadata=metadata)
    if fmt is OutputFormat.PARQUET:
        return parquet.write_layers(layers, dest, metadata=metadata)
    raise ValueError(f"未サポートの出力形式: {fmt}")


__all__ = ["OutputFormat", "resolve_extension", "write"]
