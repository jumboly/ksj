"""各サブコマンドの --json / --format json 出力テスト。

ネットワークを触る diff / refresh / html fetch は ``refresh_catalog`` を
monkeypatch で差し替え、download は respx で HTTP を握る。integrate は
conftest の fixture ZIP を使って実際のパイプラインを通す。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from typer.testing import CliRunner

from ksj.catalog.refresh import RefreshSummary
from ksj.catalog.schema import Catalog, Dataset, FileEntry, Version
from ksj.cli import app


def _catalog() -> Catalog:
    return Catalog(
        datasets={
            "N03": Dataset(
                name="行政区域",
                category="政策区域",
                license="CC BY 4.0",
                detail_page="https://example.com/N03.html",
                versions={
                    "2025": Version(
                        files=[
                            FileEntry.model_validate(
                                {
                                    "scope": "national",
                                    "url": "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2025/N03-2025.zip",
                                    "format": "shp",
                                    "crs": 6668,
                                }
                            )
                        ],
                    )
                },
            ),
            "L03-a": Dataset(
                name="土地利用細分メッシュ",
                category="土地利用",
                license="CC BY 4.0",
                versions={
                    "2021": Version(
                        files=[
                            FileEntry.model_validate(
                                {
                                    "scope": "mesh3",
                                    "url": "https://nlftp.mlit.go.jp/ksj/gml/data/L03-a/L03-a-2021/L03-a-2021-5339.zip",
                                    "format": "shp",
                                    "crs": 6668,
                                    "mesh_code": "5339",
                                }
                            )
                        ],
                    )
                },
            ),
        }
    )


def _patch_catalog(monkeypatch: pytest.MonkeyPatch, catalog: Catalog) -> None:
    monkeypatch.setattr("ksj.handlers._catalog_loader.load_catalog", lambda: catalog)


def _parse_json_stdout(output: str) -> dict[str, Any]:
    """stderr の rich markup と混在しても JSON 行だけ取り出す。

    `[error]{msg}` のような rich 装飾が `{` で始まる偽一致を避けるため、
    行頭文字ではなく ``json.loads`` の成功を判定に使う。
    """
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed: dict[str, Any] = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        return parsed
    raise AssertionError(f"JSON 行が見つかりません: {output!r}")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.mark.parametrize("flag_args", [["--json"], ["--format", "json"]])
def test_list_json(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    flag_args: list[str],
) -> None:
    _patch_catalog(monkeypatch, _catalog())
    result = runner.invoke(app, [*flag_args, "list"])

    assert result.exit_code == 0, result.output
    payload = _parse_json_stdout(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "list"
    data = payload["data"]
    assert data["total"] == 2
    codes = {row["code"] for row in data["rows"]}
    assert codes == {"N03", "L03-a"}


def test_list_json_filtered(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    _patch_catalog(monkeypatch, _catalog())
    result = runner.invoke(app, ["--json", "list", "--scope", "mesh3"])

    assert result.exit_code == 0, result.output
    data = _parse_json_stdout(result.stdout)["data"]
    assert [row["code"] for row in data["rows"]] == ["L03-a"]


@pytest.mark.parametrize("flag_args", [["--json"], ["--format", "json"]])
def test_info_json(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    flag_args: list[str],
) -> None:
    _patch_catalog(monkeypatch, _catalog())
    result = runner.invoke(app, [*flag_args, "info", "N03"])

    assert result.exit_code == 0, result.output
    data = _parse_json_stdout(result.stdout)["data"]
    assert data["code"] == "N03"
    assert data["name"] == "行政区域"
    assert len(data["versions"]) == 1
    v = data["versions"][0]
    assert v["year"] == "2025"
    assert v["files"][0]["crs"] == 6668


def test_info_json_unknown_code(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    _patch_catalog(monkeypatch, _catalog())
    result = runner.invoke(app, ["--json", "info", "ZZZ"])

    assert result.exit_code == 1
    payload = _parse_json_stdout(result.stdout)
    assert payload["ok"] is False
    assert payload["exit_code"] == 1
    assert payload["error_kind"] == "dataset_not_found"
    assert "ZZZ" in payload["message"]


def test_info_rich_unknown_code(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    """rich モード (--json 無指定) では従来どおり err console に文言を出す。"""
    _patch_catalog(monkeypatch, _catalog())
    result = runner.invoke(app, ["info", "ZZZ"])

    assert result.exit_code == 1
    # rich_render.failure は err_console に書く。CliRunner はデフォルトで
    # stderr も result.output に含める。
    assert "ZZZ" in result.output


def test_html_list_json_empty(
    tmp_path: Path,
    runner: CliRunner,
) -> None:
    result = runner.invoke(app, ["--json", "html", "list", "--cache-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    data = _parse_json_stdout(result.stdout)["data"]
    assert data["entries"] == []
    assert data["total_bytes"] == 0


def test_html_list_json_populated(
    tmp_path: Path,
    runner: CliRunner,
) -> None:
    # キャッシュ構造は <host>/<path> 階層。テストでは任意のサブディレクトリで良い。
    (tmp_path / "host").mkdir()
    (tmp_path / "host" / "a.html").write_text("<html>A</html>", encoding="utf-8")

    result = runner.invoke(app, ["--json", "html", "list", "--cache-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    data = _parse_json_stdout(result.stdout)["data"]
    assert len(data["entries"]) == 1
    assert data["entries"][0]["relative_path"] == "host/a.html"
    assert data["total_bytes"] > 0


def test_catalog_diff_json(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    """refresh_catalog をモックして diff 出力を検証する。"""
    current = _catalog()
    # fresh は N03 を削除し A09 を追加
    fresh = Catalog(
        datasets={
            "L03-a": current.datasets["L03-a"],
            "A09": Dataset(
                name="自然保全",
                category="地域",
                versions={"2020": Version()},
            ),
        }
    )
    summary = RefreshSummary(
        total_datasets=len(fresh.datasets),
        added=[],
        updated=[],
        skipped=[],
        warnings=[],
        unsupported=[],
    )

    async def _fake_refresh(**_: Any) -> tuple[Catalog, RefreshSummary]:
        return fresh, summary

    _patch_catalog(monkeypatch, current)
    monkeypatch.setattr("ksj.handlers.catalog.refresh_catalog", _fake_refresh)

    result = runner.invoke(app, ["--json", "catalog", "diff"])

    assert result.exit_code == 0, result.output
    data = _parse_json_stdout(result.stdout)["data"]
    assert data["added"] == ["A09"]
    assert data["removed"] == ["N03"]
    assert data["changed"] == []


def test_catalog_missing_returns_json_error(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    """カタログ YAML 不在時の JSON エラー契約を確認する。"""

    def _boom() -> Catalog:
        from ksj.catalog.loader import CatalogNotFoundError

        raise CatalogNotFoundError("not found")

    monkeypatch.setattr("ksj.handlers._catalog_loader.load_catalog", _boom)
    result = runner.invoke(app, ["--json", "list"])

    assert result.exit_code == 1
    payload = _parse_json_stdout(result.stdout)
    assert payload["ok"] is False
    assert payload["error_kind"] == "catalog_not_found"


def test_rich_mode_still_uses_table(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    """--json 未指定時は従来の rich Table を stdout に出す (互換性担保)。"""
    _patch_catalog(monkeypatch, _catalog())
    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0, result.output
    # Table タイトル文言は rich_render 側で保持されている
    assert "KSJ カタログ" in result.output
    # stdout の先頭行は JSON ではない (rich モードの証明)
    first_line = result.stdout.strip().splitlines()[0]
    assert not first_line.startswith("{")


# ---- write 系 ---------------------------------------------------------------


def test_catalog_summary_json(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    _patch_catalog(monkeypatch, _catalog())
    result = runner.invoke(app, ["--json", "catalog", "summary"])

    assert result.exit_code == 0, result.output
    data = _parse_json_stdout(result.stdout)["data"]
    assert data["total_datasets"] == 2
    # categories は count 降順、scope_histogram も同様。キーは存在確認のみで十分
    assert "政策区域" in data["categories"]
    assert data["scope_histogram"].get("national", 0) >= 1
    assert "2021" in data["years_seen"] and "2025" in data["years_seen"]


@respx.mock
def test_download_json_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    _patch_catalog(monkeypatch, _catalog())
    url = "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2025/N03-2025.zip"
    respx.get(url).mock(return_value=httpx.Response(200, content=b"X" * 512))

    result = runner.invoke(
        app,
        [
            "--json",
            "download",
            "N03",
            "--year",
            "2025",
            "--data-dir",
            str(tmp_path),
            "--rate",
            "100",
        ],
    )

    assert result.exit_code == 0, result.output
    data = _parse_json_stdout(result.stdout)["data"]
    assert data["code"] == "N03"
    assert data["year"] == "2025"
    assert len(data["results"]) == 1
    assert data["results"][0]["error"] is None


def test_download_json_invalid_argument(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    """--scope と --prefer-national の同時指定は invalid_argument で弾かれる。"""
    _patch_catalog(monkeypatch, _catalog())
    result = runner.invoke(
        app,
        [
            "--json",
            "download",
            "N03",
            "--year",
            "2025",
            "--scope",
            "national",
            "--prefer-national",
            "--data-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    payload = _parse_json_stdout(result.stdout)
    assert payload["ok"] is False
    assert payload["error_kind"] == "invalid_argument"


def test_ingest_local_json(
    tmp_path: Path,
    runner: CliRunner,
) -> None:
    src_zip = tmp_path / "src.zip"
    src_zip.write_bytes(b"zipdata")
    data_dir = tmp_path / "data"

    result = runner.invoke(
        app,
        [
            "--json",
            "ingest-local",
            "N03",
            "--year",
            "2025",
            "--from",
            str(src_zip),
            "--data-dir",
            str(data_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    data = _parse_json_stdout(result.stdout)["data"]
    assert data["code"] == "N03"
    assert len(data["copied"]) == 1


def test_ingest_local_json_missing_source(
    tmp_path: Path,
    runner: CliRunner,
) -> None:
    result = runner.invoke(
        app,
        [
            "--json",
            "ingest-local",
            "N03",
            "--year",
            "2025",
            "--from",
            str(tmp_path / "nope.zip"),
            "--data-dir",
            str(tmp_path / "data"),
        ],
    )

    assert result.exit_code == 1
    payload = _parse_json_stdout(result.stdout)
    assert payload["error_kind"] == "invalid_argument"


def test_catalog_refresh_json_dry_run(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    fake_catalog = _catalog()
    summary = RefreshSummary(
        total_datasets=2,
        added=[],
        updated=["N03"],
        skipped=[],
        warnings=[],
        unsupported=[],
    )

    async def _fake_refresh(**_: Any) -> tuple[Catalog, RefreshSummary]:
        return fake_catalog, summary

    monkeypatch.setattr("ksj.handlers.catalog.refresh_catalog", _fake_refresh)

    result = runner.invoke(app, ["--json", "catalog", "refresh", "--dry-run"])

    assert result.exit_code == 0, result.output
    data = _parse_json_stdout(result.stdout)["data"]
    assert data["summary"]["total_datasets"] == 2
    assert data["saved_path"] is None


def test_html_fetch_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    fake_catalog = _catalog()
    summary = RefreshSummary(
        total_datasets=2,
        added=[],
        updated=[],
        skipped=[],
        warnings=[],
        unsupported=[],
    )

    async def _fake_refresh(**_: Any) -> tuple[Catalog, RefreshSummary]:
        return fake_catalog, summary

    monkeypatch.setattr("ksj.handlers.html.refresh_catalog", _fake_refresh)

    result = runner.invoke(
        app,
        ["--json", "html", "fetch", "--cache-dir", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    data = _parse_json_stdout(result.stdout)["data"]
    assert data["cache_stats"]["file_count"] == 0
    assert data["summary"]["total_datasets"] == 2


def test_integrate_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_shapefile_zip: Callable[..., Path],
    stage_zip: Callable[[Path, Path], Path],
    seed_manifest: Callable[..., None],
    tiny_geodataframe: Any,
    runner: CliRunner,
) -> None:
    """実パイプラインを通して IntegrateResult の JSON 出力を検証する。"""
    data_dir = tmp_path / "data"
    src_zip = write_shapefile_zip(tiny_geodataframe, "N03-2025")
    dest = stage_zip(data_dir / "raw" / "N03" / "2025", src_zip)

    url = "https://example.com/N03-2025.zip"
    catalog = Catalog(
        datasets={
            "N03": Dataset(
                name="行政区域",
                license="CC BY 4.0",
                detail_page="https://example.com/N03.html",
                versions={
                    "2025": Version(
                        files=[
                            FileEntry.model_validate(
                                {
                                    "scope": "national",
                                    "url": url,
                                    "format": "shp",
                                    "crs": 6668,
                                }
                            )
                        ]
                    )
                },
            )
        }
    )
    seed_manifest(
        data_dir,
        "N03",
        "2025",
        entries=[
            {
                "url": url,
                "rel_path": str(dest.relative_to(data_dir)),
                "size": dest.stat().st_size,
                "scope": "national",
                "format": "shp",
            }
        ],
    )
    _patch_catalog(monkeypatch, catalog)

    result = runner.invoke(
        app,
        [
            "--json",
            "integrate",
            "N03",
            "--year",
            "2025",
            "--data-dir",
            str(data_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    data = _parse_json_stdout(result.stdout)["data"]
    assert data["strategy"] == "national"
    assert data["layer_names"] == ["N03_2025"]
    # Path は default=str で文字列化される契約
    assert isinstance(data["output_path"], str)


def test_integrate_json_unknown_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    _patch_catalog(monkeypatch, _catalog())
    result = runner.invoke(
        app,
        [
            "--json",
            "integrate",
            "ZZZ",
            "--year",
            "2025",
            "--data-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    payload = _parse_json_stdout(result.stdout)
    assert payload["error_kind"] == "dataset_not_found"
