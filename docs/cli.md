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
  KSJ サイトをスクレイピングしてカタログ YAML を再生成する。
  - --only <code> : 単一データセットのみ更新
  - --parallel N  : 同時接続数 (デフォルト 2)
  - --rate N      : 秒間リクエスト数の上限 (デフォルト 1)

ksj catalog diff
  現在のカタログ YAML と再スクレイプ結果の差分を表示する (コミット前レビュー用)。
```

### ダウンロード

```
ksj download <code> --year YYYY
             [--format-preference shp,gml,geojson]
             [--crs EPSG_CODE]
             [--data-dir PATH]
             [--parallel N]
             [--rate LIMIT]
  指定データセット・年度の ZIP を取得する。並列・レート制限・Range レジューム対応。
  - --format-preference : 複数形式が並列配布されているとき選ぶ優先順
  - --crs EPSG_CODE     : 年度内で複数測地系がある場合のフィルタ

ksj ingest-local <code> --year YYYY --from PATH
  既存のローカル ZIP を取り込む (オフラインテストや別経路で取得したデータ用)。
```

### 統合・変換

```
ksj integrate <code> --year YYYY
              [--target-crs EPSG:6668]
              [--format gpkg|parquet]
              [--format-preference shp,gml]
              [--allow-partial]
              [--out PATH]
  分割データを結合し CRS 統一・属性正規化して出力する。
  - --target-crs      : 統合後の CRS (デフォルト EPSG:6668 = JGD2011)
  - --format          : 出力形式 (デフォルト gpkg)
  - --format-preference: 入力形式の優先順
  - --allow-partial   : urban_area 等、全国未カバーのデータでも続行

ksj convert <input> --format gpkg|parquet [--out PATH]
  統合済みファイルの形式を変換する (GeoPackage ⇄ GeoParquet)。
```

## グローバルオプション

```
--data-dir PATH        データ格納ルート (デフォルト ./data)
--help / -h           ヘルプ表示
```

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
│   ├── datasets.yaml           スクレイプ結果のスナップショット
│   └── .refresh_state.json     refresh 中断時の再開用状態
└── data/                       (gitignore)
    ├── raw/<code>/<year>/*.zip
    ├── extracted/<code>/<year>/...
    ├── integrated/<code>-<year>.gpkg
    └── manifest.json           取得 URL・サイズ・取得日時の記録
```
