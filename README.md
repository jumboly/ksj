# ksj

国土数値情報 (KSJ, 国土交通省) のカタログ管理・ダウンロード・統合を行う CLI ツール。分割配布されたデータ (都道府県・メッシュ・圏域) を全国相当に結合し、CRS 統一・属性正規化した GeoPackage / GeoParquet として出力する。

## 状況

開発中。フェーズ別の進捗は [`CLAUDE.md`](CLAUDE.md) の「現在の進捗」表で管理。各フェーズの成果物・動作確認手順は [`docs/roadmap.md`](docs/roadmap.md) を参照。

## ドキュメント

- [`docs/README.md`](docs/README.md) — 仕様書の索引と前提決定事項
- [`docs/catalog.md`](docs/catalog.md) — カタログ設計 (scope / CRS / format 語彙、YAML スキーマ)
- [`docs/cli.md`](docs/cli.md) — CLI コマンド体系
- [`docs/integration.md`](docs/integration.md) — 統合パイプライン、ソース選択アルゴリズム
- [`docs/architecture.md`](docs/architecture.md) — モジュール構成、依存ライブラリ
- [`docs/roadmap.md`](docs/roadmap.md) — 段階的実装計画 (Phase 0〜7)
- [`docs/risks.md`](docs/risks.md) — リスクと対処

## 開発

```bash
uv sync                 # 依存解決
uv run ksj --help       # CLI ヘルプ
uv run pytest           # テスト
uv run ruff check       # lint
uv run mypy             # 型チェック
```
