from __future__ import annotations

from pathlib import Path

from ksj.catalog.loader import load_catalog
from ksj.downloader.selector import pick_targets

FIXTURE = Path(__file__).parent.parent / "fixtures" / "catalog" / "phase3_fixture.yaml"


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
    # urban_area は識別子が 3 つ (SYUTO/CHUBU/KINKI) で重複しないため全件残る
    assert {e.urban_area_code for e in entries} == {"SYUTO", "CHUBU", "KINKI"}


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
