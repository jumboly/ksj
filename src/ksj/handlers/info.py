"""`ksj info <code>` の純粋関数実装。"""

from __future__ import annotations

from dataclasses import dataclass

from ksj.catalog import Catalog
from ksj.errors import ErrorKind, HandlerError
from ksj.handlers._catalog_loader import load_catalog_or_raise


@dataclass(slots=True)
class FileRow:
    """info 表示用に FileEntry から必要列だけ抽出したもの。"""

    scope: str
    scope_identifier: str
    crs: int | None
    format: str
    url: str


@dataclass(slots=True)
class VersionInfo:
    year: str
    files: list[FileRow]


@dataclass(slots=True)
class DatasetInfo:
    code: str
    name: str
    category: str | None
    detail_page: str | None
    license_raw: str | None
    geometry_types: list[str]
    available_formats: list[str]
    description: str | None
    use_cases: list[str]
    notes: str | None
    versions: list[VersionInfo]


def dataset_info_data(
    code: str,
    *,
    catalog: Catalog | None = None,
) -> DatasetInfo:
    cat = catalog if catalog is not None else load_catalog_or_raise()
    dataset = cat.datasets.get(code)
    if dataset is None:
        raise HandlerError(
            ErrorKind.DATASET_NOT_FOUND,
            f"データセット '{code}' はカタログに存在しません",
        )

    versions: list[VersionInfo] = []
    for year, version_entry in sorted(dataset.versions.items()):
        files = [
            FileRow(
                scope=str(f.scope),
                scope_identifier=f.scope_identifier,
                crs=f.crs,
                format=str(f.format),
                url=f.url,
            )
            for f in version_entry.files
        ]
        versions.append(VersionInfo(year=year, files=files))

    return DatasetInfo(
        code=code,
        name=dataset.name,
        category=dataset.category,
        detail_page=dataset.detail_page,
        license_raw=dataset.license_raw,
        geometry_types=list(dataset.geometry_types),
        available_formats=list(dataset.available_formats),
        description=dataset.description,
        use_cases=list(dataset.use_cases),
        notes=dataset.notes,
        versions=versions,
    )
