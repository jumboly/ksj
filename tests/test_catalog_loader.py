from __future__ import annotations

from pathlib import Path

import pytest

from ksj.catalog.loader import CatalogNotFoundError, load_catalog


def test_load_bundled_catalog() -> None:
    """リポジトリ同梱の catalog/datasets.yaml が読み込めること。"""
    catalog = load_catalog()
    assert len(catalog.datasets) >= 5
    # Phase 1 の手書き分に含まれるべき代表データセット
    for code in ("N03", "A03", "L03-a", "A53", "G04-a"):
        assert code in catalog.datasets


def test_load_from_custom_path(tmp_path: Path) -> None:
    target = tmp_path / "custom.yaml"
    target.write_text(
        """
schema_version: 1
datasets:
  TEST:
    name: テスト
    versions:
      "2024":
        files:
          - scope: national
            url: https://example.com/test.zip
            format: shp
""".strip(),
        encoding="utf-8",
    )
    catalog = load_catalog(target)
    assert catalog.datasets["TEST"].name == "テスト"


def test_load_missing_path_raises(tmp_path: Path) -> None:
    with pytest.raises(CatalogNotFoundError):
        load_catalog(tmp_path / "nope.yaml")


def test_g04a_uses_different_host() -> None:
    """G04-a は www.gsi.go.jp でホストされていることを回帰テスト。"""
    catalog = load_catalog()
    dataset = catalog.datasets["G04-a"]
    urls = [f.url for version in dataset.versions.values() for f in version.files]
    assert all(url.startswith("https://www.gsi.go.jp/") for url in urls)


def test_a03_has_urban_area_scope() -> None:
    catalog = load_catalog()
    dataset = catalog.datasets["A03"]
    scopes = {f.scope for v in dataset.versions.values() for f in v.files}
    assert scopes == {"urban_area"}
    assert dataset.coverage == "partial"
