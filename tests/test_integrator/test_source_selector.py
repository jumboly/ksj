from __future__ import annotations

import pytest

from ksj.catalog.schema import Dataset, FileEntry, Version
from ksj.integrator.source_selector import (
    NoNationalSourceError,
    select_national,
)


def _dataset(*files: FileEntry, year: str = "2025") -> Dataset:
    return Dataset(
        name="サンプル",
        versions={year: Version(files=list(files))},
    )


def _file(scope: str = "national", **overrides: object) -> FileEntry:
    base: dict[str, object] = {
        "scope": scope,
        "url": f"https://example.com/{scope}.zip",
        "format": "shp",
    }
    if scope == "prefecture":
        base["pref_code"] = 1
    base.update(overrides)
    return FileEntry.model_validate(base)


def test_select_national_picks_national_entry() -> None:
    dataset = _dataset(
        _file(scope="prefecture"),
        _file(scope="national", url="https://example.com/national.zip"),
    )
    selected = select_national(dataset, "2025")
    assert selected.file_entry.scope == "national"
    assert selected.year == "2025"


def test_select_national_picks_first_when_multiple() -> None:
    dataset = _dataset(
        _file(url="https://example.com/a.zip"),
        _file(url="https://example.com/b.zip"),
    )
    selected = select_national(dataset, "2025")
    assert selected.file_entry.url == "https://example.com/a.zip"


def test_select_national_raises_when_only_other_scopes() -> None:
    dataset = _dataset(_file(scope="prefecture"))
    with pytest.raises(NoNationalSourceError):
        select_national(dataset, "2025")


def test_select_national_raises_when_year_missing() -> None:
    dataset = _dataset(_file(), year="2024")
    with pytest.raises(NoNationalSourceError):
        select_national(dataset, "2025")
