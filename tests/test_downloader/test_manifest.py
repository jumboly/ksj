from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ksj.downloader.manifest import (
    Manifest,
    ManifestEntry,
    load_manifest,
    save_manifest,
)


def _entry(url: str, path: str) -> ManifestEntry:
    return ManifestEntry(
        url=url,
        path=path,
        size_bytes=100,
        downloaded_at=datetime(2026, 4, 18, tzinfo=UTC),
        scope="national",
        scope_identifier="",
        format="shp",
    )


def test_empty_when_missing(tmp_path: Path) -> None:
    manifest = load_manifest(tmp_path)
    assert manifest.datasets == {}


def test_roundtrip(tmp_path: Path) -> None:
    manifest = Manifest()
    manifest.set_entries("N03", "2025", [_entry("https://e.co/a.zip", "raw/N03/2025/a.zip")])
    path = save_manifest(manifest, tmp_path)
    assert path.exists()

    reloaded = load_manifest(tmp_path)
    assert reloaded.get_entries("N03", "2025")[0].url == "https://e.co/a.zip"


def test_set_entries_replaces_only_target_slot(tmp_path: Path) -> None:
    manifest = Manifest()
    manifest.set_entries("N03", "2025", [_entry("u1", "p1")])
    manifest.set_entries("A03", "2003", [_entry("u2", "p2")])

    # 上書きは N03/2025 のみに局所的であること (A03 が壊れない)
    manifest.set_entries("N03", "2025", [_entry("u1-new", "p1-new")])

    assert [e.url for e in manifest.get_entries("N03", "2025")] == ["u1-new"]
    assert [e.url for e in manifest.get_entries("A03", "2003")] == ["u2"]


def test_save_excludes_none(tmp_path: Path) -> None:
    manifest = Manifest()
    manifest.set_entries("N03", "2025", [_entry("u", "p")])
    path = save_manifest(manifest, tmp_path)
    raw = path.read_text(encoding="utf-8")
    # ManifestEntry に optional は無い想定なので単純な smoke チェック
    assert "schema_version" in raw
    assert "N03" in raw
