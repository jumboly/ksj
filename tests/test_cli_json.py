"""read-only 4 コマンドの --json / --format json 出力テスト。

write 系 (download / integrate / catalog refresh / html fetch / ingest-local)
は PR #2 で追加する。catalog diff はネットワークに出るため
``ksj.handlers.catalog.refresh_catalog`` をモックする。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
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
                                    "url": "https://example.com/N03-2025.zip",
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
                                    "url": "https://example.com/L03-a-2021-5339.zip",
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
