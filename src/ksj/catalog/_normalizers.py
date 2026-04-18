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
# HTML の「データフォーマット」セクションおよびテーブルの「形式」列に現れるキーワード。
# ページ全体走査 (detect_formats_in_text) と行単位判定 (classify_row_format) で共用する。
# 比較は大文字化して部分一致で行うため、小文字/大文字の表記揺れはキーに書かず 1 エントリで済む。
_FORMAT_KEYWORDS: list[tuple[str, Format]] = [
    ("JPGIS2014", "gml_jpgis2014"),
    ("JPGIS 2014", "gml_jpgis2014"),
    ("JPGIS2.1", "gml_jpgis21"),
    ("JPGIS 2.1", "gml_jpgis21"),
    ("CITYGML", "citygml"),
    ("シェープ", "shp"),
    ("SHAPE", "shp"),
    ("GEOJSON", "geojson"),
    ("CSV", "csv"),
    ("GEOTIFF", "geotiff"),
]


def detect_formats_in_text(text: str) -> list[Format]:
    """HTML 文字列から全ての該当 format を抽出する。

    ページ上部の「データフォーマット」説明文と行単位の「形式」列の双方に使える。
    「GML形式」単独 (JPGIS バージョン未指定) は旧規格 (JPGIS 2.1) とみなす。
    """
    upper = text.upper()
    found: list[Format] = []
    for keyword, fmt in _FORMAT_KEYWORDS:
        if keyword.upper() in upper and fmt not in found:
            found.append(fmt)
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


def classify_row_format(*, cell_text: str, formats_in_page: list[Format]) -> Format:
    """詳細ページの「形式」列テキストから Format を決定する。

    「GML形式」単独 (JPGIS バージョン未指定) は、ページ内のフォーマット説明文で
    JPGIS2014 が宣言されていれば 2014 側に寄せる (N13 のように表は「GML形式」と
    書くが製品仕様書は JPGIS2014 準拠、というケース)。
    """
    found = detect_formats_in_text(cell_text)
    if not found:
        return "unknown"
    fmt = found[0]
    if fmt == "gml_jpgis21" and "gml_jpgis2014" in formats_in_page:
        return "gml_jpgis2014"
    return fmt


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

# 北海道開発局 = 81、地方整備局 = 82-89。KSJ URL の末尾コード (A53-23-82_*.zip
# 等) で確認済みの対応。沖縄総合事務局は現カタログに出現せずコード不明のため未収録
# (出現が確認できた時点で追加する)。
_BUREAU_NAME_TO_CODE: dict[str, str] = {
    "北海道開発局": "81",
    "東北地方整備局": "82",
    "関東地方整備局": "83",
    "北陸地方整備局": "84",
    "中部地方整備局": "85",
    "近畿地方整備局": "86",
    "中国地方整備局": "87",
    "四国地方整備局": "88",
    "九州地方整備局": "89",
}
_BUREAU_NAMES: set[str] = set(_BUREAU_NAME_TO_CODE)

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


# 日本の地域メッシュ規格 (JIS X 0410) の桁数 → 次数マッピング。
# 1次メッシュ (80km) = 4 桁、2次 (10km) = 6 桁、3次 (1km) = 8 桁、
# 分割 3次 (500m/250m/100m) は末尾に 1 桁ずつ区分コードが付与される。
_VALID_MESH_DIGITS: dict[int, str] = {
    4: "mesh1",
    6: "mesh2",
    8: "mesh3",
    9: "mesh4",
    10: "mesh5",
    11: "mesh6",
}


def _parse_dom_id(dom_id: str | None) -> tuple[str, str] | None:
    """td の id 属性から (種別, 値) を抽出する。

    KSJ の code 区間 (``prefectureNN`` の NN 値):
    - 01..47: 都道府県
    - 51..59: 地方区分 (51=北海道 / 52=東北 / 53=関東 / 54=中部(甲信越・北陸含む) /
      55=近畿 / 56=中国 / 57=四国 / 58=九州 / 59=沖縄)
    - 81..89: 北海道開発局 (81) および地方整備局 (82..89)

    ``aXXXX`` はメッシュコード (L03-b: id=``a3036-1``)。
    """
    if not dom_id:
        return None
    m = re.match(r"prefecture(\d{2})", dom_id)
    if m:
        code = m.group(1)
        code_int = int(code)
        if code_int >= 80:
            return ("bureau", code)
        if code_int >= 48:
            return ("region", code)
        return ("pref", code)
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
        # region の慣用コード体系は KSJ 公開資料で確認できないため、region_name のみで成立させる
        return ScopeHints("region", region_name=text)
    if text in _BUREAU_NAMES:
        return ScopeHints(
            "regional_bureau",
            bureau_code=_BUREAU_NAME_TO_CODE[text],
            bureau_name=text,
        )

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
        if kind == "region":
            # text が `_REGION_NAMES` に無い呼称 (「甲信越・北陸地方」等) でも code と
            # 元 text で region を成立させる
            return ScopeHints("region", region_code=value, region_name=text or None)
        if kind == "bureau":
            # text が空 (別表で整備局名が省略されている) でも code から bureau を成立させる
            return ScopeHints("regional_bureau", bureau_code=value, bureau_name=text or None)
        if kind == "mesh":
            # DOM id="aXXXX" は KSJ 慣行で概ね 4 桁 (1次メッシュ) を指すため、
            # 桁数が合わないときは 1次メッシュ (最粗) にフォールバックする
            scope = _VALID_MESH_DIGITS.get(len(value), "mesh1")
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
    "classify_row_format",
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
