"""読込→CRS変換→スキーマ統一→結合→書出 の統合パイプライン。

Phase 4 では national scope のみ対応。Phase 5 で分割結合 / scope union / latest-fill
を追加する。
"""

from ksj.integrator.pipeline import (
    DEFAULT_TARGET_CRS,
    DownloadRequiredError,
    IntegrateResult,
    integrate,
)
from ksj.integrator.source_selector import (
    NoNationalSourceError,
    SelectedSource,
    select_national,
)

__all__ = [
    "DEFAULT_TARGET_CRS",
    "DownloadRequiredError",
    "IntegrateResult",
    "NoNationalSourceError",
    "SelectedSource",
    "integrate",
    "select_national",
]
