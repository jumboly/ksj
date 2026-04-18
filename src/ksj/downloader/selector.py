"""`ksj download` の対象 FileEntry を絞り込むロジック。

カタログは同じ (scope, 識別子) に対して shp / gml / geojson を並列配布することがあり、
全件ダウンロードすると冗長になる。format_preference が明示されたときに限り重複を畳む。
CRS が混在するデータセットでは `--crs` で 1 系統のみを選べるようにする。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from ksj.catalog.schema import Dataset, FileEntry


def pick_targets(
    dataset: Dataset,
    year: str,
    *,
    format_preference: Sequence[str] | None = None,
    crs_filter: int | None = None,
) -> list[FileEntry]:
    """version の files から DL 対象を決める。

    - `crs_filter` 指定時は EPSG 完全一致のみ残す (HTML の CRS 正規化済み値に対して)
    - `format_preference` 未指定時はフィルタせず全件返す
    - `format_preference` 指定時は (scope, scope_identifier) をキーに重複を畳む。
      プリファレンス順に最初にマッチしたものを残し、どれもマッチしなければ
      そのキーの候補のうち元々の並び順で最初の 1 件を残す (脱落を避けるため)
    """
    version = dataset.versions.get(year)
    if version is None:
        return []

    entries = list(version.files)

    if crs_filter is not None:
        entries = [f for f in entries if f.crs == crs_filter]

    if format_preference is None:
        return entries

    return list(_dedup_by_preference(entries, format_preference))


def _dedup_by_preference(
    entries: Iterable[FileEntry],
    preference: Sequence[str],
) -> list[FileEntry]:
    # 同一 scope/識別子 のグループを元の順序を保ちつつ束ねる
    groups: dict[tuple[str, str], list[FileEntry]] = {}
    order: list[tuple[str, str]] = []
    for entry in entries:
        key: tuple[str, str] = (str(entry.scope), entry.scope_identifier)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(entry)

    picked: list[FileEntry] = []
    for key in order:
        candidates = groups[key]
        chosen: FileEntry | None = None
        for fmt in preference:
            chosen = next((c for c in candidates if c.format == fmt), None)
            if chosen is not None:
                break
        # プリファレンスに無い形式しか無い scope (例: citygml only) を落とさない
        if chosen is None:
            chosen = candidates[0]
        picked.append(chosen)
    return picked


__all__ = ["pick_targets"]
