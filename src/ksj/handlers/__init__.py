"""純粋関数レイヤ: stdout に書かず結果オブジェクトを返す。

CLI (`ksj.cli`) と将来の自動化インタフェース (MCP / HTTP 等) から共通に呼べるよう、
rich / typer への依存を持たない。失敗時は ``ksj.errors.HandlerError`` を raise する。
"""

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
