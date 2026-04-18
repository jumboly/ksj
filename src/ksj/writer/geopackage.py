"""GeoPackage の書き出しと出典 JSON のメタデータ埋め込み。

埋め込み先は OGC GeoPackage 仕様の ``gpkg_metadata`` / ``gpkg_metadata_reference``
表 (Metadata Extension)。pyogrio はデータセットレベルのメタデータ書き込みを安定
サポートしないため、書き出し直後に sqlite3 で直接 INSERT する。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pyogrio

from ksj.reader import VectorLayer

# OGC GeoPackage Metadata Extension v1.4 で定義されるカラム値。
# https://www.geopackage.org/spec/#extension_metadata
_METADATA_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS gpkg_metadata (
    id INTEGER CONSTRAINT m_pk PRIMARY KEY ASC NOT NULL,
    md_scope TEXT NOT NULL DEFAULT 'dataset',
    md_standard_uri TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'text/xml',
    metadata TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS gpkg_metadata_reference (
    reference_scope TEXT NOT NULL,
    table_name TEXT,
    column_name TEXT,
    row_id_value INTEGER,
    timestamp DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    md_file_id INTEGER NOT NULL,
    md_parent_id INTEGER,
    CONSTRAINT crmr_mfi_fk FOREIGN KEY (md_file_id) REFERENCES gpkg_metadata(id),
    CONSTRAINT crmr_mpi_fk FOREIGN KEY (md_parent_id) REFERENCES gpkg_metadata(id)
);
"""

# gpkg_extensions に Metadata Extension の宣言を入れる必要がある。
# 仕様で必須カラムだけ網羅する。
_EXTENSIONS_REGISTER_SQL = """
CREATE TABLE IF NOT EXISTS gpkg_extensions (
    table_name TEXT,
    column_name TEXT,
    extension_name TEXT NOT NULL,
    definition TEXT NOT NULL,
    scope TEXT NOT NULL,
    CONSTRAINT ge_tce UNIQUE (table_name, column_name, extension_name)
);
INSERT OR IGNORE INTO gpkg_extensions
    (table_name, column_name, extension_name, definition, scope)
VALUES
    (NULL, NULL, 'gpkg_metadata',
     'http://www.geopackage.org/spec/#extension_metadata', 'read-write');
"""


def write_layers(
    layers: Iterable[VectorLayer],
    dest: Path,
    *,
    metadata: Mapping[str, Any],
) -> Path:
    """``layers`` を ``dest`` に GeoPackage として書き出し、メタデータを埋め込む。

    複数レイヤがある場合は append=True で追記する。空イテレータは ValueError。
    """
    layer_list = list(layers)
    if not layer_list:
        raise ValueError("書き出すレイヤが 0 件")

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        # 同名ファイルが残っているとレイヤが古い構成のまま追記され矛盾する
        dest.unlink()

    for index, layer in enumerate(layer_list):
        pyogrio.write_dataframe(
            layer.gdf,
            dest,
            driver="GPKG",
            layer=layer.layer_name,
            append=index > 0,
        )

    _embed_dataset_metadata(dest, metadata)
    return dest


def _embed_dataset_metadata(gpkg_path: Path, metadata: Mapping[str, Any]) -> None:
    """``gpkg_metadata`` テーブルに JSON メタデータを 1 行追加する (dataset スコープ)。"""
    payload = json.dumps(metadata, ensure_ascii=False, indent=2, default=str)
    with sqlite3.connect(gpkg_path) as conn:
        conn.executescript(_METADATA_TABLES_SQL)
        conn.executescript(_EXTENSIONS_REGISTER_SQL)
        cursor = conn.execute(
            "INSERT INTO gpkg_metadata (md_scope, md_standard_uri, mime_type, metadata)"
            " VALUES (?, ?, ?, ?)",
            ("dataset", "https://github.com/jumboly/ksj", "application/json", payload),
        )
        md_file_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO gpkg_metadata_reference"
            " (reference_scope, table_name, column_name, row_id_value, md_file_id)"
            " VALUES (?, NULL, NULL, NULL, ?)",
            ("geopackage", md_file_id),
        )
        conn.commit()
