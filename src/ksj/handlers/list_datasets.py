"""`ksj list` の純粋関数実装。"""

from __future__ import annotations

from dataclasses import dataclass

from ksj.catalog import Catalog, Dataset
from ksj.handlers._catalog_loader import load_catalog_or_raise


@dataclass(slots=True)
class ListRow:
    """1 データセット分の表示行。"""

    code: str
    name: str
    category: str | None
    versions: int
    scopes: list[str]


@dataclass(slots=True)
class ListResult:
    """list コマンドの結果。

    ``total`` は ``--category`` / ``--scope`` フィルタ前のカタログ全体件数、
    ``rows`` はフィルタ後の該当行。UI では「132 件収録 中 N 件該当」のような
    分子分母表示に使う想定。
    """

    total: int
    rows: list[ListRow]


def _collect_scopes(dataset: Dataset) -> list[str]:
    return list(
        dict.fromkeys(file.scope for version in dataset.versions.values() for file in version.files)
    )


def _category_matches(dataset: Dataset, query: str | None) -> bool:
    if query is None:
        return True
    return dataset.category is not None and query in dataset.category


def list_datasets_data(
    *,
    category: str | None = None,
    scope: str | None = None,
    catalog: Catalog | None = None,
) -> ListResult:
    """カテゴリ・scope でフィルタした一覧を返す。catalog は DI 可能。"""
    cat = catalog if catalog is not None else load_catalog_or_raise()

    rows: list[ListRow] = []
    for code, dataset in cat.datasets.items():
        if not _category_matches(dataset, category):
            continue
        scopes = _collect_scopes(dataset)
        if scope is not None and scope not in scopes:
            continue
        rows.append(
            ListRow(
                code=code,
                name=dataset.name,
                category=dataset.category,
                versions=len(dataset.versions),
                scopes=scopes,
            )
        )
    return ListResult(total=len(cat.datasets), rows=rows)
