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


def test_g04a_is_mesh2_distribution() -> None:
    """G04-a は 2 次メッシュ単位で配布されていることの回帰テスト。

    配布ホストは過去の調査では www.gsi.go.jp だったが、2026-04 時点で
    nlftp.mlit.go.jp に移行している。scope の検証に絞る。
    """
    catalog = load_catalog()
    dataset = catalog.datasets["G04-a"]
    scopes = {f.scope for v in dataset.versions.values() for f in v.files}
    assert scopes == {"mesh2"}


def test_a03_has_urban_area_scope() -> None:
    """A03 は三大都市圏 (SYUTO/CHUBU/KINKI) のみ配布されることの回帰テスト。"""
    catalog = load_catalog()
    dataset = catalog.datasets["A03"]
    scopes = {f.scope for v in dataset.versions.values() for f in v.files}
    assert scopes == {"urban_area"}
    urban_codes = {
        f.urban_area_code for v in dataset.versions.values() for f in v.files if f.urban_area_code
    }
    assert urban_codes == {"SYUTO", "CHUBU", "KINKI"}
