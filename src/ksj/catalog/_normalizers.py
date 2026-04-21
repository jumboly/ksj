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

    HTML の「世界測地系」は JGD2000 と JGD2011 を区別しない。曖昧解消は
    filename サフィックスで行う:

    1. ``-jgd2011`` → 6668 (JGD2011)
    2. ``-tky``     → 4301 (Tokyo Datum)
    3. ``-jgd`` (末尾数字なし) → 4612 (JGD2000)
    4. サフィックス無し → 6668 (JGD2011) を既定

    4 のサフィックス無しを 6668 に倒すのは KSJ 側の慣行に合わせたもの。KSJ は
    旧測地系版と新測地系版を並行配信するときに限り suffix を付け、単一配信では
    pre-2011 の年度であっても JGD2011 に再投影して提供する (L01 1983 年版など
    全年度 suffix 無し + 6668 単一系統になっている) ため、年度連動の推定は入れない。

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


# ---- Version year inference ------------------------------------------------
_YEAR_IN_FILENAME_RE = re.compile(r"[-_]((?:19|20)\d{2})(?:\d{4})?(?=[-_.])")
_YEAR_TEXT_RE = re.compile(r"((?:19|20)\d{2})\s*年")
# 元号「平成21年」「昭和60年」「令和3年」等の 2 桁年を西暦に変換する
_ERA_YEAR_RE = re.compile(r"(昭和|平成|令和)\s*(\d{1,2})\s*年")
_ERA_BASE: dict[str, int] = {"昭和": 1925, "平成": 1988, "令和": 2018}


def infer_version_year(*, year_raw: str | None, filename: str) -> str:
    """ダウンロード行の年度列テキストと filename から version year (YYYY) を推定する。

    HTML「年度」列の方が filename より信頼できるため先に評価する。
    いずれにも該当しなければ ``"unknown"``。
    """
    raw = year_raw or ""
    m = _YEAR_TEXT_RE.search(raw)
    if m is not None:
        return m.group(1)
    m_era = _ERA_YEAR_RE.search(raw)
    if m_era is not None:
        base = _ERA_BASE[m_era.group(1)]
        return str(base + int(m_era.group(2)))
    m = _YEAR_IN_FILENAME_RE.search(filename)
    if m is not None:
        return m.group(1)
    return "unknown"


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

# 47 都道府県コード→正式名称 (JIS X 0401 準拠、都/道/府/県 サフィックス付き)。
# prefecture セル判定および DOM id fallback 時の表示名に使用する。
_PREF_CODE_TO_NAME: dict[int, str] = {
    1: "北海道",
    2: "青森県",
    3: "岩手県",
    4: "宮城県",
    5: "秋田県",
    6: "山形県",
    7: "福島県",
    8: "茨城県",
    9: "栃木県",
    10: "群馬県",
    11: "埼玉県",
    12: "千葉県",
    13: "東京都",
    14: "神奈川県",
    15: "新潟県",
    16: "富山県",
    17: "石川県",
    18: "福井県",
    19: "山梨県",
    20: "長野県",
    21: "岐阜県",
    22: "静岡県",
    23: "愛知県",
    24: "三重県",
    25: "滋賀県",
    26: "京都府",
    27: "大阪府",
    28: "兵庫県",
    29: "奈良県",
    30: "和歌山県",
    31: "鳥取県",
    32: "島根県",
    33: "岡山県",
    34: "広島県",
    35: "山口県",
    36: "徳島県",
    37: "香川県",
    38: "愛媛県",
    39: "高知県",
    40: "福岡県",
    41: "佐賀県",
    42: "長崎県",
    43: "熊本県",
    44: "大分県",
    45: "宮崎県",
    46: "鹿児島県",
    47: "沖縄県",
}
# 正式名称および短縮形 (「東京」「京都」) の両方から code を逆引きできる辞書。
# KSJ HTML は通常「東京都」等の正式名称だが、一部で短縮形が出現する可能性を許容する。
# `{正式, 短縮}` の set 展開で短縮形が正式名と一致する場合 (「北海道」) は 1 エントリに収束する。
_PREF_NAMES: dict[str, int] = {
    name: code
    for code, full_name in _PREF_CODE_TO_NAME.items()
    for name in {full_name, re.sub(r"(都|府|県)$", "", full_name)}
}

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

# 北海道開発局 / 地方整備局 8 件。原文 (日本語名) をそのまま保持する方針なので
# code への alias は持たない。filename の数値接頭辞 (A53-23-82_*.zip 等) は
# DOM id fallback (_BUREAU_DOM_CODES) 経由で数値が `bureau` に入ることがあるが、
# 現行カタログのエントリは全て HTML text 経由で日本語名になる。
# 沖縄総合事務局は現カタログに出現せず未収録 (出現したら追加する)。
_BUREAU_NAMES: frozenset[str] = frozenset(
    {
        "北海道開発局",
        "東北地方整備局",
        "関東地方整備局",
        "北陸地方整備局",
        "中部地方整備局",
        "近畿地方整備局",
        "中国地方整備局",
        "四国地方整備局",
        "九州地方整備局",
    }
)

