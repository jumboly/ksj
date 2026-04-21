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

# EPSG 整数で保持。docs/catalog.md の「CRS の正規化」表を参照。
KNOWN_EPSG = {4301, 4612, 6668, 4326}

# scope → バリデーションで必須となる識別子フィールド名。
# ここに無い scope (national / region / special) は付随識別子無しで成立する
# (region は KSJ 公開資料で慣用コードが明示されていないため任意)。
_SCOPE_REQUIRED_CODE_FIELD: dict[str, str] = {
    "prefecture": "pref_code",
    "regional_bureau": "bureau",
    "urban_area": "urban_area",
    "river": "river",
    "municipality": "municipality",
    **{f"mesh{i}": "mesh_code" for i in range(1, 7)},
}

# scope → 識別子フィールドのフォールバック順 (最初に埋まっている値を採用)。
# prefecture 以外は単一フィールドなので表示用・bucket 用とも同じ。prefecture のみ
# 表示時は pref_name 優先、bucket 化時は pref_code 優先 (表記ゆれ耐性のため)。
_SCOPE_IDENTIFIER_FIELDS: dict[str, tuple[str, ...]] = {
    "prefecture": ("pref_name", "pref_code"),
    "region": ("region",),
    "regional_bureau": ("bureau",),
    "urban_area": ("urban_area",),
    "river": ("river",),
    "municipality": ("municipality",),
    "special": ("special",),
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
    # Phase 5 追加。KSJ Shp は実質 Shift_JIS (cp932) 固定だが、新しめの配布で UTF-8 の
    # ケースもあり、HTML から自動抽出できないので optional で手書き override する余地を残す。
    encoding: Literal["utf-8", "cp932"] | None = None

    pref_code: int | None = Field(default=None, ge=1, le=47)
    pref_name: str | None = None
    # 日本語名が識別子。fallback 時は KSJ 慣行の数値/英字接頭辞が入りうる
    # (region 51-59 / bureau 81-89 / urban_area SYUTO/CHUBU/KINKI)
    region: str | None = None
    bureau: str | None = None
    urban_area: str | None = None
    river: str | None = None
    municipality: str | None = None
    special: str | None = None
    mesh_code: str | None = None

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
        for field in _SCOPE_IDENTIFIER_FIELDS.get(self.scope, ()):
            value = getattr(self, field)
            if value is not None:
                return str(value)
        return ""

    @property
    def scope_bucket_key(self) -> str:
        """分割統合でのバケット化キー。

        prefecture のみ表記ゆれ (「北海道」vs「北海道庁」) への耐性で JIS 整数
        ``pref_code`` を優先する。それ以外の scope では単一フィールドしか持たない
        ので ``scope_identifier`` と等価。
        """
        if self.scope == "prefecture":
            if self.pref_code is not None:
                return str(self.pref_code)
            return self.pref_name or ""
        return self.scope_identifier


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


# Phase 9: 用途タグ語彙 (enum 固定)。
# 自然言語要求からの推薦・フィルタで使う抽象タグなので、粒度は中〜粗で揃える。
# 「災害リスク全般」と「水害」のように階層関係のあるタグは併記可能 (list で複数付与)。
UseCase = Literal[
    "administrative_boundary",
    "transportation",
    "disaster_risk",
    "flood_risk",
    "land_use",
    "population",
    "facility",
    "terrain",
    "climate",
    "urban_planning",
    "economy",
]


class Dataset(BaseModel):
    """1 データセット (例: N03 行政区域)。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    category: str | None = None
    detail_page: str | None = None
    geometry_types: list[Literal["point", "line", "polygon", "raster"]] = Field(
        default_factory=list
    )
    # KSJ 詳細ページの「使用/利用許諾条件」欄の原文をそのまま保持する。
    # 構造化分類は「年度別分岐」「県別制限」等で判定条件が複雑化・恣意的になるため
    # 採用せず、原文のフィルタ/解釈は LLM / 人間レビューに委ねる方針。
    license_raw: str | None = None
    # ページ全体で宣言された利用可能 format 一覧 (union)。FileEntry.format = multi
    # の内訳参照先。詳細は docs/catalog.md の「format の語彙」節を参照。
    available_formats: list[Format] = Field(default_factory=list)
    description: str | None = None
    use_cases: list[UseCase] = Field(default_factory=list)
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
