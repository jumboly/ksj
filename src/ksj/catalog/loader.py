"""カタログ YAML の読込とバリデーション。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ksj.catalog.schema import Catalog

# プロジェクトルート直下の catalog/datasets.yaml を規定の場所とする
DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[3] / "catalog" / "datasets.yaml"


class CatalogNotFoundError(FileNotFoundError):
    """カタログファイルが見つからない。"""


def load_catalog(path: Path | None = None) -> Catalog:
    """YAML を読込んで ``Catalog`` として返す。

    path 未指定時はプロジェクト同梱の ``catalog/datasets.yaml`` を使う。
    """

    target = path if path is not None else DEFAULT_CATALOG_PATH
    try:
        with target.open("r", encoding="utf-8") as f:
            raw: Any = yaml.safe_load(f)
    except FileNotFoundError as exc:
        raise CatalogNotFoundError(f"カタログファイルが見つかりません: {target}") from exc

    if raw is None:
        raw = {}
    return Catalog.model_validate(raw)
