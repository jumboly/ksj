"""純粋関数レイヤ: stdout に書かず結果オブジェクトを返す。

CLI (`ksj.cli`) と将来の自動化インタフェース (MCP / HTTP 等) から共通に呼べるよう、
rich / typer への依存を持たない。失敗時は ``ksj.errors.HandlerError`` を raise する。
"""

from ksj.handlers.catalog import CatalogDiffResult, catalog_diff_data
from ksj.handlers.html import HtmlListResult, HtmlListRow, html_list_data
from ksj.handlers.info import DatasetInfo, FileRow, VersionInfo, dataset_info_data
from ksj.handlers.list_datasets import ListResult, ListRow, list_datasets_data

__all__ = [
    "CatalogDiffResult",
    "DatasetInfo",
    "FileRow",
    "HtmlListResult",
    "HtmlListRow",
    "ListResult",
    "ListRow",
    "VersionInfo",
    "catalog_diff_data",
    "dataset_info_data",
    "html_list_data",
    "list_datasets_data",
]
