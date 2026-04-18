from __future__ import annotations

import pytest

from ksj.catalog.schema import Dataset, FileEntry, Version
from ksj.integrator.source_selector import NoSourcesError, select_sources


def _dataset(*files: FileEntry, year: str = "2025") -> Dataset:
    return Dataset(
        name="サンプル",
        versions={year: Version(files=list(files))},
    )


def _dataset_multi(years: dict[str, list[FileEntry]]) -> Dataset:
    return Dataset(
        name="サンプル",
        versions={y: Version(files=list(files)) for y, files in years.items()},
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


def test_select_sources_returns_national_plan() -> None:
    dataset = _dataset(_file(scope="national"))
    plan = select_sources(dataset, "2025")
    assert plan.strategy == "national"
    assert plan.national_year == "2025"
    assert len(plan.sources) == 1
    assert plan.sources[0].file_entry.scope == "national"
    assert plan.sources[0].year == "2025"
    assert plan.coverage == []


def test_select_sources_prefers_national_over_prefecture_in_same_year() -> None:
    dataset = _dataset(
        _file(scope="prefecture"),
        _file(scope="national", url="https://example.com/national.zip"),
    )
    plan = select_sources(dataset, "2025")
    assert plan.strategy == "national"
    assert plan.sources[0].file_entry.scope == "national"


def test_select_sources_prefers_latest_national_in_past_years() -> None:
    dataset = _dataset_multi(
        {
            "2020": [_file(scope="national", url="https://example.com/2020.zip")],
            "2023": [_file(scope="national", url="https://example.com/2023.zip")],
            "2025": [_file(scope="prefecture")],
        }
    )
    # 2025 は prefecture のみだが、2023 以前の national が見つかるので strategy=national
    plan = select_sources(dataset, "2025")
    assert plan.strategy == "national"
    assert plan.national_year == "2023"
    assert plan.sources[0].file_entry.url == "https://example.com/2023.zip"


def test_select_sources_raises_when_year_missing() -> None:
    dataset = _dataset(_file(), year="2024")
    with pytest.raises(NoSourcesError):
        select_sources(dataset, "2099")


def test_select_sources_latest_fill_picks_all_prefectures() -> None:
    # 2018 年は 46 県、2015 年のみ沖縄 (47) が存在するケース
    files_2018 = [_file(scope="prefecture", pref_code=i) for i in range(1, 47)]
    files_2015 = [_file(scope="prefecture", pref_code=47, url="https://example.com/47-2015.zip")]
    dataset = _dataset_multi({"2018": files_2018, "2015": files_2015})

    plan = select_sources(dataset, "2018")
    assert plan.strategy == "latest-fill"
    assert len(plan.sources) == 47

    pref_coverage = next(c for c in plan.coverage if c.scope == "prefecture")
    assert pref_coverage.covered == 47
    assert pref_coverage.expected == 47
    assert pref_coverage.year_distribution["2018"] == 46
    assert pref_coverage.year_distribution["2015"] == 1
    assert pref_coverage.missing_identifiers == []

    assert any("過去年度から補填" in note for note in plan.notes)


def test_select_sources_strict_year_drops_past_years() -> None:
    files_2018 = [_file(scope="prefecture", pref_code=i) for i in range(1, 47)]
    files_2015 = [_file(scope="prefecture", pref_code=47, url="https://example.com/47-2015.zip")]
    dataset = _dataset_multi({"2018": files_2018, "2015": files_2015})

    plan = select_sources(dataset, "2018", strict_year=True)
    assert plan.strategy == "strict-year"
    assert len(plan.sources) == 46  # 沖縄は落ちる

    pref_coverage = next(c for c in plan.coverage if c.scope == "prefecture")
    assert pref_coverage.covered == 46
    assert pref_coverage.expected == 47
    assert pref_coverage.missing_identifiers == ["47"]


def test_select_sources_raises_when_no_eligible_candidates() -> None:
    # year より新しい年度しか無ければ strict-year でも latest-fill でも 0 件
    dataset = _dataset_multi({"2025": [_file(scope="prefecture", pref_code=1)]})
    with pytest.raises(NoSourcesError):
        select_sources(dataset, "2024")


def test_select_sources_mixes_scopes_when_no_national() -> None:
    files = [
        _file(scope="prefecture", pref_code=1),
        _file(scope="region", region_name="北海道地方", url="https://example.com/hokkaido.zip"),
    ]
    dataset = _dataset(*files)
    plan = select_sources(dataset, "2025")
    assert plan.strategy == "latest-fill"
    scopes = {s.file_entry.scope for s in plan.sources}
    assert scopes == {"prefecture", "region"}


def test_bucket_coverage_to_payload_is_defensive_copy() -> None:
    from ksj.integrator.source_selector import BucketCoverage

    bucket = BucketCoverage(
        scope="prefecture",
        covered=2,
        expected=47,
        year_distribution={"2018": 2},
        missing_identifiers=["3", "4"],
    )
    payload = bucket.to_payload()
    payload["year_distribution"]["2018"] = 999
    payload["missing_identifiers"].append("5")
    assert bucket.year_distribution == {"2018": 2}
    assert bucket.missing_identifiers == ["3", "4"]
