"""カタログ YAML の読込とバリデーション。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ksj.catalog.schema import Catalog

# プロジェクトルート直下の catalog/datasets.yaml を規定の場所とする
DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[3] / "catalog" / "datasets.yaml"
# Phase 9: scraper 対象外の description / use_cases を別ファイルで管理する。
# refresh で datasets.yaml を上書きしても LLM/人手で埋めた値が失われないよう分離。
DEFAULT_ANNOTATIONS_PATH = Path(__file__).resolve().parents[3] / "catalog" / "annotations.yaml"


class CatalogNotFoundError(FileNotFoundError):
    """カタログファイルが見つからない。"""


def load_catalog(
    path: Path | None = None,
    annotations_path: Path | None = None,
) -> Catalog:
    """YAML を読込んで ``Catalog`` として返す。

    path 未指定時はプロジェクト同梱の ``catalog/datasets.yaml`` を使う。
    Phase 9: ``annotations_path`` (デフォルト ``catalog/annotations.yaml``) が存在
    すれば description / use_cases を各 Dataset に merge する。ファイルが無い場合
    は merge をスキップし (新規プロジェクトで annotations が未整備でも起動可能)。
    """

    target = path if path is not None else DEFAULT_CATALOG_PATH
    try:
        with target.open("r", encoding="utf-8") as f:
            raw: Any = yaml.safe_load(f)
    except FileNotFoundError as exc:
        raise CatalogNotFoundError(f"カタログファイルが見つかりません: {target}") from exc

    if raw is None:
        raw = {}

    _merge_annotations(
        raw, annotations_path if annotations_path is not None else DEFAULT_ANNOTATIONS_PATH
    )

    return Catalog.model_validate(raw)


def load_annotations(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """annotations.yaml を ``{code: {description, use_cases}}`` の形で読む。

    ファイルが無い / 形式不正の場合は空 dict を返す (呼び出し側は存在チェック不要)。
    refresh の欠損検知や loader の merge で共用する。
    """
    target = path if path is not None else DEFAULT_ANNOTATIONS_PATH
    try:
        with target.open("r", encoding="utf-8") as f:
            raw: Any = yaml.safe_load(f)
    except FileNotFoundError:
        return {}
    if not isinstance(raw, dict):
        return {}
    datasets = raw.get("datasets")
    if not isinstance(datasets, dict):
        return {}
    return {code: ann for code, ann in datasets.items() if isinstance(ann, dict)}


def _merge_annotations(raw: dict[str, Any], annotations_path: Path) -> None:
    """annotations.yaml の description / use_cases を datasets dict に注入する。

    datasets.yaml 側に description / use_cases が (旧仕様で) 残っている場合は
    annotations 側を優先する (annotations は運用上の正とする)。
    """
    ann_datasets = load_annotations(annotations_path)
    datasets = raw.setdefault("datasets", {})
    if not isinstance(datasets, dict):
        return
    # description は明示的な "" も採用するため is not None、use_cases は空リストが
    # 「未指定」と区別できないため truthy で判定 (空リスト上書きは意味がない)
    for code, ann in ann_datasets.items():
        ds = datasets.get(code)
        if not isinstance(ds, dict):
            continue
        if ann.get("description") is not None:
            ds["description"] = ann["description"]
        if ann.get("use_cases"):
            ds["use_cases"] = ann["use_cases"]
