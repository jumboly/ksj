# ksj

国土数値情報 (KSJ, 国土交通省) のカタログ管理・ダウンロード・統合を行う CLI ツール。分割配布されたデータ (都道府県・メッシュ・圏域) を全国相当に結合し、CRS 統一・属性正規化した GeoPackage / GeoParquet として出力する。

## クイックスタート

uv と GDAL (geopandas / pyogrio が依存) が入っている前提。

```bash
uv sync                                         # 依存解決と仮想環境作成
uv run ksj list                                 # 同梱カタログのデータセット一覧
uv run ksj info N03                             # データセット詳細 (年度別 scope/CRS/形式)
uv run ksj download N03 --year 2025             # KSJ サイトから ZIP 取得 (約 400MB)
uv run ksj integrate N03 --year 2025            # data/integrated/N03-2025.gpkg を生成
uv run ksj convert data/integrated/N03-2025.gpkg --format parquet
```

`download` は Range レジューム対応・ホスト別レート制限付きの並列ダウンロード。`integrate` は CRS を JGD2011 (EPSG:6668) に統一し、出典・ライセンス・カバレッジを GeoPackage の `gpkg_metadata` テーブル / GeoParquet の `key_value_metadata` に埋め込む。

### 分割データセットの統合

メッシュや都道府県分割で配布されているデータも 1 コマンドで全国相当に結合できる。

```bash
uv run ksj download L03-a --year 2021 --parallel 4    # 数百メッシュを並列取得
uv run ksj integrate L03-a --year 2021                # data/integrated/L03-a-2021.gpkg
```

整備済み年度が混在する場合 (本州 46 県が 2018 版、沖縄のみ 2015 版など) は `--year 2018` を指定すれば未整備の県のみ過去年度から自動補填される。年度を厳密一致させたいときは `--strict-year`、未取得ソースをスキップして続行したいときは `--allow-partial` を付ける。

旧測地系 (Tokyo Datum, EPSG:4301) のデータは `pyproj` 標準変換で JGD2011 に変換し、その旨を WARNING で通知する (数 m 精度の誤差あり)。

## ドキュメント

- [`docs/README.md`](docs/README.md) — 仕様書の索引と前提決定事項
- [`docs/catalog.md`](docs/catalog.md) — カタログ設計 (scope / CRS / format 語彙、YAML スキーマ)
- [`docs/cli.md`](docs/cli.md) — CLI コマンド体系
- [`docs/integration.md`](docs/integration.md) — 統合パイプライン、ソース選択アルゴリズム
- [`docs/architecture.md`](docs/architecture.md) — モジュール構成、依存ライブラリ
- [`docs/roadmap.md`](docs/roadmap.md) — 段階的実装計画 (Phase 0〜7)
- [`docs/risks.md`](docs/risks.md) — リスクと対処
- [`CHANGELOG.md`](CHANGELOG.md) — リリース履歴

## 開発

```bash
uv sync                 # 依存解決
uv run ksj --help       # CLI ヘルプ
uv run pytest           # テスト
uv run ruff check       # lint
uv run mypy             # 型チェック
```

## ライセンス

MIT License — 詳細は [`LICENSE`](LICENSE) を参照。
