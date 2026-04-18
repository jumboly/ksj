"""カタログ YAML の pydantic スキーマ定義。

docs/catalog.md の仕様を型化する。正規化値 (format, crs, scope) と
HTML 原文 (format_raw, crs_raw) の両方を保持することで、スクレイパの
取りこぼしや未知値を失わないようにする。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Scope = Literal[
    "national",
    "region",
    "regional_bureau",
    "prefecture",
    "urban_area",
    "river",
    "municipality",
    "mesh1",
    "mesh2",
    "mesh3",
    "mesh4",
    "mesh5",
    "mesh6",
    "special",
]

Format = Literal[
    "gml_jpgis21",
    "gml_jpgis2014",
    "citygml",
    "shp",
    "geojson",
    "csv",
    "geotiff",
    # 1 つの ZIP に複数形式が同梱されているケース (N03 等。HTML のデータフォーマット欄が複数言及)
    "multi",
    "unknown",
]

Coverage = Literal["full", "partial"]

# EPSG 整数で保持。docs/catalog.md の「CRS の正規化」表を参照。
KNOWN_EPSG = {4301, 4612, 6668, 4326}

# scope → バリデーションで必須となる識別子コードフィールド名。
# ここに無い scope (national, special) は付随コード無しで成立する。
_SCOPE_REQUIRED_CODE_FIELD: dict[str, str] = {
    "prefecture": "pref_code",
    "region": "region_code",
    "regional_bureau": "bureau_code",
    "urban_area": "urban_area_code",
    "river": "river_id",
    "municipality": "muni_code",
    **{f"mesh{i}": "mesh_code" for i in range(1, 7)},
}

# scope → 表示用の識別子フィールド名のフォールバック順 (最初に埋まっている値を採用)。
_SCOPE_DISPLAY_FIELDS: dict[str, tuple[str, ...]] = {
    "prefecture": ("pref_name", "pref_code"),
    "region": ("region_name", "region_code"),
    "regional_bureau": ("bureau_name", "bureau_code"),
    "urban_area": ("urban_area_name", "urban_area_code"),
    "river": ("river_name", "river_id"),
    "municipality": ("muni_name", "muni_code"),
    "special": ("special_name", "special_code"),
    **{f"mesh{i}": ("mesh_code",) for i in range(1, 7)},
}


class FileEntry(BaseModel):
    """1 URL 分のダウンロード対象。HTML テーブルの 1 行に対応する。

    scope ごとに異なる識別子 (pref_code, mesh_code, 等) を discriminated union
    ではなく平坦に持つ設計を採用している。YAML の可読性と既存エディタ補完の素朴さ
    を優先する判断。
    """

    model_config = ConfigDict(extra="forbid")

    scope: Scope
    url: str
    format: Format
    format_raw: str | None = None
    crs: int | None = Field(
        default=None,
        description="EPSG 整数コード。未整備 (`unknown` 形式) や TP-only を許容するため optional",
    )
    crs_raw: str | None = None
    size_bytes: int | None = None

    pref_code: int | None = Field(default=None, ge=1, le=47)
    pref_name: str | None = None
    region_code: str | None = None
    region_name: str | None = None
    bureau_code: str | None = None
    bureau_name: str | None = None
    urban_area_code: str | None = None
    urban_area_name: str | None = None
    mesh_code: str | None = None
    river_id: str | None = None
    river_name: str | None = None
    muni_code: str | None = None
    muni_name: str | None = None
    special_code: str | None = None
    special_name: str | None = None

    # データセット固有の但し書き (例: mesh* 統計系の Shapefile 男女削除)
    attribute_caveat: str | None = None

    @model_validator(mode="after")
    def _check_scope_keys(self) -> FileEntry:
        # 整合を崩したままカタログに入ると統合時にサイレントに落ちるため読込時点で弾く
        field = _SCOPE_REQUIRED_CODE_FIELD.get(self.scope)
        if field is not None and getattr(self, field) is None:
            raise ValueError(f"{self.scope} scope には {field} が必須")
        return self

    @property
    def scope_identifier(self) -> str:
        """表示用の scope 識別子 (例: 「北海道」「5339」「SYUTO」)。

        CLI の info 表示などが scope 別フィールドを直接探らなくて済むよう、
        schema 側にまとめる。name が無ければ code にフォールバックする。
        """
        for field in _SCOPE_DISPLAY_FIELDS.get(self.scope, ()):
            value = getattr(self, field)
            if value is not None:
                return str(value)
        return ""


class Version(BaseModel):
    """ある年度の配布データ一式。

    files は空 (``[]``) も許す: A55 のようなフォーム配布データセットは URL を
    列挙できないため、カタログ上は version を空で保持しメタのみ提供する。
    """

    model_config = ConfigDict(extra="forbid")

    reference_date: date | None = None
    files: list[FileEntry] = Field(default_factory=list)
    # データセットごとに異なる欠損値コード (例: -999, 9999)。統合時に NaN 化する
    null_values: list[int | float | str] = Field(default_factory=list)
    notes: str | None = None


class Dataset(BaseModel):
    """1 データセット (例: N03 行政区域)。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    category: str | None = None
    detail_page: str | None = None
    geometry_types: list[Literal["point", "line", "polygon", "raster"]] = Field(
        default_factory=list
    )
    license: str | None = None
    license_raw: str | None = None
    coverage: Coverage = "full"
    coverage_notes: str | None = None
    notes: str | None = None
    # year 文字列 → Version。YAML 側では "2025" のようなキーで保持される
    versions: dict[str, Version] = Field(default_factory=dict)


class Catalog(BaseModel):
    """カタログ YAML 全体のルート。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    generated_at: datetime | None = None
    source_index: str | None = None
    total_datasets: int | None = None
    # データセットコード (例: "N03", "L03-a") → Dataset
    datasets: dict[str, Dataset] = Field(default_factory=dict)
