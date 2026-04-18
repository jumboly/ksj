# CLI コマンド体系

`ksj` は typer ベースのサブコマンド型 CLI。すべて `uv run ksj <subcommand>` または `python -m ksj <subcommand>` で実行可能。

## コマンド一覧

### カタログ照会

```
ksj list [--category CAT] [--scope SCOPE]
  カタログ一覧を rich Table で表示する。カテゴリ・scope でフィルタ可能。

ksj info <code>
  1 データセットの詳細を表示する。年度別の scope 分布、CRS、形式を一覧化する。
```

### カタログ管理

```
ksj catalog refresh [--only <code>] [--parallel 2] [--rate 1]
                    [--dry-run] [--no-cache] [--cache-dir PATH]
  KSJ サイトをスクレイピングしてカタログ YAML を再生成する。
  - --only <code> : 単一データセットのみ更新 (複数指定可)
  - --parallel N  : 同時接続数 (デフォルト 2)
  - --rate N      : 秒間リクエスト数の上限 (デフォルト 1)
  - --dry-run     : YAML を上書きせずサマリのみ表示
  - --no-cache    : HTML キャッシュを無視して再取得 (取得結果はキャッシュに上書き)
  - --cache-dir   : HTML キャッシュディレクトリ (デフォルト data/html_cache)

ksj catalog diff
  現在のカタログ YAML と再スクレイプ結果の差分を表示する (コミット前レビュー用)。
```

### HTML キャッシュ管理 (補助)

```
ksj html fetch [--only <code>] [--parallel 2] [--rate 1] [--force] [--cache-dir PATH]
  KSJ サイトの HTML を cache_dir に保存する (カタログ YAML は更新しない)。
  catalog refresh は保存された HTML をそのまま使うので、初回実行後はオフライン
  でカタログ再生成できる。

ksj html list [--cache-dir PATH]
  HTML キャッシュの内容を一覧表示する。
```

### ダウンロード

```
ksj download <code> --year YYYY
             [--format-preference shp,gml,geojson]
             [--crs EPSG_CODE]
             [--scope VALUE] [--prefer-national]
             [--data-dir PATH]
             [--parallel N]
             [--rate LIMIT]
  指定データセット・年度の ZIP を取得する。並列・レート制限・Range レジューム対応。
  - --format-preference : 複数形式が並列配布されているとき選ぶ優先順
  - --crs EPSG_CODE     : 年度内で複数測地系がある場合のフィルタ
  - --scope VALUE       : 指定 scope のみ取得 (複数指定可。例: --scope national --scope region)。
                          語彙は catalog schema の Scope と同じ (national / prefecture / mesh1..6 等)
  - --prefer-national   : national があれば national のみ、無ければ全 scope を取得
                          (integrate の national 優先戦略と同等)。--scope と同時指定不可

ksj ingest-local <code> --year YYYY --from PATH
  既存のローカル ZIP を取り込む (オフラインテストや別経路で取得したデータ用)。
```

### 統合・変換

```
ksj integrate <code> --year YYYY
              [--target-crs EPSG:6668]
              [--format gpkg|parquet]
              [--format-preference gml,shp,geojson]
              [--strict-year] [--allow-partial]
              [--data-dir PATH] [--out PATH]
  分割データを結合し CRS 統一・属性正規化して出力する。
  - --target-crs       : 統合後の CRS (デフォルト EPSG:6668 = JGD2011)
  - --format           : 出力形式 (デフォルト gpkg)
  - --format-preference: ZIP 内に複数形式が同梱されているとき採用する優先順 (デフォルトは gml > shp > geojson)
  - --strict-year      : 対象年度に完全一致する識別子のみ採用。デフォルトは最新補填あり
                         (例: 本州 46 県 2018、沖縄のみ 2015 も取り込む)
  - --allow-partial    : manifest に無いソースをスキップして続行する (警告のみ)
  - --data-dir         : データ格納ルート (デフォルト ./data)
  - --out              : 出力先パス (デフォルト data_dir/integrated/{code}-{year}.{ext})

ksj convert <input> --format gpkg|parquet [--out PATH]
  統合済みファイルの形式を変換する (GeoPackage ⇄ GeoParquet)。メタデータは保全される。
  入力と同じ形式を指定するとエラーになる。
```

## 補助コマンド

```
ksj version       バージョン番号を表示
ksj --help        ヘルプ表示 (各サブコマンドにも --help あり)
```

`--data-dir` はサブコマンドごとのオプションとして提供 (CLI レベルのグローバル ではない)。`download` / `ingest-local` / `integrate` の各コマンドで指定可能。

## ディレクトリ規約

```
./                              プロジェクトルート (working dir)
├── pyproject.toml
├── uv.lock
├── .gitignore                  data/ を除外
├── .scratch/                   使い捨てスクリプト (gitignore)
├── src/ksj/                    実装
├── tests/                      テスト
├── catalog/
│   └── datasets.yaml           スクレイプ結果のスナップショット
└── data/                       (gitignore)
    ├── raw/<code>/<year>/*.zip
    ├── integrated/<code>-<year>.gpkg
    ├── html_cache/             KSJ 詳細ページのキャッシュ
    └── manifest.json           取得 URL・サイズ・取得日時の記録
```

reader は ZIP を `vsizip://` で直接読むため、展開済みファイルを置く中間ディレクトリ (extracted/) は持たない。
