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

    rows = [a for a in soup.select("a[onclick]") if "DownLd" in (a.get("onclick") or "")]
    if not rows:
        result.warnings.append("ダウンロードリンクが検出できない (フォームベース配布の可能性)")
        return result

    for anchor in rows:
        onclick_attr = anchor.get("onclick")
        onclick = onclick_attr if isinstance(onclick_attr, str) else ""
        m = _DOWNLD_RE.search(onclick)
        if m is None:
            continue
        size_raw, filename, rel_path = m.groups()
        url = urljoin(page_url, rel_path)

        row = anchor.find_parent("tr")
        cells: list[Tag] = list(row.find_all("td")) if row else []

        region_td = cells[0] if cells else None
        region_text = region_td.get_text(strip=True) if region_td else ""
        region_id_attr = region_td.get("id") if region_td else None
        region_id = region_id_attr if isinstance(region_id_attr, str) else None

        crs_text = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        year_text = cells[2].get_text(strip=True) if len(cells) > 2 else None

        scope_hints = classify_scope(cell_text=region_text, dom_id=region_id, filename=filename)
        crs, crs_raw = normalize_crs(cell_text=crs_text, filename=filename)
        fmt = classify_url_format(filename=filename, formats_in_page=formats_in_page)

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
                format_raw=", ".join(formats_in_page) if formats_in_page else "",
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
    # ページ内の「利用許諾条件」or 類似ラベルの隣セルを抽出
    for th in soup.find_all("th"):
        label = th.get_text(strip=True)
        if "利用" in label and "条件" in label:
            td = th.find_next("td")
            if td is not None:
                # 長大ライセンス文を切り詰め。bs4 の get_text は Any を返すため明示的に str 化
                return str(td.get_text(" ", strip=True))[:200]
    return None


def _parse_size(size_raw: str | None) -> int | None:
    if not size_raw:
        return None
    m = _SIZE_RE.search(size_raw)
    if m is None:
        return None
    value, unit = m.groups()
    try:
        return int(float(value) * _SIZE_MULT[unit.upper()])
    except ValueError:
        # KSJ 側の値が「48.7.2MB」のように破損している場合 (バージョン表記と混在) を救済
        return None


__all__ = [
    "IndexEntry",
    "ParsedDetailPage",
    "ParsedFile",
    "parse_detail_page",
    "parse_index_page",
]
