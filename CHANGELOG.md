# Changelog

本プロジェクトの主要な変更点を記録する。フォーマットは [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に準拠し、バージョン管理は [Semantic Versioning](https://semver.org/lang/ja/) に従う。

## [Unreleased]

## [0.1.0] - 2026-04-18

初回リリース。MVP として N03 (行政区域) / L03-a (土地利用細分メッシュ、2021 + 1976 旧測地系) / A03 (三大都市圏計画区域) / A53 (医療圏) の 5 件で end-to-end 動作を検証済み。

### Added

- **CLI**: `ksj list` / `info` / `download` / `ingest-local` / `integrate` / `convert` / `catalog refresh` / `catalog diff` / `html fetch` / `html list` / `version`
- **カタログ管理**: pydantic ベースのスキーマ (Catalog / Dataset / Version / FileEntry) と YAML ローダ。`ksj catalog refresh` で KSJ サイトをスクレイプし `catalog/datasets.yaml` を再生成、`ksj catalog diff` で差分確認
- **HTML キャッシュ**: KSJ 詳細ページをローカル保存し、catalog refresh をオフラインで反復可能に
- **ダウンローダ**: httpx 非同期、ホスト別レート制限・並列取得、Range レジューム、`data/manifest.json` での状態管理
- **統合パイプライン**: national 1 本採用 / scope + 識別子バケットでの latest-fill / 年度厳密一致 (`--strict-year`) / 部分カバレッジ許容 (`--allow-partial`) の 3 戦略。CRS 統一 (デフォルト JGD2011 / EPSG:6668)、旧測地系 (Tokyo Datum) からの変換 WARNING、欠損値コードの NaN 正規化、複数ソースの単一レイヤ結合
- **対応 scope**: national / region / regional_bureau / prefecture / urban_area / mesh1〜mesh6
- **出力形式**: GeoPackage (OGC Metadata Extension に出典・カバレッジを JSON 埋込) と GeoParquet 1.1 (`key_value_metadata` の `ksj_metadata` キーに同等 JSON 埋込)。`ksj convert` で GPKG ⇄ Parquet の相互変換 (メタデータ保全)
- **テスト**: 単体・統合 134 関数 / 約 2,140 行、CLI smoke 5 ケース (national / mesh / 旧測地系 / urban_area / regional_bureau)。pytest / ruff / mypy strict / uv ベースの開発環境
- **ドキュメント**: `docs/` に仕様書一式 (catalog / cli / integration / architecture / roadmap / risks)、ルート README にクイックスタート

### 既知の制限

- TKY2JGD / PatchJGD グリッドによる高精度測地系変換は未対応 (pyproj 標準変換のみ。数 m 精度誤差)
- ラスタデータ (L03-b_r) の統合は対象外
- CSV 専有データ (L01 / L02 地価公示) の座標フィールド解釈は将来フェーズ
- メッシュ境界における重複ポリゴンのマージ・トポロジ修正は行わない

[Unreleased]: https://example.com/unreleased
[0.1.0]: https://example.com/v0.1.0
