from __future__ import annotations

import json
import shutil
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from ksj.catalog import loader as catalog_loader
from ksj.cli import app
from ksj.downloader.manifest import LOCAL_URL_PREFIX, load_manifest

FIXTURE = Path(__file__).parent.parent / "fixtures" / "catalog" / "phase3_fixture.yaml"


def _install_fixture_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """同梱 datasets.yaml の代わりに Phase 3 用 fixture を読ませる。

    loader は絶対パスを算出するため、CWD 変更ではなく DEFAULT_CATALOG_PATH を
    直接書き換える。
    """
    target = tmp_path / "catalog" / "datasets.yaml"
    target.parent.mkdir(parents=True)
    shutil.copy2(FIXTURE, target)
    monkeypatch.setattr(catalog_loader, "DEFAULT_CATALOG_PATH", target)
    return target


@respx.mock
def test_download_writes_files_and_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fixture_catalog(tmp_path, monkeypatch)

    shp_url = "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2025/N03-20250101_GML.zip"
    gj_url = "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2025/N03-20250101_GeoJSON.zip"
    respx.get(shp_url).mock(return_value=httpx.Response(200, content=b"S" * 1000))
    respx.get(gj_url).mock(return_value=httpx.Response(200, content=b"G" * 1000))

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "download",
            "N03",
            "--year",
            "2025",
            "--data-dir",
            str(tmp_path / "data"),
            "--rate",
            "100",
        ],
    )
    assert result.exit_code == 0, result.output

    raw_dir = tmp_path / "data" / "raw" / "N03" / "2025"
    assert (raw_dir / "N03-20250101_GML.zip").exists()
    assert (raw_dir / "N03-20250101_GeoJSON.zip").exists()

    manifest = load_manifest(tmp_path / "data")
    entries = manifest.get_entries("N03", "2025")
    assert {e.url for e in entries} == {shp_url, gj_url}
    assert all(e.size_bytes == 1000 for e in entries)


@respx.mock
def test_download_format_preference_reduces_to_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fixture_catalog(tmp_path, monkeypatch)

    shp_url = "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2025/N03-20250101_GML.zip"
    gj_url = "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2025/N03-20250101_GeoJSON.zip"
    respx.get(shp_url).mock(return_value=httpx.Response(200, content=b"S" * 1000))
    geojson_route = respx.get(gj_url).mock(return_value=httpx.Response(200, content=b"G" * 1000))

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "download",
            "N03",
            "--year",
            "2025",
            "--format-preference",
            "shp",
            "--data-dir",
            str(tmp_path / "data"),
            "--rate",
            "100",
        ],
    )
    assert result.exit_code == 0, result.output
    # preference で shp を選んだため geojson は取得しない
    assert not geojson_route.called


def test_download_unknown_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fixture_catalog(tmp_path, monkeypatch)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["download", "NOPE", "--year", "2025", "--data-dir", str(tmp_path / "data")],
    )
    assert result.exit_code == 1


def test_download_unknown_year(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fixture_catalog(tmp_path, monkeypatch)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["download", "N03", "--year", "9999", "--data-dir", str(tmp_path / "data")],
    )
    assert result.exit_code == 1


def test_download_scope_and_prefer_national_are_mutually_exclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fixture_catalog(tmp_path, monkeypatch)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "download",
            "N03",
            "--year",
            "2025",
            "--scope",
            "national",
            "--prefer-national",
            "--data-dir",
            str(tmp_path / "data"),
        ],
    )
    assert result.exit_code == 1
    assert "同時指定できません" in result.output


def test_ingest_local_single_zip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fixture_catalog(tmp_path, monkeypatch)

    src = tmp_path / "source.zip"
    src.write_bytes(b"LOCAL" * 20)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "ingest-local",
            "N03",
            "--year",
            "2025",
            "--from",
            str(src),
            "--data-dir",
            str(tmp_path / "data"),
        ],
    )
    assert result.exit_code == 0, result.output
    dest = tmp_path / "data" / "raw" / "N03" / "2025" / "source.zip"
    assert dest.exists()

    manifest_raw = json.loads((tmp_path / "data" / "manifest.json").read_text())
    urls = [e["url"] for e in manifest_raw["datasets"]["N03"]["versions"]["2025"]]
    assert any(u.startswith(LOCAL_URL_PREFIX) for u in urls)


def test_ingest_local_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fixture_catalog(tmp_path, monkeypatch)

    src_dir = tmp_path / "incoming"
    src_dir.mkdir()
    (src_dir / "a.zip").write_bytes(b"A" * 10)
    (src_dir / "b.zip").write_bytes(b"B" * 10)
    (src_dir / "ignored.txt").write_bytes(b"skip me")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "ingest-local",
            "N03",
            "--year",
            "2025",
            "--from",
            str(src_dir),
            "--data-dir",
            str(tmp_path / "data"),
        ],
    )
    assert result.exit_code == 0, result.output
    dest_dir = tmp_path / "data" / "raw" / "N03" / "2025"
    names = {p.name for p in dest_dir.iterdir()}
    assert names == {"a.zip", "b.zip"}


def test_ingest_local_missing_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fixture_catalog(tmp_path, monkeypatch)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "ingest-local",
            "N03",
            "--year",
            "2025",
            "--from",
            str(tmp_path / "missing.zip"),
            "--data-dir",
            str(tmp_path / "data"),
        ],
    )
    assert result.exit_code == 1
