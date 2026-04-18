# アーキテクチャ

## モジュール構成

```
src/ksj/
  __init__.py              # __version__ を公開
  __main__.py              # python -m ksj エントリポイント
  cli.py                   # typer サブコマンド定義
  config.py                # --data-dir 等の設定、pydantic-settings
  catalog/
    __init__.py
    schema.py              # pydantic モデル: Dataset / Version / FileEntry
    loader.py              # YAML 読込・検証
    refresh.py             # ksj catalog refresh: HTML スクレイパ (BeautifulSoup)
  downloader/
    __init__.py
    client.py              # httpx.AsyncClient + ホスト別レート制限 + Range レジューム
    manifest.py            # data/manifest.json: URL, サイズ, 取得日時, zip 内ファイル一覧
  reader/
    __init__.py
    vector.py              # pyogrio.read_dataframe ラッパ。Shp/GML/GeoJSON を同一 I/F
    encoding.py            # Shift_JIS/UTF-8 判定、DBF エンコーディング指定
  integrator/
    __init__.py
    pipeline.py            # 読込→CRS変換→スキーマ統一→結合→書出
    schema_unify.py        # カラム型・順序の統一、欠損カラム補完
    source_selector.py     # files[] から scope/CRS/format 優先度で最適なセットを選ぶ
  writer/
    __init__.py
    geopackage.py          # pyogrio で .gpkg 書出、gpkg_metadata に出典埋込
    parquet.py             # pyogrio/geoarrow で .parquet 書出、key_value_metadata に出典埋込
  catalog_data/
    datasets.yaml          # 同梱カタログ (ソース・オブ・トゥルース)
    code_tables/           # 将来: 行政区域コード等の辞書
```

## レイヤの責務

| レイヤ | 責務 | 外部依存 |
|---|---|---|
| `cli` | 引数解析、サブコマンド分岐、rich 表示 | typer, rich |
| `catalog` | データセットメタ・URL・CRS・形式の管理と再スクレイプ | pydantic, pyyaml, beautifulsoup4, lxml, httpx |
| `downloader` | 非同期ダウンロード、レート制限、レジューム、マニフェスト記録 | httpx, tenacity |
| `reader` | Shp/GML/GeoJSON をデータフレームとして読み込む、エンコーディング自動判定 | pyogrio, cchardet |
| `integrator` | CRS 変換・スキーマ統一・結合 | pyproj, shapely, pyarrow |
| `writer` | GeoPackage / GeoParquet 書出、メタデータ埋込 | pyogrio, pyarrow |

## CLI 設計の注意点

- Typer は単一コマンドのみ登録されている場合、それを root にマージして単純な CLI にする挙動がある。常にサブコマンド構造を維持するため、空の `@app.callback()` を置く
- `ksj --help` 実行時に `no_args_is_help=True` で自動的にヘルプを表示させる

## 依存ライブラリ

### 本体依存

- **typer, rich** — CLI と UX
- **httpx[http2], tenacity** — 並列 DL・リトライ
- **beautifulsoup4, lxml** — カタログ refresh (HTML パース)
- **pyogrio** (GDAL ラッパ) — Shapefile/GML/GeoJSON/GPKG/GeoParquet の読書
- **pyproj** — CRS 変換
- **shapely** — 必要に応じた幾何操作
- **pyarrow** — GeoParquet メタデータ操作
- **pydantic, pydantic-settings** — カタログ検証・設定
- **pyyaml** — カタログ YAML
- **cchardet** (or chardetng) — エンコーディング判定

### 開発依存

- **pytest, pytest-asyncio** — テスト
- **ruff** — lint + format
- **mypy** — 型チェック (strict モード)

## ディレクトリ規約

```
./                              プロジェクトルート (working dir)
├── pyproject.toml
├── uv.lock
├── .gitignore                  data/ を除外
├── .scratch/                   使い捨てスクリプト (ユーザー CLAUDE.md 規約)
├── src/ksj/
├── tests/
├── catalog/datasets.yaml
├── docs/                       本ディレクトリ (仕様書)
└── data/                       (gitignore)
    ├── raw/<code>/<year>/*.zip
    ├── extracted/<code>/<year>/...
    └── integrated/<code>-<year>.gpkg
```

## エラーハンドリングと検証

- カタログ YAML の不整合は pydantic で起動時に検出
- `catalog refresh` の異常検知: (1) 各詳細ページから URL が最低 1 件取れない、(2) データセット数が前回比 -10% 以上、等のヒューリスティックで警告
- 統合前に `data/raw/<code>/<year>/` に全分割が揃っているか事前チェック、不足なら自動ダウンロードまたはエラー
- `refresh` 中断時は `catalog/.refresh_state.json` に進捗を記録、次回は再開可能

## メモリ効率

大規模メッシュデータ (mesh250r6 は SHP 756MB / GML 1.9GB 等) への対処:

- 分割を逐次読込み、`pyarrow.RecordBatch` ストリームに追記していく形で書出
- pandas 上で一気に concat しない
- `integrator/pipeline.py` でストリーミング結合を実装
