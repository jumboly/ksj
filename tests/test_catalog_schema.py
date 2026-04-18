from __future__ import annotations

import pytest
from pydantic import ValidationError

from ksj.catalog.schema import Catalog, Dataset, FileEntry, Version


def _base_file(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "scope": "national",
        "url": "https://example.com/sample.zip",
        "format": "shp",
    }
    base.update(overrides)
    return base


def test_file_entry_national_minimum() -> None:
    f = FileEntry.model_validate(_base_file())
    assert f.scope == "national"
    assert f.pref_code is None


def test_file_entry_prefecture_requires_pref_code() -> None:
    with pytest.raises(ValidationError) as excinfo:
        FileEntry.model_validate(_base_file(scope="prefecture"))
    assert "pref_code" in str(excinfo.value)


def test_file_entry_regional_bureau_requires_bureau_code() -> None:
    with pytest.raises(ValidationError):
        FileEntry.model_validate(_base_file(scope="regional_bureau"))


def test_file_entry_mesh_requires_mesh_code() -> None:
    for scope in ("mesh1", "mesh2", "mesh3", "mesh4", "mesh5", "mesh6"):
        with pytest.raises(ValidationError):
            FileEntry.model_validate(_base_file(scope=scope))


def test_file_entry_unknown_scope_rejected() -> None:
    with pytest.raises(ValidationError):
        FileEntry.model_validate(_base_file(scope="intergalactic"))


def test_version_requires_at_least_one_file() -> None:
    with pytest.raises(ValidationError):
        Version.model_validate({"files": []})


def test_dataset_round_trip() -> None:
    dataset = Dataset.model_validate(
        {
            "name": "サンプル",
            "coverage": "full",
            "versions": {
                "2025": {"files": [_base_file()]},
            },
        }
    )
    assert "2025" in dataset.versions
    assert dataset.versions["2025"].files[0].format == "shp"


def test_catalog_rejects_unknown_top_level_key() -> None:
    with pytest.raises(ValidationError):
        Catalog.model_validate({"datasets": {}, "unknown_key": 1})
