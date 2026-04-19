"""`ksj catalog diff` の純粋関数実装。

書き込み系 (``ksj catalog refresh`` 等) は別途 handler 化する。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ksj.catalog import Catalog
from ksj.catalog.refresh import diff_catalogs, refresh_catalog
from ksj.handlers._catalog_loader import load_catalog_or_raise


@dataclass(slots=True)
class CatalogDiffResult:
    """diff 結果 + 空判定ヘルパ。"""

    added: list[str]
    removed: list[str]
    changed: list[str]

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


def catalog_diff_data(
    *,
    current: Catalog | None = None,
) -> CatalogDiffResult:
    """既存カタログと最新スクレイプ結果の差分を計算する。

    ネットワークに出るので blocking 時間が長い。rich 表示側では spinner で囲む
    が、handler 自身は進捗表示に関与しない。
    """
    base = current if current is not None else load_catalog_or_raise()
    fresh, _ = asyncio.run(refresh_catalog())
    raw = diff_catalogs(base, fresh)
    return CatalogDiffResult(added=raw.added, removed=raw.removed, changed=raw.changed)
