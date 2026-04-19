"""`ksj integrate` の純粋関数実装。

既存 ``integrator.integrate`` を薄く呼び、その既知例外を ``HandlerError`` に
正規化するだけ。結果は ``IntegrateResult`` (integrator/pipeline.py:50) を
そのまま返す。
"""

from __future__ import annotations

from pathlib import Path

from ksj.catalog import Catalog
from ksj.errors import ErrorKind, HandlerError
from ksj.handlers._catalog_loader import load_catalog_or_raise
from ksj.integrator import (
    DEFAULT_TARGET_CRS,
    DownloadRequiredError,
    NoSourcesError,
)
from ksj.integrator import (
    integrate as integrate_dataset,
)
from ksj.integrator.pipeline import IntegrateResult
from ksj.reader import NoMatchingFormatError


def integrate_data(
    code: str,
    year: str,
    *,
    data_dir: Path,
    target_crs: str = DEFAULT_TARGET_CRS,
    format_preference: list[str] | None = None,
    strict_year: bool = False,
    allow_partial: bool = False,
    output_path: Path | None = None,
    catalog: Catalog | None = None,
) -> IntegrateResult:
    cat = catalog if catalog is not None else load_catalog_or_raise()
    try:
        return integrate_dataset(
            cat,
            code,
            year,
            data_dir=data_dir,
            target_crs=target_crs,
            format_preference=format_preference,
            strict_year=strict_year,
            allow_partial=allow_partial,
            output_path=output_path,
        )
    except KeyError as exc:
        raise HandlerError(ErrorKind.DATASET_NOT_FOUND, str(exc)) from exc
    except (NoSourcesError, DownloadRequiredError, NoMatchingFormatError) as exc:
        raise HandlerError(ErrorKind.INTEGRATE_FAILED, str(exc)) from exc