# 三大都市圏の判定用語彙。
# HTML text (KSJ 詳細ページの「地域」列) と filename の英字接頭辞の両方に現れうるが、
# どちらが来ても原文をそのまま ``urban_area`` フィールドに入れる。
# 「関東圏」と「首都圏」のような KSJ 内の表記揺れは canonical 化せず、統合時の
# bucket 化や推薦での同一視は downstream (integrator / LLM) に委ねる。
_URBAN_AREA_TEXT_TOKENS: frozenset[str] = frozenset({"首都圏", "関東圏", "中部圏", "近畿圏"})
_URBAN_AREA_FILENAME_TOKENS: frozenset[str] = frozenset({"SYUTO", "CHUBU", "KINKI"})


@dataclass(slots=True)
class ScopeHints:
    """HTML のセル情報 + DOM id + filename から scope を推定した結果。"""

    scope: Scope
    pref_code: int | None = None
    pref_name: str | None = None
    # 原文を 1 フィールドで保持 (_code / _name 分離はしない)
    region: str | None = None
    bureau: str | None = None
    urban_area: str | None = None
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


# KSJ の ``prefectureNN`` 慣行は以下の 3 区間に分かれる。
# 以前はマジックナンバー (>=80 / >=48) で判定していたが、未使用帯 (01-47/51-59/81-89 以外)
# が silent に region 化する退行リスクがあったため、明示的な frozenset で
# 未知値は None (scope 不明) に倒す運用に改めた。
# 地方区分 51..59: 北海道 / 東北 / 関東 / 中部 / 近畿 / 中国 / 四国 / 九州 / 沖縄
# 整備局等 81..89: 北海道開発局 / 東北 / 関東 / 北陸 / 中部 / 近畿 / 中国 / 四国 / 九州
_PREF_DOM_CODES: frozenset[int] = frozenset(range(1, 48))
_REGION_DOM_CODES: frozenset[int] = frozenset(range(51, 60))
_BUREAU_DOM_CODES: frozenset[int] = frozenset(range(81, 90))


def _parse_dom_id(dom_id: str | None) -> tuple[str, str] | None:
    """td の id 属性から (種別, 値) を抽出する。

    ``prefectureNN`` は KSJ 慣行で 01-47=都道府県 / 51-59=地方区分 /
    81-89=開発局・整備局 の 3 区間に対応する。未知区間は None を返して
    呼び出し側で special 等にフォールバックさせる。
    ``aXXXX`` はメッシュコード (L03-b: id=``a3036-1``)。
    """
    if not dom_id:
        return None
    m = re.match(r"prefecture(\d{2})", dom_id)
    if m:
        code = m.group(1)
        code_int = int(code)
        if code_int in _BUREAU_DOM_CODES:
            return ("bureau", code)
        if code_int in _REGION_DOM_CODES:
            return ("region", code)
        if code_int in _PREF_DOM_CODES:
            return ("pref", code)
        return None
    m = re.match(r"a(\d{4,9})", dom_id)  # L03-b: id="a3036-1"
    if m:
        return ("mesh", m.group(1))
    return None


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
        return ScopeHints("region", region=text)
    if text in _BUREAU_NAMES:
        return ScopeHints("regional_bureau", bureau=text)

    if text in _URBAN_AREA_TEXT_TOKENS:
        return ScopeHints("urban_area", urban_area=text)

    # 都道府県名。`_PREF_NAMES` は「東京都」「東京」どちらからも code 逆引き可能。
    # pref_name には text 原文をそのまま入れる (サフィックスの有無を曲げない)。
    if text in _PREF_NAMES:
        return ScopeHints("prefecture", pref_code=_PREF_NAMES[text], pref_name=text)

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
            # text が `_REGION_NAMES` に無い呼称 (「甲信越・北陸地方」等) は text 優先、
            # text が空なら DOM id の数値 code (例: "55") をそのまま region に入れる
            return ScopeHints("region", region=text or value)
        if kind == "bureau":
            # text が空なら DOM id の数値 code (例: "81") をそのまま bureau に入れる。
            # text があればその日本語名を優先
            return ScopeHints("regional_bureau", bureau=text or value)
        if kind == "mesh":
            # DOM id="aXXXX" は KSJ 慣行で概ね 4 桁 (1次メッシュ) を指すため、
            # 桁数が合わないときは 1次メッシュ (最粗) にフォールバックする
            scope = _VALID_MESH_DIGITS.get(len(value), "mesh1")
            return ScopeHints(scope, mesh_code=value)  # type: ignore[arg-type]

    if filename is not None:
        upper = filename.upper()
        for token in _URBAN_AREA_FILENAME_TOKENS:
            if token in upper:
                # filename の英字接頭辞をそのまま保存 (SYUTO/CHUBU/KINKI)。
                # HTML text を持たない配布向けの保険で、現行カタログで発火する
                # エントリは無い (実運用では HTML text 経由で日本語が入る)。
                return ScopeHints("urban_area", urban_area=token)

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


__all__ = [
    "GeometryType",
    "Scope",
    "ScopeHints",
    "classify_row_format",
    "classify_scope",
    "classify_url_format",
    "detect_formats_in_text",
    "infer_geometry_types",
    "infer_version_year",
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
