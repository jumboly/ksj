"""`ksj html list` の純粋関数実装。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ksj import html_cache


@dataclass(slots=True)
class HtmlListRow:
    relative_path: str
    size_bytes: int
    modified_at: datetime


@dataclass(slots=True)
class HtmlListResult:
    cache_dir: Path
    entries: list[HtmlListRow]
    total_bytes: int

    @property
    def is_empty(self) -> bool:
        return not self.entries


def html_list_data(
    *,
    cache_dir: Path = html_cache.DEFAULT_HTML_CACHE_DIR,
) -> HtmlListResult:
    rows: list[HtmlListRow] = []
    total_bytes = 0
    for entry in html_cache.iter_cached(cache_dir):
        rows.append(
            HtmlListRow(
                relative_path=str(entry.path.relative_to(cache_dir)),
                size_bytes=entry.size_bytes,
                modified_at=entry.modified_at,
            )
        )
        total_bytes += entry.size_bytes
    return HtmlListResult(cache_dir=cache_dir, entries=rows, total_bytes=total_bytes)
