"""統合対象のファイルを `Dataset.versions[year].files` から選び出す。

Phase 4 範囲: ``select_national`` のみ。national scope の FileEntry を抽出する。
Phase 5 で latest-fill / 識別子バケット union のロジックを追加する。
"""

from __future__ import annotations

from dataclasses import dataclass

from ksj.catalog.schema import Dataset, FileEntry


class NoNationalSourceError(LookupError):
    """指定年度に national scope のファイルが存在しないとき送出する。"""


@dataclass(slots=True)
class SelectedSource:
    """統合に採用する 1 ファイル。Phase 5 で list[SelectedSource] に拡張予定。"""

    file_entry: FileEntry
    year: str


def select_national(dataset: Dataset, year: str) -> SelectedSource:
    """``year`` の national ファイルを 1 件返す。複数あれば先頭を採用する。

    複数 national が出るケースは現状ほぼ無いが、将来的な異形 (national-summary 等)
    への備えとしてリストから取り出す。
    """
    version = dataset.versions.get(year)
    if version is None:
        raise NoNationalSourceError(f"年度 {year} は登録されていない")

    nationals = [f for f in version.files if f.scope == "national"]
    if not nationals:
        raise NoNationalSourceError(
            f"年度 {year} に national scope のファイルが無い (Phase 4 は national 限定)"
        )

    return SelectedSource(file_entry=nationals[0], year=year)
