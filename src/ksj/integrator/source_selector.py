"""統合対象のファイルを ``Dataset.versions[year].files`` から選び出す。

戦略は 2 本道:
1. 対象年度以前に national scope が 1 本でもあれば、最新の national を採用
   (``strategy="national"``)
2. 無ければ scope + 識別子でバケット化し、各バケットで「対象年度以前で最新」
   を 1 件選んで union する (``strategy="latest-fill"``)。``strict_year=True``
   のときは「年度完全一致」のみ (``strategy="strict-year"``)

docs/integration.md の設計方針に沿って、``SelectionPlan`` に戦略・採用ファイル群・
カバレッジ集計を束ねる。pipeline / CLI / メタ生成の全てで同じ構造体を参照する。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal

from ksj.catalog.schema import Dataset, FileEntry

Strategy = Literal["national", "latest-fill", "strict-year"]


class NoSourcesError(LookupError):
    """``select_sources`` で採用できるファイルが 1 件も無いとき送出する。"""


@dataclass(slots=True, frozen=True)
class SelectedSource:
    """統合に採用する 1 ファイル分の決定。

    ``year`` は実際にこのファイルが採られた配布年度。latest-fill で古い年度が
    選ばれたときは ``year`` が ``--year`` 引数と異なる値になる。
    """

    file_entry: FileEntry
    year: str


@dataclass(slots=True)
class BucketCoverage:
    """scope 別の統合結果サマリ。

    ``expected`` はそのデータセット全年度に現れる識別子数の和集合から推定する。
    事前にハードコードするより「このデータセットが本来カバーし得る識別子数」
    として素直で、部分整備データセットにも自然に馴染む。
    """

    scope: str
    covered: int
    expected: int | None = None
    year_distribution: dict[str, int] = field(default_factory=dict)
    missing_identifiers: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        """coverage_summary メタデータ用の dict (防御コピー付き)。"""
        return {
            "covered": self.covered,
            "expected": self.expected,
            "year_distribution": dict(self.year_distribution),
            "missing_identifiers": list(self.missing_identifiers),
        }


@dataclass(slots=True)
class SelectionPlan:
    """``select_sources`` の戻り値。pipeline / CLI / メタ生成の全てで参照する。"""

    strategy: Strategy
    sources: list[SelectedSource]
    coverage: list[BucketCoverage] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    national_year: str | None = None


def select_sources(
    dataset: Dataset,
    year: str,
    *,
    strict_year: bool = False,
) -> SelectionPlan:
    """``year`` を対象に統合対象ファイル群を決定する。"""
    if year not in dataset.versions:
        raise NoSourcesError(f"年度 {year} は登録されていない")

    national = _find_latest_national(dataset, year)
    if national is not None:
        source = SelectedSource(file_entry=national[1], year=national[0])
        return SelectionPlan(
            strategy="national",
            sources=[source],
            national_year=national[0],
        )

    strategy: Strategy = "strict-year" if strict_year else "latest-fill"
    buckets = _build_buckets(dataset, year, strict_year=strict_year)
    if not buckets:
        raise NoSourcesError(
            f"年度 {year} に採用できるソースが 0 件"
            f" (strict_year={strict_year}, 他年度も含めて確認してください)"
        )

    sources = [SelectedSource(file_entry=f, year=y) for (_, _), (y, f) in buckets.items()]
    coverage, notes = _summarize_coverage(
        dataset, buckets, target_year=year, strict_year=strict_year
    )

    return SelectionPlan(
        strategy=strategy,
        sources=sources,
        coverage=coverage,
        notes=notes,
    )


def _find_latest_national(dataset: Dataset, year: str) -> tuple[str, FileEntry] | None:
    """``year`` 以前で最も新しい national ファイルを (year, entry) で返す。

    年度は KSJ 全データセットで YYYY 形式なので辞書順比較で十分。
    """
    candidates: list[tuple[str, FileEntry]] = []
    for v_year, version in dataset.versions.items():
        if v_year > year:
            continue
        for file_entry in version.files:
            if file_entry.scope == "national":
                candidates.append((v_year, file_entry))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[-1]


def _build_buckets(
    dataset: Dataset,
    target_year: str,
    *,
    strict_year: bool,
) -> dict[tuple[str, str], tuple[str, FileEntry]]:
    """(scope, identifier) ごとに採用する (year, FileEntry) を決める。

    strict_year=False なら target_year 以前の候補から最新年度を、
    strict_year=True なら target_year 完全一致のみを採用。national は呼び出し元で
    除外済みの前提。
    """
    if strict_year:
        version = dataset.versions.get(target_year)
        versions_iter: list[tuple[str, Any]] = [(target_year, version)] if version else []
    else:
        versions_iter = [(y, v) for y, v in dataset.versions.items() if y <= target_year]

    buckets: dict[tuple[str, str], tuple[str, FileEntry]] = {}
    for v_year, version in versions_iter:
        for file_entry in version.files:
            if file_entry.scope == "national":
                continue
            key = (file_entry.scope, file_entry.scope_bucket_key)
            existing = buckets.get(key)
            if existing is None or existing[0] < v_year:
                buckets[key] = (v_year, file_entry)
    return buckets


def _summarize_coverage(
    dataset: Dataset,
    buckets: dict[tuple[str, str], tuple[str, FileEntry]],
    *,
    target_year: str,
    strict_year: bool,
) -> tuple[list[BucketCoverage], list[str]]:
    """scope 別に BucketCoverage を組み立て、人間可読メモを生成する。"""
    # expected は「そのデータセットが全期間通じて配布してきた識別子の和集合」を採用する。
    # buckets の対象 (target_year 以前 or 同年) より広い範囲を参照する必要があるため、
    # ここで別途ループを回す (1 パス合流は意図的にしない)。
    expected_by_scope: dict[str, set[str]] = defaultdict(set)
    for version in dataset.versions.values():
        for file_entry in version.files:
            if file_entry.scope == "national":
                continue
            expected_by_scope[file_entry.scope].add(file_entry.scope_bucket_key)

    covered_by_scope: dict[str, set[str]] = defaultdict(set)
    years_by_scope: dict[str, list[str]] = defaultdict(list)
    for (scope, ident), (year, _file) in buckets.items():
        covered_by_scope[scope].add(ident)
        years_by_scope[scope].append(year)

    coverage: list[BucketCoverage] = []
    notes: list[str] = []
    for scope in sorted(covered_by_scope):
        covered_ids = covered_by_scope[scope]
        expected_ids = expected_by_scope.get(scope, set())
        year_dist: dict[str, int] = defaultdict(int)
        for y in years_by_scope[scope]:
            year_dist[y] += 1
        missing = sorted(expected_ids - covered_ids)
        coverage.append(
            BucketCoverage(
                scope=scope,
                covered=len(covered_ids),
                expected=len(expected_ids) if expected_ids else None,
                year_distribution=dict(year_dist),
                missing_identifiers=missing,
            )
        )
        if not strict_year:
            fallback_count = sum(1 for y in years_by_scope[scope] if y != target_year)
            if fallback_count > 0:
                notes.append(
                    f"{scope}: {fallback_count} 件を過去年度から補填 (target={target_year})"
                )

    return coverage, notes
