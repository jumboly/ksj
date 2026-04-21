from __future__ import annotations

from pathlib import Path

import pytest

from ksj.catalog.loader import load_catalog
from ksj.catalog.schema import Dataset, FileEntry, Version
from ksj.downloader.selector import pick_targets

FIXTURE = Path(__file__).parent.parent / "fixtures" / "catalog" / "phase3_fixture.yaml"


def _mixed_dataset() -> Dataset:
    """national 1 件 + prefecture 2 件の混在 dataset (scope フィルタ動作検証用)。"""
    return Dataset(
        name="混在サンプル",
        versions={
            "2024": Version(
                files=[
                    FileEntry.model_validate(
                        {
                            "scope": "national",
                            "url": "https://example.com/X-2024-all.zip",
                            "format": "shp",
                            "crs": 6668,
                        }
                    ),
                    FileEntry.model_validate(
                        {
                            "scope": "prefecture",
                            "url": "https://example.com/X-2024-01.zip",
                            "format": "shp",
                            "crs": 6668,
                            "pref_code": 1,
                        }
                    ),
                    FileEntry.model_validate(
                        {
                            "scope": "prefecture",
                            "url": "https://example.com/X-2024-13.zip",
                            "format": "shp",
                            "crs": 6668,
                            "pref_code": 13,
                        }
                    ),
                ]
            )
        },
    )


def test_no_preference_returns_all() -> None:
    catalog = load_catalog(FIXTURE)
    entries = pick_targets(catalog.datasets["N03"], "2025")
    assert len(entries) == 2
    formats = {e.format for e in entries}
    assert formats == {"shp", "geojson"}


def test_format_preference_dedups_by_scope_identifier() -> None:
    catalog = load_catalog(FIXTURE)
    entries = pick_targets(catalog.datasets["N03"], "2025", format_preference=["shp"])
    # national は scope_identifier が空のため 1 グループに畳まれる → shp を 1 件のみ残す
    assert len(entries) == 1
    assert entries[0].format == "shp"


def test_format_preference_keeps_distinct_identifiers() -> None:
    catalog = load_catalog(FIXTURE)
    entries = pick_targets(catalog.datasets["A03"], "2003", format_preference=["shp"])
    # urban_area は識別子が 3 つで重複しないため全件残る
    assert {e.urban_area for e in entries} == {"関東圏", "中部圏", "近畿圏"}


def test_crs_filter() -> None:
    catalog = load_catalog(FIXTURE)
    entries = pick_targets(catalog.datasets["A03"], "2003", crs_filter=6668)
    # A03 fixture は全件 EPSG:4301 なので 6668 フィルタでは 0 件
    assert entries == []


def test_unknown_year_returns_empty() -> None:
    catalog = load_catalog(FIXTURE)
    assert pick_targets(catalog.datasets["N03"], "9999") == []


def test_format_preference_falls_back_to_first_candidate() -> None:
    """preference に無い形式しか無ければ、そのグループの先頭候補を残し脱落させない。"""
    catalog = load_catalog(FIXTURE)
    # gml を要求しても N03 fixture には無いので、shp/geojson のうち最初に現れる shp が残る
    entries = pick_targets(catalog.datasets["N03"], "2025", format_preference=["gml_jpgis2014"])
    assert len(entries) == 1
    assert entries[0].format == "shp"


def test_prefer_national_selects_only_national_when_present() -> None:
    entries = pick_targets(_mixed_dataset(), "2024", prefer_national=True)
    assert len(entries) == 1
    assert entries[0].scope == "national"


def test_prefer_national_falls_back_to_all_when_absent() -> None:
    """national が無いデータセットでは全 scope を残す (integrate の national 優先戦略と同じ)。"""
    catalog = load_catalog(FIXTURE)
    entries = pick_targets(catalog.datasets["A03"], "2003", prefer_national=True)
    assert len(entries) == 3
    assert {e.urban_area for e in entries} == {"関東圏", "中部圏", "近畿圏"}


def test_scope_filter_single_scope() -> None:
    entries = pick_targets(_mixed_dataset(), "2024", scope_filter=["prefecture"])
    assert len(entries) == 2
    assert all(e.scope == "prefecture" for e in entries)


def test_scope_filter_multiple_scopes_union() -> None:
    entries = pick_targets(_mixed_dataset(), "2024", scope_filter=["national", "prefecture"])
    assert len(entries) == 3


def test_scope_filter_no_match_returns_empty() -> None:
    entries = pick_targets(_mixed_dataset(), "2024", scope_filter=["mesh1"])
    assert entries == []


def test_scope_filter_and_prefer_national_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="同時指定できません"):
        pick_targets(_mixed_dataset(), "2024", scope_filter=["prefecture"], prefer_national=True)


def test_unknown_scope_in_filter_silently_drops() -> None:
    """タイポ等で存在しない scope を渡した場合は単に 0 件になる (Literal 検証はしない)。"""
    entries = pick_targets(_mixed_dataset(), "2024", scope_filter=["NATIONAL"])  # 大小違い
    assert entries == []
