"""HTML 文字列をカタログ正規化値へ変換する。

KSJ の詳細ページ HTML はデータセット間でラベルが揺れるため、緩いマッチで
正規化する。未知入力は警告ログ用途で原文をそのまま返す。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, get_args

from ksj.catalog.schema import Format

# ---- Format ----------------------------------------------------------------
# HTML の「データフォーマット」セクションに現れるキーワードから識別
_FORMAT_KEYWORDS: list[tuple[str, Format]] = [
    ("JPGIS2014", "gml_jpgis2014"),
    ("JPGIS 2014", "gml_jpgis2014"),
    ("JPGIS2.1", "gml_jpgis21"),
    ("JPGIS 2.1", "gml_jpgis21"),
    ("CityGML", "citygml"),
    ("シェープファイル", "shp"),
    ("GeoJSON", "geojson"),
    ("GEOJSON", "geojson"),
    ("CSV", "csv"),
    ("GeoTIFF", "geotiff"),
]


def detect_formats_in_text(text: str) -> list[Format]:
    """ページ上部のデータフォーマット説明文から全ての該当 format を抽出する。"""
    found: list[Format] = []
    for keyword, fmt in _FORMAT_KEYWORDS:
        if keyword in text and fmt not in found:
            found.append(fmt)
    # 「GML形式」単独 (JPGIS バージョン未指定) は旧規格とみなす
    if "GML形式" in text and "gml_jpgis2014" not in found and "gml_jpgis21" not in found:
        found.append("gml_jpgis21")
    return found


def classify_url_format(*, filename: str, formats_in_page: list[Format]) -> Format:
    """ページ記載の formats と URL から 1 つの format を決定する。

    1 つだけ記載があればそれを採用。複数記載がある場合は filename の
    サフィックス (``_GML.zip`` / ``_SHP.zip`` / ``_GEOJSON.zip`` 等) を
    ヒントに使う。それでも確定できなければ multi とする (ZIP 内部に
    複数形式が同梱されているケース)。
    """
    unique = list(dict.fromkeys(formats_in_page))
    if len(unique) == 1:
        return unique[0]
    if not unique:
        return "unknown"

    upper = filename.upper()
    if "_SHP.ZIP" in upper and "shp" in unique:
        return "shp"
    if "_GEOJSON.ZIP" in upper and "geojson" in unique:
        return "geojson"
    if "_GML.ZIP" in upper:
        # _GML.zip しかない配布では GML 版が代表だが、他形式も同梱される
        # ケースが一般的 (N03 等) なので multi を返す
        return "multi"
    if "SHAPE" in upper and "shp" in unique:
        return "shp"
    return "multi"


# ---- CRS -------------------------------------------------------------------
_CRS_TEXT_MAP: list[tuple[str, int]] = [
    ("旧測地系", 4301),
    ("Tokyo Datum", 4301),
    ("WGS84", 4326),
    ("WGS 84", 4326),
]


def normalize_crs(*, cell_text: str, filename: str | None = None) -> tuple[int | None, str]:
    """「測地系」列のテキスト + filename サフィックスで EPSG を決定する。

    HTML の「世界測地系」は JGD2000 と JGD2011 を区別しない。filename に
    ``-jgd2011`` があれば 6668、``-jgd`` があれば 4612 とフォールバックする。
    filename 情報が無く「世界測地系」のみなら、最新である JGD2011 (6668)
    を仮定する (A55 / N03 等の新規データセット)。

    返り値は (epsg_or_none, 原文) のタプル。
    """
    raw = cell_text.strip()
    lowered_name = (filename or "").lower()

    for keyword, epsg in _CRS_TEXT_MAP:
        if keyword in raw:
            return epsg, raw

    if "日本測地系" in raw:
        return 4301, raw
    if "世界測地系" in raw or "JGD" in raw:
        if "jgd2011" in lowered_name:
            return 6668, raw
        if "-tky" in lowered_name:
            return 4301, raw
        if re.search(r"-jgd(?![0-9])", lowered_name):
            return 4612, raw
        return 6668, raw

    return None, raw


# ---- Scope -----------------------------------------------------------------
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

# 47 都道府県コード→名称。prefecture セル判定用
_PREF_CODE_TO_NAME: dict[int, str] = {
    1: "北海道",
    2: "青森",
    3: "岩手",
    4: "宮城",
    5: "秋田",
    6: "山形",
    7: "福島",
    8: "茨城",
    9: "栃木",
    10: "群馬",
    11: "埼玉",
    12: "千葉",
    13: "東京",
    14: "神奈川",
    15: "新潟",
    16: "富山",
    17: "石川",
    18: "福井",
    19: "山梨",
    20: "長野",
    21: "岐阜",
    22: "静岡",
    23: "愛知",
    24: "三重",
    25: "滋賀",
    26: "京都",
    27: "大阪",
    28: "兵庫",
    29: "奈良",
    30: "和歌山",
    31: "鳥取",
    32: "島根",
    33: "岡山",
    34: "広島",
    35: "山口",
    36: "徳島",
    37: "香川",
    38: "愛媛",
    39: "高知",
    40: "福岡",
    41: "佐賀",
    42: "長崎",
    43: "熊本",
    44: "大分",
    45: "宮崎",
    46: "鹿児島",
    47: "沖縄",
}
_PREF_NAMES = {v: k for k, v in _PREF_CODE_TO_NAME.items()}

# 地方ブロック (KSJ 慣行で 52-59 のコードを付ける)
_REGION_NAMES = {
    "北海道地方",
    "東北地方",
    "関東地方",
    "中部地方",
    "近畿地方",
    "中国地方",
    "四国地方",
    "九州地方",
    "沖縄地方",
}

# 地方整備局 (82-89 等)
_BUREAU_NAMES = {
    "東北地方整備局",
    "関東地方整備局",
    "北陸地方整備局",
    "中部地方整備局",
    "近畿地方整備局",
    "中国地方整備局",
    "四国地方整備局",
    "九州地方整備局",
}

# 三大都市圏。HTML や filename に現れる英字コード
_URBAN_AREA_CODES = {"SYUTO": "首都圏", "CHUBU": "中部圏", "KINKI": "近畿圏"}


@dataclass(slots=True)
class ScopeHints:
    """HTML のセル情報 + DOM id + filename から scope を推定した結果。"""

    scope: Scope
    pref_code: int | None = None
    pref_name: str | None = None
    region_code: str | None = None
    region_name: str | None = None
    bureau_code: str | None = None
    bureau_name: str | None = None
    urban_area_code: str | None = None
    urban_area_name: str | None = None
    mesh_code: str | None = None


_VALID_MESH_DIGITS: dict[int, str] = {
    2: "mesh1",
    4: "mesh2",
    6: "mesh3",
    7: "mesh4",
    8: "mesh5",
    9: "mesh6",
}


def _parse_dom_id(dom_id: str | None) -> tuple[str, str] | None:
    """td の id 属性から (種別, 値) を抽出する (例: prefecture13 → ("pref", "13"))。"""
    if not dom_id:
        return None
    m = re.match(r"prefecture(\d{2})", dom_id)
    if m:
        return ("pref", m.group(1))
    m = re.match(r"a(\d{4,9})", dom_id)  # L03-b: id="a3036-1"
    if m:
        return ("mesh", m.group(1))
    return None


_URBAN_AREA_JP_NAMES = {"首都圏": "SYUTO", "中部圏": "CHUBU", "近畿圏": "KINKI", "関東圏": "SYUTO"}


def classify_scope(
    *,
    cell_text: str,
    dom_id: str | None = None,
    filename: str | None = None,
) -> ScopeHints:
    """地域セルの情報から scope と付随コード/名称を推定する。

    優先順: 1) テキストが全国/地方/整備局/都市圏/都道府県名に一致する 2) 数字メッシュ
    コード 3) DOM id ヒント (prefectureNN や aMESHCODE) 4) filename 中の圏域コード
    5) 特殊 (special)。テキストが都市圏名なら DOM id が prefectureXX でも text を優先
    する (A03 のように id 属性が他用途で流用されているケースを避けるため)。
    """
    text = cell_text.strip()

    if text in {"全国", "全国版"}:
        return ScopeHints("national")

    if text in _REGION_NAMES:
        return ScopeHints("region", region_name=text)
    if text in _BUREAU_NAMES:
        return ScopeHints("regional_bureau", bureau_name=text)

    if text in _URBAN_AREA_JP_NAMES:
        code = _URBAN_AREA_JP_NAMES[text]
        return ScopeHints("urban_area", urban_area_code=code, urban_area_name=text)

    # 都道府県名 (「東京都」「京都府」等を吸収)
    stripped = re.sub(r"(都|道|府|県)$", "", text)
    if stripped in _PREF_NAMES:
        pref_code = _PREF_NAMES[stripped]
        return ScopeHints(
            "prefecture", pref_code=pref_code, pref_name=_PREF_CODE_TO_NAME[pref_code]
        )
    if text in _PREF_NAMES:
        pref_code = _PREF_NAMES[text]
        return ScopeHints("prefecture", pref_code=pref_code, pref_name=text)

    if re.fullmatch(r"\d{2,9}", text):
        scope = _VALID_MESH_DIGITS.get(len(text))
        if scope is not None:
            return ScopeHints(scope, mesh_code=text)  # type: ignore[arg-type]

    # DOM id のフォールバック (text と矛盾しない場合のみ)
    id_hint = _parse_dom_id(dom_id)
    if id_hint is not None:
        kind, value = id_hint
        if kind == "pref":
            pref_code = int(value)
            return ScopeHints(
                "prefecture",
                pref_code=pref_code,
                pref_name=_PREF_CODE_TO_NAME.get(pref_code, text or None),
            )
        if kind == "mesh":
            scope = _VALID_MESH_DIGITS.get(len(value), "mesh2")
            return ScopeHints(scope, mesh_code=value)  # type: ignore[arg-type]

    if filename is not None:
        upper = filename.upper()
        for ua_code, ua_name in _URBAN_AREA_CODES.items():
            if ua_code in upper:
                return ScopeHints("urban_area", urban_area_code=ua_code, urban_area_name=ua_name)

    return ScopeHints("special")


__all__ = [
    "Scope",
    "ScopeHints",
    "classify_scope",
    "classify_url_format",
    "detect_formats_in_text",
    "normalize_crs",
]


# Scope Literal の確認 (schema.py との同期がずれた時に気付くため)
assert set(get_args(Scope)) == {
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
}
