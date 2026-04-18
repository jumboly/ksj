"""KSJ サイトから取得した HTML をローカルキャッシュする。

目的:
1. 反復的なカタログ refresh でサイトに負荷をかけない
2. オフライン環境でもパーサ改修を回せる
3. 取得タイムスタンプ/差分を保持してデバッグしやすく

URL → キャッシュファイルパスは host + path をディレクトリ階層にマップするので、
別ホスト (www.gsi.go.jp 等) 対応も自動。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_HTML_CACHE_DIR = Path("data/html_cache")


@dataclass(slots=True)
class CachedEntry:
    """キャッシュ内の 1 HTML エントリ。"""

    url: str
    path: Path
    size_bytes: int
    modified_at: datetime


def cache_path(url: str, base_dir: Path = DEFAULT_HTML_CACHE_DIR) -> Path:
    """URL をキャッシュファイルの絶対パスに変換する。

    例: ``https://nlftp.mlit.go.jp/ksj/index.html``
      → ``<base>/nlftp.mlit.go.jp/ksj/index.html``

    path が "/" で終わる場合は ``index.html`` を補完する。
    """
    parsed = urlparse(url)
    host = parsed.hostname or "unknown"
    raw_path = parsed.path.lstrip("/")
    if not raw_path or raw_path.endswith("/"):
        raw_path = raw_path + "index.html"
    return base_dir / host / raw_path


def load(url: str, base_dir: Path = DEFAULT_HTML_CACHE_DIR) -> str | None:
    """キャッシュから HTML を読み出す。存在しなければ ``None``。"""
    target = cache_path(url, base_dir)
    try:
        return target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def save(url: str, html: str, base_dir: Path = DEFAULT_HTML_CACHE_DIR) -> Path:
    """HTML をキャッシュに書き込む。"""
    target = cache_path(url, base_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    return target


def iter_cached(base_dir: Path = DEFAULT_HTML_CACHE_DIR) -> Iterator[CachedEntry]:
    """キャッシュ配下の *.html を順次列挙する。"""
    if not base_dir.exists():
        return
    for path in sorted(base_dir.rglob("*.html")):
        rel = path.relative_to(base_dir)
        # rel の先頭がホスト名。残りをパスとして扱う。
        parts = rel.parts
        if len(parts) < 2:
            continue
        host = parts[0]
        url_path = "/" + "/".join(parts[1:])
        url = f"https://{host}{url_path}"
        stat = path.stat()
        yield CachedEntry(
            url=url,
            path=path,
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        )


def total_size(base_dir: Path = DEFAULT_HTML_CACHE_DIR) -> int:
    """キャッシュ全体のバイト合計。"""
    return sum(entry.size_bytes for entry in iter_cached(base_dir))


__all__ = [
    "DEFAULT_HTML_CACHE_DIR",
    "CachedEntry",
    "cache_path",
    "iter_cached",
    "load",
    "save",
    "total_size",
]
