"""`ksj ingest-local` の純粋関数実装。"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ksj.downloader import ManifestEntry, load_manifest, save_manifest
from ksj.downloader.manifest import LOCAL_URL_PREFIX
from ksj.errors import ErrorKind, HandlerError


@dataclass(slots=True)
class IngestLocalReport:
    code: str
    year: str
    dest_root: Path
    copied: list[Path] = field(default_factory=list)


def ingest_local_data(
    code: str,
    year: str,
    *,
    source: Path,
    data_dir: Path,
) -> IngestLocalReport:
    if not source.exists():
        raise HandlerError(
            ErrorKind.INVALID_ARGUMENT,
            f"--from で指定されたパスが見つかりません: {source}",
        )

    if source.is_dir():
        zips = sorted(p for p in source.iterdir() if p.is_file() and p.suffix.lower() == ".zip")
    else:
        zips = [source]
    if not zips:
        raise HandlerError(
            ErrorKind.INVALID_ARGUMENT,
            f"ZIP が見つかりません: {source}",
        )

    dest_root = data_dir / "raw" / code / year
    dest_root.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest(data_dir)
    existing = {e.url: e for e in manifest.get_entries(code, year)}
    now = datetime.now(UTC).replace(microsecond=0)
    copied: list[Path] = []
    for zip_path in zips:
        dest = dest_root / zip_path.name
        shutil.copy2(zip_path, dest)
        # 実 URL ではなくローカル path を manifest に残すため擬似 URL を作る
        pseudo_url = f"{LOCAL_URL_PREFIX}{zip_path.resolve()}"
        existing[pseudo_url] = ManifestEntry(
            url=pseudo_url,
            path=str(dest.relative_to(data_dir)),
            size_bytes=dest.stat().st_size,
            downloaded_at=now,
        )
        copied.append(dest)

    manifest.set_entries(code, year, list(existing.values()))
    save_manifest(manifest, data_dir)
    return IngestLocalReport(code=code, year=year, dest_root=dest_root, copied=copied)
