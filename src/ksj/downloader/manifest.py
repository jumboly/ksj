"""`data/manifest.json` の読み書き。

download / ingest-local を繰り返し実行したときに「何をどこに配置済みか」を追跡するため
の状態ファイル。人間がコミットするものではなく動的状態なので JSON (YAML ではなく)。
`data/` 配下は gitignore 済み。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_MANIFEST_FILENAME = "manifest.json"

# ingest-local で取り込んだファイルの url 欄に使う擬似スキーム。
# 正規の http(s) URL と区別しつつ「このエントリは手動取り込み」を明示する。
LOCAL_URL_PREFIX = "local://"


class ManifestEntry(BaseModel):
    """取得済み 1 ZIP の記録。"""

    model_config = ConfigDict(extra="forbid")

    url: str
    path: str
    size_bytes: int
    downloaded_at: datetime
    # ingest-local はカタログ由来のメタが無いので None を許容する
    scope: str | None = None
    scope_identifier: str | None = None
    format: str | None = None


class DatasetManifest(BaseModel):
    """1 データセットの年度別エントリ集合。"""

    model_config = ConfigDict(extra="forbid")

    # "2025" -> entries
    versions: dict[str, list[ManifestEntry]] = Field(default_factory=dict)


class Manifest(BaseModel):
    """data/manifest.json 全体のルート。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    datasets: dict[str, DatasetManifest] = Field(default_factory=dict)

    def get_entries(self, code: str, year: str) -> list[ManifestEntry]:
        ds = self.datasets.get(code)
        if ds is None:
            return []
        return list(ds.versions.get(year, []))

    def set_entries(self, code: str, year: str, entries: list[ManifestEntry]) -> None:
        ds = self.datasets.setdefault(code, DatasetManifest())
        ds.versions[year] = entries


def manifest_path(data_dir: Path) -> Path:
    return data_dir / DEFAULT_MANIFEST_FILENAME


def load_manifest(data_dir: Path) -> Manifest:
    """マニフェストを読み込む。存在しない場合は空で返す (初回実行)。"""
    target = manifest_path(data_dir)
    if not target.exists():
        return Manifest()
    return Manifest.model_validate_json(target.read_text(encoding="utf-8"))


def save_manifest(manifest: Manifest, data_dir: Path) -> Path:
    """マニフェストを JSON 書き出し。"""
    target = manifest_path(data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        manifest.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )
    return target


__all__ = [
    "DEFAULT_MANIFEST_FILENAME",
    "LOCAL_URL_PREFIX",
    "DatasetManifest",
    "Manifest",
    "ManifestEntry",
    "load_manifest",
    "manifest_path",
    "save_manifest",
]
