"""KSJ から取得した HTML を ``<base>/<host>/<path>`` の配置でローカルキャッシュする。

反復的な catalog refresh でネットワーク負荷を避け、オフラインでもパーサ改修を
回すための透過キャッシュ。別ホスト (www.gsi.go.jp 等) 対応は host 階層で自動処理。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_HTML_CACHE_DIR = Path("data/html_cache")


class CachePolicy(Enum):
    """キャッシュの読み/書きポリシー。"""

    OFF = "off"  # キャッシュを全く使用しない (読まない・書かない)
    READ_ONLY = "read_only"  # キャッシュから読むのみ (ネットワーク取得は書かない)
    READ_WRITE = "read_write"  # 読み取り優先、ネットワーク取得分は書き込む


@dataclass(slots=True)
class CachedEntry:
    """キャッシュ内の 1 HTML エントリ。"""

    url: str
    path: Path
    size_bytes: int
    modified_at: datetime


@dataclass(slots=True)
class CacheSummary:
    """キャッシュ全体の集計値。"""

    file_count: int
    total_bytes: int

    @property
    def total_mb(self) -> float:
        return self.total_bytes / (1024 * 1024)


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
    """キャッシュ配下の *.html を順次列挙する。

    ``base_dir`` が存在しない場合は rglob が 0 件を返す (FileNotFoundError は catch)。
    """
    try:
        paths = sorted(base_dir.rglob("*.html"))
    except FileNotFoundError:
        return
    for path in paths:
        rel = path.relative_to(base_dir)
        # キャッシュ構造が <base>/<host>/<path> なので最初の要素がホストになる
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


def summary(base_dir: Path = DEFAULT_HTML_CACHE_DIR) -> CacheSummary:
    """キャッシュ全体のファイル数と合計バイト数を 1 回の走査で取得する。"""
    count = 0
    total = 0
    for entry in iter_cached(base_dir):
        count += 1
        total += entry.size_bytes
    return CacheSummary(file_count=count, total_bytes=total)


__all__ = [
    "DEFAULT_HTML_CACHE_DIR",
    "CachePolicy",
    "CacheSummary",
    "CachedEntry",
    "cache_path",
    "iter_cached",
    "load",
    "save",
    "summary",
]
