"""HTML 文字列をカタログ正規化値へ変換する。

KSJ の詳細ページ HTML はデータセット間でラベルが揺れるため、緩いマッチで
正規化する。未知入力は警告ログ用途で原文をそのまま返す。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, get_args

from ksj.catalog.schema import Format, LicenseProfile

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


GeometryType = Literal["point", "line", "polygon", "raster"]

# name 末尾の「（ポリゴン）」「（ポイント）」「（ライン）」「（ラスタ版）」は
# KSJ の命名慣行で確実に geometry を指し示すため最優先で採用する。
# （ラスタ版）は 1 件のみだが他のパターンで誤検出しないよう先に除外する。
_NAME_PAREN_GEOMETRY: list[tuple[str, GeometryType]] = [
    ("ポリゴン", "polygon"),
    ("ポイント", "point"),
    ("ライン", "line"),
    ("ラスタ版", "raster"),
    ("ラスタ", "raster"),
]


def infer_geometry_types(name: str) -> list[GeometryType]:
    """データセット名から geometry 種別を推定する。

    KSJ の命名慣行に沿って name 内のカッコ表記 (「（ポリゴン）」等) を検出する。
    同一データセットで 2 種類 (「（ポリゴン）（ポイント）」) が併記されるケースは
    name 内の出現順で両方返す。推定不能な場合は空配列を返す (「メッシュ」等の単純
    名は実データ読込なしに geometry を決められないため、保守的に [] を返して
    後続フェーズでの手動補完に委ねる)。
    """
    matches: list[tuple[int, GeometryType]] = []
    for keyword, geom in _NAME_PAREN_GEOMETRY:
        if any(geom == g for _, g in matches):
            continue
        for pattern in (f"（{keyword}）", f"({keyword})"):
            pos = name.find(pattern)
            if pos >= 0:
                matches.append((pos, geom))
                break
    matches.sort(key=lambda x: x[0])
    return [g for _, g in matches]


# ---- License ----------------------------------------------------------------
# KSJ 詳細ページの「使用許諾条件」欄の文字列を LicenseProfile に正規化する。
# 実測分布は docs/roadmap.md の Phase 9 節参照。大分類:
#   1) 非商用 (55 件) ... 「非商用」単独または「有償刊行物」注記つき
#   2) CC_BY_4.0 (24 件) ... 「オープンデータ（CC_BY_4.0）」
#   3) CC_BY_4.0 一部制限 (14 件) ... 「（一部制限）」付き、県別/市区町村別条件など
#   4) 商用可 (18 件) ... 「商用可」
#   5) 年度分岐 (9 件) ... 「YYYY年以降：X / 上記以外：Y」等
#   6) 空 (1 件) ... A48

_YEAR_MARKER_RE = re.compile(r"\d{4}\s*年(?:度)?")
_YEAR_THRESHOLD_RE = re.compile(r"\d{4}\s*年(?:度)?(?:（[^）]+）)?\s*以[降後]")
_YEAR_KEY_HEAD_RE = re.compile(r"(\d{4})")
_ELSE_KEY_RE = re.compile(r"(上記以外|それ以外)")
_YEAR_BLOCK_RE = re.compile(
    r"(?P<key>"
    r"(?:\d{4}\s*年(?:度)?(?:（[^）]+）)?(?:以[降後]|以前)?"
    r"(?:\s*[、,]\s*\d{4}\s*年(?:度)?(?:（[^）]+）)?)*)"
    r"|上記以外|それ以外"
    r")"
    r"\s*[：:]?\s*"
)

# KSJ 側の表記揺れ (全角アンダースコア、スペース、ハイフン、タイポ「CC_B.Y」) を吸収する
_CC_BY_VARIANTS: tuple[str, ...] = ("CC_BY_4.0", "CC_BY 4.0", "CC-BY 4.0", "CC_B.Y_4.0")
_PARTIAL_VARIANTS: tuple[str, ...] = ("（一部制限）", "(一部制限)")

# (検出キーワード群, constraints に追加するラベル) のリスト。
# license_raw に複数該当があれば重ねて付与する (例: CC_BY_4.0（一部制限） + 岡山県のみ非商用)
_CONSTRAINT_MARKERS: list[tuple[tuple[str, ...], str]] = [
    (("岡山県のみ非商用",), "岡山県のみ非商用"),
    (("有償刊行物",), "有償刊行物を使用"),
    (("都道府県毎", "市区町村", "地方公共団体ごと"), "市区町村/都道府県毎の個別条件あり"),
    (("申請等必要", "申請が必要"), "二次利用時に二次利用申請が必要な場合あり"),
]


def _has_year_branching(text: str) -> bool:
    """年度別分岐が存在するかの判定。

    「整備年度」「作成年度」のような属性的年度は分岐とみなさない (N06 等は
    一部制限 + 注記のため flat 分類に寄せる)。分岐 trigger は以下のいずれか:
    - 「XXXX年以降」「XXXX年以後」のような閾値表現
    - 「XXXX年」+「上記以外」の対 (A09 型)
    - 複数の異なる年度が出現 (P29 型「2023年度、2021年度：X / 2013年度：Y」)
    """
    if "整備年度" in text or "作成年度" in text:
        return False
    if _YEAR_THRESHOLD_RE.search(text):
        return True
    has_else_marker = "上記以外" in text or "それ以外" in text
    unique_years = set(_YEAR_MARKER_RE.findall(text))
    if has_else_marker and len(unique_years) >= 1:
        return True
    return len(unique_years) >= 2


def _parse_year_branches(text: str) -> dict[str, LicenseProfile]:
    """年度別条件を by_year 辞書に分解する。

    best-effort: 完璧にパースできないケースはトップレベルで mixed_by_year にまとめ、
    この関数は最低限拾えた年度だけを返す。空 dict なら分岐検出は失敗。
    """
    positions: list[tuple[int, int, str]] = [
        (m.start(), m.end(), m.group("key")) for m in _YEAR_BLOCK_RE.finditer(text)
    ]
    if not positions:
        return {}

    branches: dict[str, LicenseProfile] = {}
    for i, (_start, end, key) in enumerate(positions):
        next_start = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        value_text = text[end:next_start].strip()
        if not value_text:
            continue
        child = _classify_flat(value_text, nested=True)
        year_match = _YEAR_KEY_HEAD_RE.search(key)
        if year_match:
            branches[year_match.group(1)] = child
        elif _ELSE_KEY_RE.search(key):
            branches["_else"] = child

    return branches


def _classify_flat(text: str, nested: bool = False) -> LicenseProfile:
    """単一分類に落とし込む (年度分岐を含まない text を前提)。

    `nested=True` の場合、制約抽出は最小限に留め子プロファイルをコンパクトにする。
    """
    constraints: list[str] = []
    if not nested:
        for keywords, label in _CONSTRAINT_MARKERS:
            if any(k in text for k in keywords):
                constraints.append(label)

    # 判定優先順: 「一部制限」 > 非商用 > CC_BY_4.0 > 商用可 > 利用規約のみ > unknown
    has_cc_by = any(v in text for v in _CC_BY_VARIANTS)
    has_partial = any(v in text for v in _PARTIAL_VARIANTS)
    has_nc = "非商用" in text
    has_commercial_ok = "商用可" in text

    if has_cc_by and has_partial:
        return LicenseProfile(
            kind="cc_by_4_0_partial",
            commercial_use="conditional",
            attribution_required=True,
            derivative_works=True,
            constraints=constraints,
        )

    # 「非商用」と「商用可」が同居する文面は年度分岐以外では通常存在しないが、
    # 子プロファイルで両方が現れたら商用可側を優先 (分岐の「上記以外：非商用」等を
    # 逆に取らないため、flat の判定は text ブロック単位で独立に行う)
    if has_nc and not has_commercial_ok:
        return LicenseProfile(
            kind="non_commercial",
            commercial_use=False,
            attribution_required=True,
            derivative_works="unknown",
            constraints=constraints,
        )

    if has_cc_by:
        return LicenseProfile(
            kind="cc_by_4_0",
            commercial_use=True,
            attribution_required=True,
            derivative_works=True,
            constraints=constraints,
        )

    if has_commercial_ok:
        return LicenseProfile(
            kind="commercial_ok",
            commercial_use=True,
            attribution_required=True,
            derivative_works="unknown",
            constraints=constraints,
        )

    # KSJ 利用規約のみを指示する A31a 等 (CC_BY / 商用可否の明示なし)
    if "利用規約" in text or "国土数値情報ダウンロードサイト" in text:
        return LicenseProfile(
            kind="site_terms_only",
            commercial_use="unknown",
            attribution_required=True,
            derivative_works="unknown",
            constraints=constraints,
        )

    return LicenseProfile(
        kind="unknown",
        commercial_use="unknown",
        attribution_required=True,
        derivative_works="unknown",
        constraints=constraints,
    )


def normalize_license(license_raw: str | None) -> LicenseProfile:
    """HTML の利用許諾条件テキストを LicenseProfile に正規化する。

    空・None → ``kind="unknown"``。年度分岐を検出した場合は ``kind="mixed_by_year"``
    を返し、分岐ごとの子プロファイルを ``by_year`` に詰める (best-effort)。
    単一分類に落とせる場合は ``_classify_flat`` の結果を返す。
    """
    if license_raw is None:
        return LicenseProfile(kind="unknown", commercial_use="unknown", derivative_works="unknown")
    text = license_raw.strip()
    if not text:
        return LicenseProfile(kind="unknown", commercial_use="unknown", derivative_works="unknown")

    if _has_year_branching(text):
        by_year = _parse_year_branches(text)
        if by_year:
            return LicenseProfile(
                kind="mixed_by_year",
                commercial_use="conditional",
                attribution_required=True,
                derivative_works="unknown",
                constraints=["年度ごとに条件が異なる"],
                by_year=by_year,
            )
        # 分岐検出は失敗したが trigger はあった → constraints で通知して flat 分類
        flat = _classify_flat(text)
        flat.constraints = [*flat.constraints, "年度別条件の可能性あり (license_raw 要確認)"]
        return flat

    return _classify_flat(text)


__all__ = [
    "GeometryType",
    "Scope",
    "ScopeHints",
    "classify_row_format",
    "classify_scope",
    "classify_url_format",
    "detect_formats_in_text",
    "infer_geometry_types",
    "normalize_crs",
    "normalize_license",
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
