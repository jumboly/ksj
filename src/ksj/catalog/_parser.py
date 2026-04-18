"""KSJ トップ index.html と各詳細ページの HTML パーサ。

docs/catalog.md のスクレイピング方針に従い、URL はテンプレート推測せず実
値を抽出する。形式 / CRS は HTML の記述から正規化し、ファイル名は補助の
ヒントに留める。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ksj.catalog._normalizers import (
    ScopeHints,
    classify_row_format,
    classify_scope,
    classify_url_format,
    detect_formats_in_text,
    normalize_crs,
)
from ksj.catalog.schema import Format


@dataclass(slots=True)
class IndexEntry:
    """トップページの 1 リンク。"""

    code: str
    name: str
    category: str
    subcategory: str | None
    detail_page: str  # 絶対 URL


@dataclass(slots=True)
class ParsedFile:
    """詳細ページから抽出した 1 ダウンロード行。"""

    url: str
    filename: str
    size_raw: str | None
    size_bytes: int | None
    year_raw: str | None
    crs_raw: str
    crs: int | None
    format: Format
    format_raw: str
    scope_hints: ScopeHints


@dataclass(slots=True)
class ParsedDetailPage:
    """詳細ページのパース結果。"""

    code: str
    name: str | None
    license_raw: str | None
    formats_in_page: list[Format]
    files: list[ParsedFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---- トップページ ----------------------------------------------------------

_INDEX_CODE_RE = re.compile(r"KsjTmplt-([A-Za-z0-9_-]+?)(?:-(\d{4}))?\.html$")


def parse_index_page(html: str, base_url: str) -> list[IndexEntry]:
    """index.html から全データセットの (code, name, category, detail_page) を抽出する。

    トップページは ``<ul class="collapsible">`` ごとに 5 つの大カテゴリを展開し、
    その中で ``<div class="card-panel">`` が小カテゴリ、``<a href="...KsjTmplt-*.html">``
    がデータセットリンクになっている。同一コードの複数年次版リンクがある場合は
    名称が短い最初のものを採用する (後工程で詳細ページをたどるため)。
    """
    soup = BeautifulSoup(html, "lxml")

    entries: dict[str, IndexEntry] = {}
    for anchor in soup.select('a[href*="KsjTmplt-"]'):
        href_attr = anchor.get("href", "")
        href = href_attr if isinstance(href_attr, str) else ""
        if not href:
            continue
        m = _INDEX_CODE_RE.search(href)
        if m is None:
            continue
        code = m.group(1)

        name = _clean_anchor_text(anchor)
        if not name:
            continue

        category, subcategory = _find_category(anchor)
        detail_url = urljoin(base_url, href)

        # 同一コードに対し、分類済みエントリがあれば featured (uncategorized) を捨てる
        existing = entries.get(code)
        if existing is not None and existing.category != "(uncategorized)":
            continue
        entries[code] = IndexEntry(
            code=code,
            name=name,
            category=category,
            subcategory=subcategory,
            detail_page=detail_url,
        )
    return list(entries.values())


def _clean_anchor_text(anchor: Tag) -> str:
    """アンカーテキストから Material icon (<i class="material-icons">) と箇条記号を除く。"""
    clone = BeautifulSoup(str(anchor), "lxml")
    for icon in clone.select("i.material-icons"):
        icon.decompose()
    text = clone.get_text(strip=True)
    # 「&emsp;」の全角空白・箇条記号を除去
    text = re.sub(r"[\u3000\s・]+", "", text)
    return text


def _find_category(anchor: Tag) -> tuple[str, str | None]:
    """リンクから遡って 大カテゴリ (collapsible-header) と 小カテゴリ (card-panel span) を取得する。"""
    category: str = "(uncategorized)"
    subcategory: str | None = None

    # 祖先の collapsible ul を特定して、その中だけで大/小カテゴリを探す。
    # find_previous で文書全体を遡ると、前のカテゴリの小カテゴリを誤って拾うため。
    owning_ul: Tag | None = None
    for ancestor in anchor.parents:
        if (
            isinstance(ancestor, Tag)
            and ancestor.name == "ul"
            and "collapsible" in (ancestor.get("class") or [])
        ):
            owning_ul = ancestor
            break

    if owning_ul is None:
        return category, subcategory

    # 大カテゴリ: 同じ collapsible 内の header テキスト
    header = owning_ul.find("div", class_="collapsible-header")
    if isinstance(header, Tag):
        header_clone = BeautifulSoup(str(header), "lxml")
        for icon in header_clone.select("i.material-icons"):
            icon.decompose()
        raw = header_clone.get_text(" ", strip=True)
        cleaned = re.sub(r"^\d+\.\s*", "", raw).strip()
        category = cleaned or category

    # 小カテゴリ: 同じ collapsible 内の card-panel 子孫 span のうち、
    # anchor より文書上手前にある最後のもの
    for panel in owning_ul.select("div.card-panel span[id^='collapsible-body__']"):
        if _is_before(panel, anchor):
            subcategory = panel.get_text(strip=True) or subcategory

    return category, subcategory


def _is_before(a: Tag, b: Tag) -> bool:
    """文書内で ``a`` が ``b`` より前に現れるか。"""
    return any(sibling is b for sibling in a.find_all_next())


# ---- 詳細ページ -----------------------------------------------------------

_DOWNLD_RE = re.compile(
    r"DownLd\(\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'",
)
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([KMG]?B)", re.IGNORECASE)
_SIZE_MULT: dict[str, int] = {
    "B": 1,
    "KB": 1024,
    "MB": 1024 * 1024,
    "GB": 1024 * 1024 * 1024,
}

# ダウンロード表のヘッダラベル → 正規化キー。部分一致 (最初にヒットしたものを採用)。
# データセット毎にヘッダ語彙や列順が揺れる (例: N13 は 形式 列を追加、N03 は 年/年度 表記)
# ため、固定 index でなくラベル語で列を同定する。
_COLUMN_KEYWORDS: list[tuple[str, str]] = [
    ("地域", "region"),
    ("形式", "format"),
    ("測地系", "crs"),
    ("年度", "year"),
    ("年月", "year"),
    ("年", "year"),
    ("ファイル容量", "size"),
    ("ファイル名", "filename"),
]


def _build_column_map(table: Tag) -> dict[str, int]:
    """ダウンロード表の thead から 列名 → 列 index を構築する。

    「地域/形式/測地系/年度/ファイル容量/ファイル名」の 6 語彙を部分一致で探し、
    先頭行の th を走査して index を割り当てる。見つからないキーは dict に入らない。
    """
    thead = table.find("thead")
    if not isinstance(thead, Tag):
        return {}
    tr = thead.find("tr")
    if not isinstance(tr, Tag):
        return {}
    result: dict[str, int] = {}
    for idx, th in enumerate(tr.find_all("th", recursive=False)):
        label = th.get_text(" ", strip=True) if isinstance(th, Tag) else ""
        # 並べ替え記号・矢印・空白除去
        label = re.sub(r"[▲▼\s]+", "", label)
        for keyword, key in _COLUMN_KEYWORDS:
            if key in result:
                continue
            if keyword in label:
                result[key] = idx
                break
    return result


def _cell(cells: list[Tag], col_map: dict[str, int], key: str) -> Tag | None:
    """列マップから指定キーの td を取得。該当列が無ければ None。"""
    idx = col_map.get(key)
    if idx is None or idx >= len(cells):
        return None
    return cells[idx]


def _cell_text(cells: list[Tag], col_map: dict[str, int], key: str) -> str:
    """列マップから指定キーの td テキストを取得。該当列が無ければ空文字。"""
    td = _cell(cells, col_map, key)
    return td.get_text(strip=True) if td is not None else ""


def parse_detail_page(html: str, page_url: str, code: str) -> ParsedDetailPage:
    """詳細ページから ParsedFile 一覧とメタデータを抽出する。"""
    soup = BeautifulSoup(html, "lxml")
    name = _extract_title(soup)
    license_raw = _extract_license(soup)
    formats_in_page = detect_formats_in_text(soup.get_text("\n"))

    result = ParsedDetailPage(
        code=code,
        name=name,
        license_raw=license_raw,
        formats_in_page=formats_in_page,
    )

    # ダウンロード表はページ内に複数存在することがある (年度別や都道府県別の表が分かれる
    # N03 等) ため、テーブルを外側ループにして thead → 行の順で処理する。これにより
    # 行ごとの find_parent 呼び出しを排除し、列マップも 1 テーブル 1 回で済む。
    tables_with_downloads = [t for t in soup.find_all("table") if t.find("a", onclick=_DOWNLD_RE)]
    if not tables_with_downloads:
        result.warnings.append("ダウンロードリンクが検出できない (フォームベース配布の可能性)")
        return result

    for table in tables_with_downloads:
        col_map = _build_column_map(table)
        if not col_map:
            # 全 131 配布表に thead が存在することは確認済み。無い場合は構造が想定外なので
            # 当該テーブルだけスキップして他テーブルの処理を続行する
            result.warnings.append(f"テーブルヘッダが解析できない ({table.get('class')})")
            continue
        for row in table.find_all("tr"):
            anchor = row.find("a", onclick=_DOWNLD_RE)
            if anchor is None:
                continue
            onclick_attr = anchor.get("onclick")
            onclick = onclick_attr if isinstance(onclick_attr, str) else ""
            m = _DOWNLD_RE.search(onclick)
            if m is None:
                continue
            size_raw, filename, rel_path = m.groups()
            url = urljoin(page_url, rel_path)

            cells: list[Tag] = [c for c in row.find_all("td") if isinstance(c, Tag)]

            region_td = _cell(cells, col_map, "region")
            region_text = region_td.get_text(strip=True) if region_td else ""
            region_id_attr = region_td.get("id") if region_td else None
            region_id = region_id_attr if isinstance(region_id_attr, str) else None

            crs_text = _cell_text(cells, col_map, "crs")
            format_cell_text = _cell_text(cells, col_map, "format")
            year_text = _cell_text(cells, col_map, "year") or None

            scope_hints = classify_scope(cell_text=region_text, dom_id=region_id, filename=filename)
            crs, crs_raw = normalize_crs(cell_text=crs_text, filename=filename)

            # 形式列が存在するデータセット (例: N13) では行単位の表記が正。
            # 無い場合は filename + ページ全体のフォーマット宣言から推定する。
            # format_raw は HTML 原文を保持する欄なので、行単位の原文が無いときは
            # ページ共通の形式一覧をコピーせず空にする (原文らしさを損なわないため)。
            if format_cell_text:
                fmt: Format = classify_row_format(
                    cell_text=format_cell_text, formats_in_page=formats_in_page
                )
                format_raw = format_cell_text
            else:
                fmt = classify_url_format(filename=filename, formats_in_page=formats_in_page)
                format_raw = ""

            result.files.append(
                ParsedFile(
                    url=url,
                    filename=filename,
                    size_raw=size_raw,
                    size_bytes=_parse_size(size_raw),
                    year_raw=year_text,
                    crs_raw=crs_raw,
                    crs=crs,
                    format=fmt,
                    format_raw=format_raw,
                    scope_hints=scope_hints,
                )
            )

    return result


def _extract_title(soup: BeautifulSoup) -> str | None:
    # `<title>` から「◯◯ - 国土数値情報ダウンロードサイト」の◯◯ を取得
    if soup.title is None:
        return None
    raw: str = soup.title.get_text(strip=True)
    cleaned = raw.split("|")[0].split("-")[0].strip()
    return cleaned or None


def _extract_license(soup: BeautifulSoup) -> str | None:
    """ページの「使用/利用許諾条件」見出しの隣セルを抽出する。

    ラベルは KSJ サイト内で「使用許諾条件」「利用許諾条件」「使用条件」等の
    表記揺れがある。P11 のように ``<th>`` の直後に空の ``<td>`` が挟まる破損 HTML が
    存在するため、同一行内の中身のある td を採用する (文書末尾までの find_next で
    巨大な走査にならないよう行スコープに限定)。
    """
    for th in soup.find_all("th"):
        if not isinstance(th, Tag):
            continue
        label = th.get_text(strip=True)
        if ("使用" in label or "利用" in label) and ("許諾" in label or "条件" in label):
            row = th.find_parent("tr")
            if not isinstance(row, Tag):
                continue
            for td in row.find_all("td"):
                text = str(td.get_text(" ", strip=True))
                if text:
                    return text[:200]
    return None


def _parse_size(size_raw: str | None) -> int | None:
    """「307MB」形式のサイズ文字列をバイト数に変換する。

    KSJ 側で「0MB」「0.0MB」と書かれているデータ (古年版のメッシュ配布に散見) は
    実サイズ不明のプレースホルダのため、0 は None 化して「未取得」扱いにする。
    """
    if not size_raw:
        return None
    m = _SIZE_RE.search(size_raw)
    if m is None:
        return None
    value, unit = m.groups()
    try:
        size = int(float(value) * _SIZE_MULT[unit.upper()])
    except ValueError:
        # KSJ 側の値が「48.7.2MB」のように破損している場合 (バージョン表記と混在) を救済
        return None
    return size if size > 0 else None


__all__ = [
    "IndexEntry",
    "ParsedDetailPage",
    "ParsedFile",
    "parse_detail_page",
    "parse_index_page",
]
