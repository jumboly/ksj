from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from ksj.cli import app
from ksj.reader import read_integrated
from ksj.writer import write


@pytest.fixture
def seed_integrated(
    make_vector_layer: Callable[..., Any],
) -> Callable[..., None]:
    def _seed(
        path: Path, gdf: Any, *, metadata: dict[str, Any] | None = None, fmt: str = "gpkg"
    ) -> None:
        layer = make_vector_layer("X01_2025", gdf)
        write([layer], path, metadata=metadata or {"dataset_code": "X01"}, format=fmt)

    return _seed


def test_convert_gpkg_to_parquet_preserves_metadata(
    tmp_path: Path, tiny_geodataframe: Any, seed_integrated: Callable[..., None]
) -> None:
    input_path = tmp_path / "X01-2025.gpkg"
    seed_integrated(
        input_path, tiny_geodataframe, metadata={"dataset_code": "X01", "layers": ["X01_2025"]}
    )

    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(input_path), "--format", "parquet"])
    assert result.exit_code == 0, result.output

    output_path = input_path.with_suffix(".parquet")
    assert output_path.exists()

    layers, metadata = read_integrated(output_path)
    assert metadata["dataset_code"] == "X01"
    assert layers[0].layer_name == "X01_2025"


def test_convert_parquet_to_gpkg_with_explicit_out(
    tmp_path: Path, tiny_geodataframe: Any, seed_integrated: Callable[..., None]
) -> None:
    input_path = tmp_path / "src.parquet"
    seed_integrated(
        input_path,
        tiny_geodataframe,
        metadata={"dataset_code": "A03", "layers": ["A03_2003"]},
        fmt="parquet",
    )
    out_path = tmp_path / "dest" / "converted.gpkg"

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["convert", str(input_path), "--format", "gpkg", "--out", str(out_path)],
    )
    assert result.exit_code == 0, result.output
    assert out_path.exists()

    _, metadata = read_integrated(out_path)
    assert metadata["dataset_code"] == "A03"


def test_convert_rejects_same_format_output(
    tmp_path: Path, tiny_geodataframe: Any, seed_integrated: Callable[..., None]
) -> None:
    input_path = tmp_path / "X01-2025.gpkg"
    seed_integrated(input_path, tiny_geodataframe)

    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(input_path), "--format", "gpkg"])
    assert result.exit_code == 1
    assert "同形式への変換は無意味" in result.output


def test_convert_warns_when_metadata_missing(tmp_path: Path, tiny_geodataframe: Any) -> None:
    import pyogrio

    input_path = tmp_path / "legacy.gpkg"
    pyogrio.write_dataframe(tiny_geodataframe, input_path, driver="GPKG", layer="plain")

    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(input_path), "--format", "parquet"])
    assert result.exit_code == 0, result.output
    assert "警告" in result.output
