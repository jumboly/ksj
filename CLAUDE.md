# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

国土数値情報 (KSJ, 国土交通省) のカタログ管理・ダウンロード・統合を行う CLI ツール。分割配布 (都道府県・メッシュ・圏域) のデータを全国相当に結合し、CRS 統一・属性正規化した GeoPackage / GeoParquet として出力することが目的。

詳細仕様は `docs/` 以下を参照する。索引は [`docs/README.md`](docs/README.md)、個別トピックは `docs/catalog.md` / `docs/cli.md` / `docs/integration.md` / `docs/architecture.md` / `docs/roadmap.md` / `docs/risks.md`。実装は `docs/roadmap.md` の Phase 0 から順次進め、各フェーズ終了時点でユーザーの動作確認を経てから次へ進む運用。

## 現在の進捗

| フェーズ | 状態 |
|---|---|
| Phase 0: プロジェクト土台 | ✅ 完了 |
| Phase 1: カタログ雛形 + list/info | ✅ 完了 |
| Phase 2: カタログスクレイパ (catalog refresh) | 🔧 作業中 |
| Phase 3: ダウンローダ (download / ingest-local) | 未着手 |
| Phase 4: 統合パイプライン (national のみ) | 未着手 |
| Phase 5: 分割統合 (prefecture / mesh / urban_area / regional_bureau) | 未着手 |
| Phase 6: GeoParquet + convert | 未着手 |
| Phase 7: MVP 5 データセット E2E + ドキュメント | 未着手 |

**更新ルール**: Claude は各フェーズ開始時に該当行を「🔧 作業中」に、完了（ユーザー動作確認 OK）で「✅ 完了」に更新する。先取りで複数行を進めない。

**用語のエイリアス**: 「step N」「ステップ N」「フェーズ N」「phase N」はいずれも上表の Phase N と同一指示として解釈する。

## 開発コマンド

uv プロジェクトとして構成。すべて `uv run` 経由で実行:

```bash
uv sync                         # 依存解決・仮想環境作成
uv run ksj --help               # CLI のヘルプ
uv run ksj <subcommand>         # サブコマンド実行 (python -m ksj でも同等)

uv run ruff check               # lint
uv run ruff format              # format
uv run mypy                     # 型チェック (strict モード)
uv run pytest                   # 全テスト
uv run pytest tests/test_foo.py::test_bar   # 単一テスト
uv run pytest -k "name"         # 名前一致テスト
```

依存パッケージを追加するときは `uv add <pkg>` (本体) / `uv add --group dev <pkg>` (dev) を使い、`pyproject.toml` と `uv.lock` を同期する。

## アーキテクチャの全体像

`src/ksj/` 配下を以下のレイヤで構成する (段階的に追加中):

- `cli.py` — typer のサブコマンド定義。Typer は単一コマンドを root にマージする挙動があるため、空の `@app.callback()` を置いて常にサブコマンド構造を保つ
- `catalog/` — pydantic でスキーマ化したデータセットカタログ、YAML ローダー、KSJ サイトからの再スクレイパ
- `downloader/` — httpx 非同期でホスト別レート制限・Range レジューム対応の ZIP 取得
- `reader/` — pyogrio 経由で Shp/GML/GeoJSON を同一 I/F で読み込み、エンコーディング判定も担う
- `integrator/` — CRS 変換・スキーマ統一・分割結合のパイプライン。`source_selector.py` が「national があれば national のみ、無ければ識別子ごとに最新年度を選んで union」のルールで入力ファイルを決定する
- `writer/` — GeoPackage / GeoParquet 書出。出典・ライセンス・生成日等のメタデータを埋め込む

カタログ本体は `catalog/datasets.yaml` (将来追加) にコミットし、KSJ 全 131 データセット分の実 URL・CRS・形式を列挙する。

## 重要な設計ルール

- **データ形式 (GML/Shp/GeoJSON/CityGML/CSV/GeoTIFF) はファイル名サフィックスから推測しない**。必ず KSJ 詳細ページ HTML の「形式」列から抽出し、`format` (正規化値) と `format_raw` (HTML 原文) の両方を保持する。測地系 (CRS) も同様で、ファイル名中の `-tky` / `-jgd` / `-jgd2011` は根拠にせず、HTML の「測地系」列を正とする
- **URL はテンプレート化せず実値を列挙**する。KSJ のダウンロード URL はデータセット間でパターンが不規則 (別ホスト `www.gsi.go.jp` 有、サブディレクトリ有無、年号表記 YYYYMMDD / YY 混在、圏域コード SYUTO/CHUBU/KINKI 等)
- scope 語彙は `national` / `region` / `regional_bureau` / `prefecture` / `urban_area` / `river` / `municipality` / `mesh1〜mesh6` / `special` の 14 種類。メッシュは日本標準の 1〜6 次 (80km/10km/1km/500m/250m/100m)
- 統合時のデフォルト目標 CRS は JGD2011 (EPSG:6668)。`--target-crs` で切替可能
- 統合ルールは 2 本道: (1) national scope のファイルがあればそれを採用して終了、(2) 無ければ識別子 (pref_code / mesh_code / bureau_code / urban_area_code 等) ごとに「対象年度以前で最新」を 1 件ずつ選んで union する。これにより本州 46 県が 2018 版で沖縄のみ 2015 版、のようなケースでも沖縄を落とさず取り込める。出力メタの `coverage_summary` に識別子別の実績と補填状況を残す。年度を厳密一致させたい場合は `--strict-year` を指定する

## 運用上の取り決め

- 実装は `docs/roadmap.md` の Phase 0〜7 の順で段階的に進める。各フェーズ完了時にユーザーが動作確認コマンドを実行、OK 判定後に次フェーズへ進む。複数フェーズを先取りで進めない。進捗は本ファイルの「現在の進捗」表で管理する
- 使い捨てスクリプトは `.scratch/` に置き (gitignore 済み)、本体の依存に混ぜない。Python の場合は `.scratch/python/` で `uv run --with <pkg>` を使う
- コードコメントは「なぜそうするのか (Why)」のみ記述。自明な What は書かない
- 選択肢をユーザーに提示するときは各肢に `1.` / `2.` 等の項番を付与する
