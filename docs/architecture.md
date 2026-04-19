# アーキテクチャ

## モジュール構成

```
src/ksj/
  __init__.py              # __version__ を公開
  __main__.py              # python -m ksj エントリポイント
  cli.py                   # typer サブコマンド定義
  html_cache.py            # KSJ 詳細ページのローカルキャッシュ (refresh の入力)
  catalog/
    __init__.py
    schema.py              # pydantic モデル: Catalog / Dataset / Version / FileEntry
    loader.py              # YAML 読込・検証
    refresh.py             # ksj catalog refresh: HTML スクレイパ (BeautifulSoup)
    parser.py              # 詳細ページの thead/tbody パーサ
    normalizers.py         # CRS / format / scope の正規化テーブル
  downloader/
    __init__.py
    client.py              # httpx.AsyncClient + ホスト別レート制限 + Range レジューム
    manifest.py            # data/manifest.json: URL, サイズ, 取得日時, scope/format 等
    selector.py            # download コマンドのカタログ → DownloadTarget 変換
  reader/
    __init__.py
    vector.py              # pyogrio.read_dataframe ラッパ。Shp/GML/GeoJSON を同一 I/F、cp932 既定
  integrator/
    __init__.py
    pipeline.py            # 読込→CRS変換→スキーマ統一→結合→書出
    schema_unify.py        # カラム型・順序の統一、欠損カラム補完、null_values の NaN 化
    source_selector.py     # files[] から national / latest-fill / strict-year で最適なセットを選ぶ
  writer/
    __init__.py
    geopackage.py          # pyogrio で .gpkg 書出、gpkg_metadata に出典 JSON 埋込
catalog/                   # プロジェクトルート直下 (パッケージ外)
  datasets.yaml            # 同梱カタログ (ソース・オブ・トゥルース)
```

## レイヤの責務

| レイヤ | 責務 | 外部依存 |
|---|---|---|
| `cli` | 引数解析、サブコマンド分岐、rich 表示 | typer, rich |
| `catalog` | データセットメタ・URL・CRS・形式の管理と再スクレイプ | pydantic, pyyaml, beautifulsoup4, lxml, httpx |
| `downloader` | 非同期ダウンロード、レート制限、レジューム、マニフェスト記録 | httpx, tenacity |
| `reader` | Shp/GML/GeoJSON をデータフレームとして読み込む。Shapefile は cp932 既定、GML/GeoJSON は pyogrio デフォルト | pyogrio, geopandas |
| `integrator` | CRS 変換・スキーマ統一・結合 | pyproj, geopandas, shapely |
| `writer` | GeoPackage 書出、メタデータ埋込 | pyogrio |

## CLI 設計の注意点

- Typer は単一コマンドのみ登録されている場合、それを root にマージして単純な CLI にする挙動がある。常にサブコマンド構造を維持するため、空の `@app.callback()` を置く
- `ksj --help` 実行時に `no_args_is_help=True` で自動的にヘルプを表示させる

## 依存ライブラリ

### 本体依存

- **typer, rich** — CLI と UX (rich は typer 経由で entry。テーブル / 進捗バー / ログハンドラを直接利用)
- **httpx, tenacity** — 並列 DL・リトライ
- **beautifulsoup4, lxml** — カタログ refresh (HTML パース)
- **pyogrio, geopandas, shapely** — Shapefile/GML/GeoJSON/GPKG の読書
- **pyproj** — CRS 変換
- **pydantic** — カタログ・マニフェストのスキーマ検証
- **pyyaml** — カタログ YAML

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
    ├── integrated/<code>-<year>.gpkg
    ├── html_cache/             KSJ 詳細ページのキャッシュ
    └── manifest.json            取得 URL・サイズ・取得日時の記録
```

reader は ZIP を `vsizip://` で直接読むため、展開済みファイルを置く中間ディレクトリ (extracted/) は持たない。

## エラーハンドリングと検証

- カタログ YAML の不整合は pydantic で起動時に検出
- `catalog refresh` の異常検知: (1) 各詳細ページから URL が最低 1 件取れない、(2) データセット数が前回比 -10% 以上、等のヒューリスティックで警告
- 統合前に `data/raw/<code>/<year>/` に全分割が揃っているか事前チェック、不足なら自動ダウンロードまたはエラー
- `refresh` 中断時は `catalog/.refresh_state.json` に進捗を記録、次回は再開可能

## メモリ効率

大規模メッシュデータ (mesh250r6 は SHP 756MB / GML 1.9GB 等) への対処:

- 分割を逐次読込み、レイヤ単位の `append` で GeoPackage に書き出す形でストリーミング結合
- pandas 上で一気に concat しない
- `integrator/pipeline.py` でストリーミング結合を実装
