"""ZIP 内のベクタファイルを pyogrio で読み込む。

GDAL の ``/vsizip/`` 仮想ファイルシステム経由で、ZIP を展開せず直接読む。
これにより N03 (1.5GB+ の SHP+GeoJSON+GML 同梱 ZIP) のような大物でも
ディスクに展開しなくて済む。
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import pyogrio


class NoMatchingFormatError(LookupError):
    """ZIP 内に format_preference に一致するベクタが 1 つも無いとき送出する。

    LookupError 系統に揃えているのは ``NoNationalSourceError`` 等他の
    「対象が見つからない」例外と挙動を統一するため (CLI 側でまとめて拾える)。
    """


# 拡張子 → 形式キー (FileEntry.format の正規化値と揃える)。
# Phase 4 では shp / gml / geojson のみ扱う。CityGML / GeoTIFF / CSV は対象外。
_EXT_TO_FORMAT: dict[str, str] = {
    ".shp": "shp",
    ".gml": "gml_jpgis21",
    ".geojson": "geojson",
    ".json": "geojson",
}

# 「形式キー」のエイリアス。CLI/カタログ表記が gml/gml_jpgis21/gml_jpgis2014 と
# 揺れるので、preference 指定時にどれが来てもマッチさせる。
_FORMAT_ALIASES: dict[str, set[str]] = {
    "shp": {"shp", "shapefile"},
    "gml_jpgis21": {"gml", "gml_jpgis21", "gml_jpgis2014"},
    "geojson": {"geojson", "json"},
}


def default_encoding_for(format_key: str) -> str | None:
    """format に対する既定エンコーディング。

    KSJ の Shapefile は歴史的にほぼ Shift_JIS (cp932) で、.cpg が付かない配布も
    多い。GML/GeoJSON は仕様上 UTF-8 が保証されるので pyogrio の自動判定に任せる
    (None を返す)。
    """
    if format_key == "shp":
        return "cp932"
    return None


@dataclass(slots=True)
class VectorLayer:
    """1 ファイル分の読み込み結果。layer_name は GPKG レイヤ名にそのまま使う想定。

    ``source_path`` は ``/vsizip/<zip>/<inner>`` の仮想パス。実ファイルは存在しない。
    """

    layer_name: str
    source_path: Path
    format: str
    gdf: gpd.GeoDataFrame


def _normalize_preferences(preferences: Iterable[str] | None) -> list[str]:
    """ユーザ指定 preference を内部キー順に正規化する。"""
    if preferences is None:
        # GML を優先する理由: KSJ は GML (JPGIS 2.1) を 1 次配布物としている。Shp は属性が
        # DBF 254 バイト制限で切られているケースがあり (例: A46-A48)、GML の方が忠実。
        return ["gml_jpgis21", "shp", "geojson"]
    normalized: list[str] = []
    for pref in preferences:
        key = pref.strip().lower()
        for canonical, aliases in _FORMAT_ALIASES.items():
            if key in aliases and canonical not in normalized:
                normalized.append(canonical)
                break
    return normalized


def _iter_vector_entries(zip_path: Path) -> Iterator[tuple[str, str]]:
    """ZIP 内のベクタファイルを (inner_name, format_key) で列挙する。

    ``inner_name`` は ZIP 内の相対パス。ディレクトリエントリ (末尾 ``/``) はスキップ。
    """
    with zipfile.ZipFile(zip_path) as zf:
        for inner in sorted(zf.namelist()):
            if inner.endswith("/"):
                continue
            format_key = _EXT_TO_FORMAT.get(Path(inner).suffix.lower())
            if format_key is not None:
                yield inner, format_key


def read_zip(
    zip_path: Path,
    *,
    format_preference: Iterable[str] | None = None,
    encoding: str | None = None,
) -> list[VectorLayer]:
    """ZIP 内の preference 順で見つかった全ベクタを読み込んで返す。

    同一 ZIP 内に同形式のファイルが複数あるケース (例: N03 の本体 + ``_prefecture``)
    では両方を読む。レイヤ名はファイル stem を使う。GDAL は Shapefile を読むとき
    同じディレクトリ (= ZIP 内同階層) の .shx / .dbf / .prj / .cpg を自動で参照する。

    ``encoding`` を指定すると pyogrio の ``encoding`` 引数にそのまま渡る。KSJ の
    Shapefile は実質 Shift_JIS (cp932) 固定、GML/GeoJSON は UTF-8 が仕様で保証
    されるので、pipeline 側で format ごとに切り替える想定。
    """
    preferences = _normalize_preferences(format_preference)

    by_format: dict[str, list[str]] = {}
    for inner, format_key in _iter_vector_entries(zip_path):
        by_format.setdefault(format_key, []).append(inner)

    chosen_format: str | None = next((p for p in preferences if p in by_format), None)
    if chosen_format is None:
        available = sorted(by_format)
        raise NoMatchingFormatError(
            f"{zip_path.name}: preference {preferences} に一致するベクタが見つからない"
            f" (利用可能: {available or 'なし'})"
        )

    layers: list[VectorLayer] = []
    for inner in by_format[chosen_format]:
        # GDAL VSI: /vsizip/<zip-path>/<inner> で ZIP 内ファイルを直接読める
        vsi_path = f"/vsizip/{zip_path}/{inner}"
        read_kwargs: dict[str, object] = {}
        if encoding is not None:
            read_kwargs["encoding"] = encoding
        gdf = pyogrio.read_dataframe(vsi_path, **read_kwargs)
        layers.append(
            VectorLayer(
                layer_name=Path(inner).stem,
                source_path=Path(vsi_path),
                format=chosen_format,
                gdf=gdf,
            )
        )
    return layers
