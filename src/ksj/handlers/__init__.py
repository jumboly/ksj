"""実行ロジック層: stdout に書かず結果オブジェクトを返す。

rich / typer への依存を持たず、CLI と将来の自動化インタフェース (MCP / HTTP 等)
から共通に呼べる形にしている。「純粋関数」ではない: download / ingest-local /
refresh / integrate はファイルシステム (manifest / raw ZIP / GPKG) を書き換え、
refresh / diff はネットワーク I/O を行う。副作用のない関数は
list / info / catalog_summary / html_list / catalog_diff (読み取り後のネット I/O あり)。
失敗時は ``ksj.errors.HandlerError`` を raise する。

**遅延 import**: ``ksj.cli`` は root callback で ``from ksj import handlers`` を
評価するため、その時点で各 submodule を eager import すると pipeline.py 経由で
geopandas / pyproj / pyogrio が ``ksj list`` 等の軽量コマンドでも読み込まれる。
代わりに ``__getattr__`` ベースの lazy attribute lookup を使い、実際に参照された
attribute の submodule だけロードする。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ksj.handlers.catalog import (
        CatalogDiffResult,
        CatalogSummary,
        RefreshReport,
        catalog_diff_data,
        catalog_refresh_data,
        catalog_summary_data,
    )
    from ksj.handlers.download import DownloadReport, download_data
    from ksj.handlers.html import (
        HtmlFetchReport,
        HtmlListResult,
        HtmlListRow,
        html_fetch_data,
        html_list_data,
    )
    from ksj.handlers.info import DatasetInfo, FileRow, VersionInfo, dataset_info_data
    from ksj.handlers.ingest_local import IngestLocalReport, ingest_local_data
    from ksj.handlers.integrate import integrate_data
    from ksj.handlers.list_datasets import ListResult, ListRow, list_datasets_data

# attr 名 → submodule 名 (ksj.handlers.<module>)
_ATTR_MAP: dict[str, str] = {
    "CatalogDiffResult": "catalog",
    "CatalogSummary": "catalog",
    "RefreshReport": "catalog",
    "catalog_diff_data": "catalog",
    "catalog_refresh_data": "catalog",
    "catalog_summary_data": "catalog",
    "DownloadReport": "download",
    "download_data": "download",
    "HtmlFetchReport": "html",
    "HtmlListResult": "html",
    "HtmlListRow": "html",
    "html_fetch_data": "html",
    "html_list_data": "html",
    "DatasetInfo": "info",
    "FileRow": "info",
    "VersionInfo": "info",
    "dataset_info_data": "info",
    "IngestLocalReport": "ingest_local",
    "ingest_local_data": "ingest_local",
    "integrate_data": "integrate",
    "ListResult": "list_datasets",
    "ListRow": "list_datasets",
    "list_datasets_data": "list_datasets",
}


def __getattr__(name: str) -> Any:
    sub = _ATTR_MAP.get(name)
    if sub is None:
        raise AttributeError(f"module 'ksj.handlers' has no attribute {name!r}")
    module = importlib.import_module(f"ksj.handlers.{sub}")
    attr = getattr(module, name)
    # 次回以降は __getattr__ を経由せず直接解決させるため module globals にキャッシュ
    globals()[name] = attr
    return attr


# mypy strict は `__all__` が静的リテラルでないと implicit reexport を許さないため、
# _ATTR_MAP と二重管理になるが明示的に列挙する。
__all__ = [
    "CatalogDiffResult",
    "CatalogSummary",
    "DatasetInfo",
    "DownloadReport",
    "FileRow",
    "HtmlFetchReport",
    "HtmlListResult",
    "HtmlListRow",
    "IngestLocalReport",
    "ListResult",
    "ListRow",
    "RefreshReport",
    "VersionInfo",
    "catalog_diff_data",
    "catalog_refresh_data",
    "catalog_summary_data",
    "dataset_info_data",
    "download_data",
    "html_fetch_data",
    "html_list_data",
    "ingest_local_data",
    "integrate_data",
    "list_datasets_data",
]
