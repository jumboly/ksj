"""handler 共通: カタログ読込の薄いラッパ。

``load_catalog`` の ``CatalogNotFoundError`` を ``HandlerError`` に正規化し、
呼び出し元 (handler 群) の分岐を単純化する。
"""

from __future__ import annotations

from ksj.catalog import Catalog, load_catalog
from ksj.catalog.loader import CatalogNotFoundError
from ksj.errors import ErrorKind, HandlerError


def load_catalog_or_raise() -> Catalog:
    try:
        return load_catalog()
    except CatalogNotFoundError as exc:
        raise HandlerError(
            ErrorKind.CATALOG_NOT_FOUND,
            f"catalog/datasets.yaml が見つかりません: {exc}",
        ) from exc
