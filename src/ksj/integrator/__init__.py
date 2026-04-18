"""読込→CRS変換→スキーマ統一→結合→書出 の統合パイプライン。"""

from ksj.integrator.pipeline import (
    DEFAULT_TARGET_CRS,
    DownloadRequiredError,
    IntegrateResult,
    integrate,
)
from ksj.integrator.source_selector import (
    BucketCoverage,
    NoSourcesError,
    SelectedSource,
    SelectionPlan,
    select_sources,
)

__all__ = [
    "DEFAULT_TARGET_CRS",
    "BucketCoverage",
    "DownloadRequiredError",
    "IntegrateResult",
    "NoSourcesError",
    "SelectedSource",
    "SelectionPlan",
    "integrate",
    "select_sources",
]
