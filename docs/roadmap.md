# ロードマップ / 段階的実装計画

## 進め方

各フェーズ終了時点で、動作確認手順をユーザーが実行し、OK 判定後に次フェーズへ進む。フェーズ間での設計見直し・軌道修正を許容する。各フェーズは 1 PR (または 1 コミット単位) で区切る。

---

## Phase 0: プロジェクト土台

**成果物**:
- `pyproject.toml` (uv project, Python 3.12+)
- `src/ksj/__init__.py` / `__main__.py` / `cli.py` (typer スケルトン)
- `ruff` / `mypy` / `pytest` の設定
- `.gitignore` (data/ と .scratch/ を除外)
- `uv.lock`

**動作確認**:
```bash
uv sync
uv run python -m ksj --help   # サブコマンド構造
uv run ksj version            # バージョン表示
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest
```

---

## Phase 1: カタログ雛形 + list/info

**成果物**:
- `src/ksj/catalog/schema.py` — pydantic モデル (Dataset, Version, FileEntry)
- `src/ksj/catalog/loader.py`
- `catalog/datasets.yaml` — **手書きで 3〜5 件** (N03, A03, L03-a, A53, G04-a 等)
- `src/ksj/cli.py` — `ksj list` / `ksj info <code>` (typer + rich)
- 単体テスト: スキーマ検証、ローダー

**動作確認**:
```bash
uv run ksj list                       # rich Table で 3-5 件表示
uv run ksj list --scope prefecture    # prefecture を含むデータセットのみ
uv run ksj info N03                   # 年度別 scope/CRS/形式の分布
uv run ksj info UNKNOWN               # エラーメッセージが分かりやすい
uv run pytest
```

---

## Phase 2: カタログスクレイパ (catalog refresh)

**成果物**:
- `src/ksj/catalog/refresh.py` — KSJ トップ + 各詳細ページのスクレイパ (BeautifulSoup)
- HTML の「形式」列・「測地系」列から format/CRS を抽出 (filename 非使用)
- `ksj catalog refresh [--only <code>] [--parallel 2] [--rate 1]`
- `ksj catalog diff`
- 進捗状態ファイル `catalog/.refresh_state.json` で再開可能
- テスト: HTML フィクスチャ (N03, L03-b, A03, G04-a, A55) でパーサ検証

**動作確認**:
```bash
uv run ksj catalog refresh --only N03 --dry-run     # 抽出結果をプレビュー
uv run ksj catalog refresh --only N03                # catalog/datasets.yaml に書き込み
uv run ksj catalog diff                              # 既存との差分表示
uv run ksj catalog refresh                           # 全件 (~2.5 分)
uv run ksj info A55                                  # CityGML が検出される
uv run ksj info mesh1000h30                          # WGS84 が検出される
```

カタログ全件 (131 件程度) の目視確認・コミット承認が完了してから次へ。

---

## Phase 3: ダウンローダ (download / ingest-local)

**成果物**:
- `src/ksj/downloader/client.py` — httpx.AsyncClient、ホスト別レート制限、Range レジューム
- `src/ksj/downloader/manifest.py` — `data/manifest.json`
- `ksj download <code> --year YYYY [--format-preference ...] [--parallel N]`
- `ksj ingest-local <code> --year YYYY --from PATH`

**動作確認**:
```bash
uv run ksj download N03 --year 2025                  # national 1 ファイル、~400MB
uv run ksj download A03 --year 2003                  # urban_area 3 ファイル、~27MB
uv run ksj download L03-a --year 2021 --parallel 4   # メッシュ多数、並列動作
# Ctrl-C で中断後、再実行でレジュームが効くこと
ls data/raw/
cat data/manifest.json | jq
```

---

## Phase 4: 統合パイプライン (national のみ)

**成果物**:
- `src/ksj/reader/vector.py` + `encoding.py`
- `src/ksj/integrator/pipeline.py` — national scope のみ対応
- `src/ksj/integrator/source_selector.py`
- `src/ksj/writer/geopackage.py` — メタデータ埋込
- `ksj integrate N03 --year 2025 --target-crs EPSG:6668`

**動作確認**:
```bash
uv run ksj integrate N03 --year 2025
ls data/integrated/                                  # N03-2025.gpkg
ogrinfo -so data/integrated/N03-2025.gpkg            # CRS=6668、レイヤ情報
# QGIS で開いて全国ポリゴンが表示されること
```

---

## Phase 5: 分割統合 (prefecture / mesh / urban_area / regional_bureau)

**成果物**:
- `integrator/source_selector.py` — `SelectionPlan` / `BucketCoverage` / latest-fill
- `integrator/schema_unify.py` — スキーマ union + null_values 正規化 + source_year 付与
- `integrator/pipeline.py` — 複数ソース loop、旧測地系 WARNING、1 レイヤ concat 出力
- `reader/vector.py` — `encoding` 引数追加 (pipeline から shp→cp932 を自動指定)
- `catalog/schema.py` — `FileEntry.encoding` 追加 (optional、手動 override 用)
- `--strict-year` / `--allow-partial` CLI フラグ
- CRS 変換 (pyproj): JGD2011/JGD2000/Tokyo Datum → target-crs (旧測地系のみ WARNING)
- 欠損値コードの NaN 正規化 (数値 null は数値列、文字列 null は文字列列にのみ適用)
- 出力メタデータに coverage_summary (scope 別 covered/expected/year_distribution/missing) を記録

**Phase 5 スコープ外** (意図的に切り離し):
- 自動ダウンロード (フェーズ境界を守るため。`ksj download` を促すエラー)
- GeoPackage append 書出によるストリーミング結合 (pd.concat で現行 PC メモリに収まる想定、計測で問題が出たら対応)
- DBF 254 バイト分割列の結合 (A46/A47/A48 等、Phase 7 以降)

**動作確認**:
```bash
uv run ksj integrate L03-a --year 2021               # mesh3、数百ファイル結合
uv run ksj integrate L03-a --year 1976               # 旧測地系 → JGD2011 変換 (WARNING)
uv run ksj integrate A03 --year 2003                 # urban_area
uv run ksj integrate A03 --year 2003 --allow-partial # 未取得ソースはスキップ
uv run ksj integrate A09 --year 2018 --strict-year   # 2018 年一致のみ、latest-fill 無効
uv run ksj integrate A53 --year 2024                 # regional_bureau
```

---

## Phase 6: GeoParquet + convert (撤回)

> **状態 (2026-04-19)**: 当初 GeoParquet 出力と `ksj convert` を導入したが、Phase 11/13 案で「複数 dataset / 年度違いを 1 ファイルにまとめる」要件が浮上し、Parquet の「1 ファイル = 1 テーブル」制約と相容れないため撤回。`writer/parquet.py` / `reader/integrated.py` / `ksj convert` / `--format parquet` / `pyarrow` 依存を全廃した。Parquet が必要な利用者は GeoPackage から GDAL/DuckDB 等で別途変換する。コミット履歴上の Phase 6 実装は git log から辿れる。

---

## Phase 7: MVP 5 データセット E2E + ドキュメント

**成果物**:
- E2E テスト (小データで)
- README.md に使い方記載
- CHANGELOG.md

**動作確認**:
- MVP 5 件 (N03-2025, L03-a-2021, L03-a-1976, A03-2003, A53-2024) の全フロー通し
- README の手順で初回ユーザーが実行できるか

完了 → `v0.1.0` タグ

---

## Phase 8: AI エージェント連携 - `--json` 出力モード

**状態 (2026-04-19)**: 当初案の MCP server 実装は **Phase 8+ に降格**。理由:

- 主ユースケースは「このフォルダで Claude Code を起動して `ksj` を叩く」。Bash / Read / Glob tool がそのまま使え、`--json` 対応だけで目的を満たす。
- MCP 経由では生成ファイル (MB〜GB 級 GeoPackage / ZIP) を JSON-RPC で受け渡せず path 文字列だけになる。別プロセスの Claude Desktop 等では返ったパスを自動継続処理できない。同じファイルシステムに Claude Code が居る方が自然。
- MCP は「他プロジェクトや他ツールに配る価値」が出た時点で追加する (`handlers/` 純粋関数層の設計で後付け容易にしてある)。

**成果物**:

- **`--json` / `--format json` 出力モード** (全サブコマンド):
  - 成功: `{"ok": true, "command": "...", "data": ...}` (1 行)
  - 失敗: `{"ok": false, "exit_code", "error_kind", "message"}` (1 行)
  - 契約は `docs/json-output.md` に集約、`error_kind` enum (`catalog_not_found` / `dataset_not_found` / `no_matching_files` / `download_failed` / `integrate_failed` / `invalid_argument`) を型安全に露出
  - フラグ未指定時は rich Table / spinner / Progress の従来動作を完全保持
- **`handlers/` / `renderers/` レイヤ分離**: handler が純粋関数 (dict/dataclass 返却)、renderer が rich / JSON 整形。将来の MCP / Web API 追加で再利用。
- **`ksj catalog summary` 新設**: カタログ全体メタ集計 (categories / scope_histogram / years_seen) を per-dataset なしで返す。

**動作確認**:
```bash
uv run ksj --json list | jq '.data.rows[] | select(.scopes | contains(["national"]) | not) | .code'
uv run ksj --json info A31a | jq '.data.versions | map(select(.year=="2024"))[0].files | length'
uv run ksj --json catalog summary | jq '.data.scope_histogram'
uv run ksj --json download N03 --year 2025 | jq '.data.results | length'
uv run ksj --json integrate N03 --year 2025 | jq '.data.output_path'
```

完了 → `v0.2.0` タグ判断。

---

## Phase 8+ draft: MCP server (未着手)

> **降格の経緯**: Phase 8 計画時に MCP server (`ksj mcp serve` stdio/SSE) を含めていたが、ローカル CLI の主ユースケースでは `--json` + Claude Code 直接利用で十分で、ファイル受け渡しの制約 (JSON-RPC で大きいファイルを返せない) もあり降格。他プロジェクト / 他ツール配布の要件が出た時点で着手する。

**想定成果物 (案)**:

- `src/ksj/mcp/server.py` (stdio、将来 SSE) + `tools.py` (ToolSpec: name / handler / input_model / write flag) + `schemas.py` (Scope / Format / CrsFilter enum を catalog schema から import)
- 公開 tool (副作用区分を description 冒頭の `[read-only]` / `[WRITE]` で明示):
  - read-only: `ksj_list` / `ksj_info` / `ksj_catalog_summary` / `ksj_catalog_diff`
  - write: `ksj_catalog_refresh` / `ksj_download` / `ksj_integrate`
- ハンドラ層は既に `src/ksj/handlers/` に純粋関数で揃っているので、MCP 追加は薄いアダプタで済む
- 長時間実行は progress 通知なしで完了まで待つ一括レスポンス
- `docs/agent.md` (tool 一覧 / Claude Desktop / Claude Code 接続手順 / 典型フロー)

**現時点の設計意図メモ** (将来の再着手時に参照):

- dataclass / pydantic モデルを `model_dump(mode="json")` / `asdict` でそのままシリアライズ
- `asyncio.to_thread(handler, ...)` で同期 handler を MCP event loop から呼ぶ想定 (現 handler シグネチャのまま流用)
- stdio 使用時は RichHandler を外してプレーン StreamHandler に差し替える (ANSI が client に漏れないよう)

---

## Phase 9〜13: 自然言語駆動を見据えた拡張案 (draft, 未着手)

> **位置付け**: Phase 8 の `--json` + MCP 整備で「実行系の機械化」までは達するが、「自然言語要求 → 意図解釈 → 候補選定 → 実行」を AI エージェントが回すには、データ層 (license / geometry / use_case) と操作層 (推薦・複数 code 操作・空間結合・経年並べ) で追加が要る。代表シナリオ A〜E を材料にギャップを洗い出し、Phase 9〜13 として段階化した素案。**未着手・未確定多数**。Phase 9 着手前に「主要な未確定事項」を解決する。
>
> **代表シナリオ** (この提案の根拠):
> - A: 商用可ポリゴン最新版 DL、全国版なければ都道府県マージ
> - B: 水害リスク用データを推薦、関東圏のみ抽出 → GeoPackage
> - C: L03-a の年度違いを並べた経年データを作る
> - D: バス停 500m 圏の人口を集計 (推薦 → DL → 空間結合)
> - E: 出典表示要件のみで使えるデータ一覧を CSV

### Phase 9: カタログ正規化 (情報密度の引き上げ) (実装完了 / 動作確認待ち)

**目的**: geometry / 用途タグ / description など、AI エージェントがフィルタ・推薦に使える構造化情報をカタログに揃える。ライセンスは原文保持に留める。

**実装済み成果物 (2026-04-21)**:
- `Dataset.license_raw: str | None` — KSJ 詳細ページ「使用許諾条件」欄の原文を全文保持 (truncate なし)。**構造化分類 (`LicenseProfile`) は一度導入後に撤回** (判定条件がアドホックで保守性に欠けるため。詳細は下「License 構造化の撤回経緯」)
- `Dataset.geometry_types` — `infer_geometry_types()` が name 末尾の「（ポリゴン/ポイント/ライン/ラスタ版）」から推定。111/132 件埋込、残り 21 件は「メッシュ」等でカッコ表記なし
- `Dataset.description: str | None` — 初回は Claude Code が 132 件分を人手生成して annotations.yaml に投入。将来の LLM 再生成は `.scratch/python/generate_descriptions.py` で可
- `Dataset.use_cases: list[UseCase]` — enum 11 語彙 (`administrative_boundary` / `transportation` / `disaster_risk` / `flood_risk` / `land_use` / `population` / `facility` / `terrain` / `climate` / `urban_planning` / `economy`)。132 件に 1〜3 個ずつ付与
- **annotations.yaml 分離**: scraper が description/use_cases を上書きしてしまう問題を避けるため、`catalog/annotations.yaml` に別ファイル化。loader が merge、refresh は非触。未登録 code は `RefreshSummary.annotations_missing` で warning 表示

**License 構造化の撤回経緯**:

初版では `LicenseProfile` (kind / commercial_use / attribution_required / derivative_works / constraints / by_year) を導入し、`normalize_license()` で `license_raw` を構造化していた。以下の理由で撤回し `license_raw` のみ保持する設計に戻した:

- 年度別分岐の判定条件がアドホック: 「整備年度」「作成年度」を除外、`XXXX年以降` regex、`上記以外` sentinel 等、実測文面に強く依存する規則が多く KSJ 側の文言変更で容易に崩れる
- 県別制限・「申請等必要」等の細則は自由文で書かれ機械判定できず、`constraints: list[str]` にそのまま退避していたが、結局 LLM / 人間レビューが必要で構造化の恩恵が薄い
- `_has_year_branching` / `_parse_year_branches` の silent fallback (parse 失敗時に flat 降格) は挙動が読みづらい
- KSJ 側のタイポ (「CC_B.Y_4.0」) 等の個別対応が増え続ける

採用方針: 原文を正とし、解釈は利用側 (LLM / 人間レビュー) に委ねる。Phase 10 以降で「商用可否」等の派生属性が本当に必要になったら Version 単位で手動付与を再検討する。

**修正されたコード**:
- `src/ksj/catalog/schema.py` — UseCase / Dataset 拡張 (license_raw: str | None のみ)
- `src/ksj/catalog/_normalizers.py` — infer_geometry_types 追加
- `src/ksj/catalog/_parser.py` — license_raw の 200 字制限撤廃 (原文を全文保持)
- `src/ksj/catalog/loader.py` — annotations.yaml の merge 機能、`load_annotations()` 公開
- `src/ksj/catalog/refresh.py` — geometry 正規化呼出、annotations 欠損検知、save 時の exclude
- `src/ksj/integrator/pipeline.py` — metadata の license は license_raw をそのまま埋込
- `src/ksj/handlers/info.py` + `renderers/rich_render.py` — info 表示に license_raw / geometry / use_cases / description
- `catalog/datasets.yaml` — 132 件一括マイグレーション (`.scratch/python/migrate_catalog_phase9.py` で初版、`.scratch/python/drop_license_profile.py` で LicenseProfile 撤回)
- `catalog/annotations.yaml` — 132 件分の description / use_cases 投入

**動作確認**:
```bash
uv run ksj info N03                       # license_raw: オープンデータ（CC_BY_4.0） …
uv run ksj info A09                       # license_raw: 2018年度：CC_BY_4.0 / 上記以外：非商用 …
uv run ksj info A48                       # license_raw: (空 → 表示なし)
uv run ksj --json info A09 | jq '.data.license_raw'
uv run pytest                             # 全 PASS
```

依存: なし (Phase 8 と独立)

---

### Phase 10: フィルタ拡張 (list/info の表現力) (draft)

**目的**: 自然言語要求のうち「ポリゴン」「最新版のみ」「特定 CRS」「特定用途タグ」等の制約条件を CLI / MCP で明示的に指定できるようにする。

**成果物 (案)**:
- `ksj list` に追加: `--geometry {point|line|polygon|raster}` / `--format-filter` / `--crs-filter` / `--year-min` / `--year-max` / `--latest-only` / `--use-case <tag>`
- `ksj list --format {table|csv|json}` (Phase 8 の `--json` を拡張)
- `ksj info <code> --json --year YYYY`
- フィルタロジックは `src/ksj/catalog/query.py` 新設、CLI / MCP で共有
- MCP `ksj_list` / `ksj_info` も同フィルタに連動

**license フィルタについて**: Phase 9 で LicenseProfile を撤回したため、商用可否や CC-BY の絞込は `license_raw` に対する部分一致 (`--license-contains "CC_BY"`) で最低限サポートする案、または LLM にカタログ全体を渡してフィルタさせる運用に委ねる案が候補。必要性が明確になった時点で設計を決める。

依存: Phase 9 (geometry / use_cases が無いとフィルタが空回り)

---

### Phase 11: マルチデータセット操作 / 部分抽出 / バンドル出力 (draft)

**目的**: 「複数 dataset を一括」「特定範囲だけ抽出」「最終的に 1 ファイルにまとめる」など、典型シナリオで必要になる多対操作・部分操作・バンドル化。

**成果物 (案)**:
- `ksj download` 複数 code 対応 (`--code N03=2025 --code A09=2018`)、または `ksj download-batch --plan plan.json`
- `ksj integrate-many --code N03=2025 --code A09=2018 [--bundle out.gpkg | --separate]`:
  - `--separate` (default): code ごとに別 GPKG を出力 (従来流儀)
  - `--bundle out.gpkg`: **単一 GPKG に複数レイヤ** (1 dataset = 1 layer) で書き出す。レイヤ名は `<code>_<year>` 規約。writer 層は既に multi-layer 対応 (`writer/geopackage.py:62-91` の `write_layers` で `append=True`)、pipeline 側で複数 (code, year) の結果を順に渡す薄い拡張で済む見込み
- `ksj extract <input.gpkg> --bbox / --prefectures / --where [--layer NAME] --out` — 統合済 GPKG から空間/属性で抽出。multi-layer GPKG 入力の場合 `--layer` でレイヤ指定
- 内部実装は GeoPandas のみ (軽量) か DuckDB-spatial 同梱 (大規模 OK だが依存重) か (未確定事項 3)
- MCP に `ksj_extract` / `ksj_download_batch` / `ksj_integrate_many` 追加 (部分失敗を `results: [{ok, error?}]` で返す)

**典型フロー**:
```bash
# 例 A の解: 複数 dataset を 1 ファイルに
uv run ksj integrate-many \
  --code N03=2025 --code A09=2018 --code A53=2024 \
  --bundle data/integrated/bundle.gpkg
# → 1 ファイル / 3 レイヤ (N03_2025, A09_2018, A53_2024)
```

依存: Phase 10

---

### Phase 12: 推薦と検索 (draft)

**目的**: 「水害リスクに使えるデータ」「土地利用の経年比較に向くデータ」のような自然言語意図 → 候補データセットのマッピング。

**成果物 (案)**:
- `ksj search "<query>"` — name / category / use_cases / description / notes を BM25 検索 (SQLite FTS5 / rank_bm25 のいずれか、依存軽量)
- `ksj recommend "<intent>"` — use_cases タグマッチ + BM25 ランキング。LLM 再ランクは tool 利用側に委譲
- セマンティック検索 (sentence-embeddings) は第二段階の選択肢として留める (未確定事項 4)
- MCP に `ksj_search` / `ksj_recommend` 追加。**戻り値はサーバ側でカタログ実在 code に限定**してハルシネーション防止
- `catalog/datasets.sqlite` をサイドカーに置き、`refresh` 時に同期生成する案 (起動コスト低減)

依存: Phase 9 (description / use_cases が必須)

---

### Phase 13: 経年変化 / 空間結合 / レシピ (draft)

**目的**: 例 C (経年並べ) / 例 D (空間結合) のような高レベル分析を CLI / MCP の 1 コマンドで完結。

**成果物 (案)**:
- `ksj integrate-temporal <code> --years 1976,1991,2006,2021 [--layout long|per-year-layer]`:
  - `--layout long` (default): **単一レイヤ + `source_year` 列** (long format)。年度間でスキーマがほぼ同じ前提 (L03-a 等は適合)
  - `--layout per-year-layer`: **GPKG 1 ファイル / 年度ごとに別レイヤ**。スキーマ差が大きい dataset 向け
  - メタに `versions: [...]` 配列を必ず付与
- `ksj join --left ... --right ... --op {sjoin_intersects|sjoin_within|buffer_intersect|nearest} --buffer-meters --aggregate population:sum --out` — 結果は単一レイヤ
- レシピ機能 (`ksj recipe accessibility --poi P11 --target mesh1000r6 --buffer 500 --aggregate population:sum --out report.gpkg`) — 既存 tool の宣言的組み合わせ。最終出力は 1 ファイル (中間ファイルは tmp に隔離) を default とする
- MCP に `ksj_join` / `ksj_recipe_run`

依存: Phase 11 (extract / batch / bundle)

---

### MCP tool 追加案 (Phase 11〜13 で順次)

Phase 8 の 7 tool に対して以下を追加。副作用区分は Phase 8 の read-only / write 分離方針を継承:

- `ksj_search` (read-only) — BM25 全文検索
- `ksj_recommend` (read-only) — 意図 → ランク付候補
- `ksj_extract` (write) — bbox / prefectures / where 抽出
- `ksj_download_batch` / `ksj_integrate_many` (write) — 複数 code 一括
- `ksj_join` (write) — 空間結合
- `ksj_recipe_run` (write) — 宣言的レシピ実行

### 横断的な考慮事項

- **ライセンス解釈**: `license_raw` のまま保持する方針なので、商用可否・年度別分岐の判定は LLM / 人間レビューに委ねる。必要なら `license_raw` を原文付きで LLM に渡して「このデータは商用利用可か」を問い合わせる運用を想定
- **推薦のハルシネーション**: 戻り値はカタログ実在 code に限定。`reasoning` フィールドで根拠を必ず添える。`limit` 既定 5
- **インデックス規模**: 124 dataset は SQLite FTS5 で十分。embedding 索引は必須ではない
- **transactional 性**: `ksj_integrate_many` の部分失敗時に rollback するか残すか (未確定事項 4)

### 主要な未確定事項

1. **`use_cases` タグ語彙の拡張**: 現状 enum 11 値で固定。`flood_risk` は独立タグとして分離済み。フリータグ化は拡張性より保守負担が大きいと判断 (Phase 9 で決定済み)
2. **空間結合バックエンド**: GeoPandas のみ (軽量) vs DuckDB-spatial (大規模 OK だが依存重)
3. **推薦エンジン**: BM25 のみ (依存軽量、決定的) vs sentence-embeddings 同梱 (重量、再現性低下)
4. **`integrate_many` の transactional 性**: 部分成功を残すか全 rollback するか

---

## 要調査項目

### refresh と annotations.yaml の整合 (Phase 9 暫定対応後の残課題)

**現状 (2026-04-21)**: `ksj catalog refresh` は `catalog/annotations.yaml` を一切触らない設計。refresh 完了時に `summary.annotations_missing` に「annotations に無い code」を載せ、rich/JSON 双方で warning 表示する暫定対応を入れた (`src/ksj/catalog/refresh.py:RefreshSummary.annotations_missing`)。

以下は未対応の残課題:

1. **新 code の自動 stub 追加**: KSJ サイトに新データセットが増えたとき、現状は warning のみで annotations.yaml への stub (`description: null, use_cases: []`) 追加は手動。scraper 側が annotations を書く逆流を避ける方針だが、CI/運用で気付きを強めたい場合は追加検討
2. **削除された code の孤児エントリ掃除**: datasets.yaml から消えた code が annotations.yaml に残存しても loader は無視する (merge 対象にならない) ため動作問題なし。見通し上は手動で削除するか、診断コマンド `ksj annotations prune` を検討
3. **name 変更時の description 陳腐化**: dataset.name が更新されても description は旧 name を前提にした文のまま残る。refresh の diff に name 変更 code を出すか、`ksj annotations diff` で description と name の不一致候補を表示する案
4. **description / use_cases の品質自動評価**: LLM 生成後の人手レビュー運用で現状は十分だが、use_cases が KSJ の公式分類と乖離していないか監査する仕組みは将来必要

着手基準: annotations 未整備 code が 5 件以上蓄積するか、description 陳腐化で info 出力に明確な不整合が出た時点で再評価する。

---

### `DownLd_new(...)` 変種とカタログ漏れの扱い (2026-04-21 対応完了)

**結論 (2026-04-21)**: `_DOWNLD_RE` を `DownLd(?:_new)?\(` に緩めて両方を取り込む方針で対応済み。`tests/test_parser.py::TestDownLdNewVariant` を追加、`ksj catalog refresh --only L02 --only A16` を実施し `catalog/datasets.yaml` にマージ済み。

**調査で判明した事実**:

1. **`gis.js` の現物で DownLd と DownLd_new の両関数が現役定義済み** (`2024/09/04 kita add` コメント付き `newflag` 変数で分岐)。URL 遷移挙動は両者同一 (`document.location.href = path`)、差分は DL 後の span id サフィックス `_new` のみ
2. **CSS も同一** (`materialize.css` / `style.css` / `datatables.min.css`)。崩れやメンテ放棄の兆候なし
3. **index.html からは両者とも 1 回参照**される (collapsible 内、card 一覧には無し)。ただし同じ扱いの dataset が 59 件あり (A13 / A31a / A46 / A53 / N02〜N12 / P11 等)、すべて現行カタログ正規収録。L02 / A16 だけアーカイブ扱いではない
4. **onclick 関数名の全 132 ページ列挙で検出された関数は `DownLd` と `DownLd_new` の 2 種のみ**。別変種なし
5. KSJ 側が順次 `DownLd` → `DownLd_new` へ切替中の移行過渡期。L02-2025 は全件 `DownLd_new` 化済み、A16-2020 は地方ブロック版 8 件のみ先行移行

**対応内容と結果**:

- **`src/ksj/catalog/_parser.py`**: `_DOWNLD_RE` を `DownLd(?:_new)?\(` に拡張 (経緯コメント付き)
- **`tests/test_parser.py`**: 合成 HTML で DownLd / DownLd_new 併存を検証するテストを 2 件追加 (13 件全 PASS)
- **`catalog/datasets.yaml`**: L02 が 0 → 43 年度 / 2,129 files で新規充填 (1983〜2025)。A16-2020 が 48 → 56 files (region scope 8 件追加)。他 130 件は無変更

---

### カタログの HTML 原文保存強化 (2026-04-22 洗い出し)

**目的**: カタログを「人間または LLM が扱いやすい」形に保つため、HTML 原文を残さず変換している箇所を見直す。8a5942d で LicenseProfile 撤回・scope 識別子の単一フィールド化が済んでいるが、なお原文が失われる / 推測成分が主フィールドに混入している箇所が残る。

**【高】原文が完全に捨てられている / 推測しか残らない**:

1. `Dataset.name` — KSJ 詳細ページタイトル (例「国土数値情報｜行政区域データ」) から「国土数値情報」冠と区切りを除去した値だけを保持。原文保存先なし。
   - 根拠: `src/ksj/catalog/_parser.py` の `_extract_title()` 付近、`refresh.py:137-175`
   - 対応案: `Dataset.name_raw: str | None` を追加するか、`name` を原文のままにする

2. `Version` の年度キー (文字列 YYYY) — 「平成21年」→ "2009"、「2025年4月」→ "2025" に正規化しているが、`Version` モデルに原文保存フィールドが無い。
   - 根拠: `src/ksj/catalog/_normalizers.py:149-167` (`infer_version_year`)、`schema.py:150-163` (Version に year_raw 相当なし)
   - 対応案: `Version.year_raw: str | None` を追加。`versions` dict の key は YYYY のままで lookup 互換を維持

3. `Dataset.available_formats` — ページ全体の「データフォーマット」欄原文 (例「GML形式 (JPGIS2.1) ／シェープファイル形式／GeoJSON形式」) を `[gml_jpgis2014, shp, geojson]` の enum list に変換済みで、原文保存先なし。GML 版数推測も含むため情報落ちが大きい。
   - 根拠: `schema.py:201`、`refresh.py:171-172`、`_normalizers.py:33-46`
   - 対応案: `Dataset.available_formats_raw: str | None` を追加し enum list と併存

4. `Dataset.geometry_types` — `name` 末尾の「 (ポリゴン) 」「 (ラスタ版) 」等から推定。name に原文は残るため情報損失は軽微だが、フィールド自体が LLM 運用では必須性が低い。
   - 根拠: `_normalizers.py:440-459` (`infer_geometry_types`)
   - 対応案: (1) 廃止して name から LLM に読ませる / (2) 現状維持 + annotations.yaml 補完 / (3) 原文括弧表記を別フィールドで残す、の 3 択を後日決定

**【中】推測成分を含むが `*_raw` で原文は残る**:

5. `FileEntry.crs` の JGD2000 vs JGD2011 判定 — HTML は「世界測地系」しか書かないのに filename サフィックス (`-jgd2011` / `-jgd` / `-tky` / なし) で EPSG を確定値として格納。suffix なしの既定 6668 (JGD2011) は旧年度データで誤りの可能性。
   - 根拠: `_normalizers.py:102-139` (`normalize_crs`)
   - 対応案: suffix 不明時は `crs: None` にして推測根拠の薄さを表現。`crs_raw` は既存で原文保持済み

6. `FileEntry.format` の GML 版判定 (JPGIS2.1 vs 2014) — 行単位 HTML は「GML形式」しか書かないことがあり、ページ全体の宣言 context で 2014 に寄せている。行単位の根拠が薄い。
   - 根拠: `_normalizers.py:77-90` (`classify_row_format`)
   - 対応案: 版判定できない行は `gml_jpgis21`/`gml_jpgis2014` を付けずニュートラル値にする、または `format_raw` 優先で `format` を None 許容にする

7. `FileEntry.format = "multi"` — filename `_GML.zip` + ページ宣言 formats ≥ 3 で `multi` に丸めているが、N03 等で ~85% が multi になり情報量が少ない。
   - 根拠: `_normalizers.py:49-74` (`classify_url_format`)
   - 対応案: `FileEntry.contained_formats: list[Format]` を追加、または `multi` 廃止で list 化。`available_formats_raw` (項目 3) 導入後は緊急度が下がる

**【低】現状維持で合意済み (参考)**:

`pref_code` + `pref_name` 併存、`scope` enum、`mesh_code` の DOM id fallback、`license_raw` / `crs_raw` / `format_raw` の原文保持、`annotations.yaml` 分離は既存方針どおりで変更不要。

**推奨対応の優先度** (将来着手時の目安):

1. `Version.year_raw` 追加 (影響範囲小・情報落ちが一番大きい)
2. `Dataset.available_formats_raw` 追加
3. `Dataset.name` の扱い整理 (`name_raw` 追加 or 原文化)
4. `normalize_crs` の suffix 不明時を `crs: None` に
5. `geometry_types` の去就決定
6. `format` の GML 版・`multi` 運用見直し

**着手基準**: 自然言語駆動 (Phase 10 以降) で LLM にカタログを渡して解釈させる運用が本格化したとき、原文欠落が不便になった時点で再評価する。Phase 9 の延長線上で `Version.year_raw` だけ先行実装するのはコストが小さく価値が高い。

---

## MVP 対象データセット

scope / CRS / format の組み合わせ網羅を目的に以下 5 件を MVP 対象とする:

| コード | 年度 | 主要 scope | CRS | 形式 | 検証目的 |
|---|---|---|---|---|---|
| N03 | 2025 | national + region + prefecture (同居) | JGD2011 | shp/geojson/gml | national 優先解決、複数 scope 共存、最頻出 |
| L03-a | 2021 | mesh3 × 数百 | JGD2011 | shp | 大規模メッシュ結合、3 次メッシュ |
| L03-a | 1976 | mesh3 | **Tokyo Datum** | shp | 旧測地系 → JGD2011 変換の検証 |
| A03 | 2003 | urban_area (SYUTO/CHUBU/KINKI) | Tokyo | shp/gml | partial 統合、urban_area scope |
| A53 | 2024 | regional_bureau × 8 整備局 | JGD2011 | shp/geojson | regional_bureau scope、部分カバレッジ |

**網羅範囲**:
- scope: `national`, `region`, `prefecture`, `urban_area`, `mesh3`, `regional_bureau` の 6 種
- CRS: EPSG:4301 (Tokyo) と EPSG:6668 (JGD2011)、JGD2000 は L03-a の中間年度
- 形式: shp (全件)、geojson (3 件)、gml (5 件)
- coverage: full (N03, L03-a) と partial (A03, A53) の両方

**MVP 対象外** (将来フェーズ):
- WGS84 (mesh*h30) / CSV / CityGML / GeoTIFF — 変則形式の個別対応
- Shapefile vs CSV の属性差異問題 (mesh\* 統計系)
- 別ホスト配布 (G04-a 等) の詳細検証 (URL を直接扱うだけなので MVP でも動作はする想定)

---

## 運用ルール

- 各フェーズの成果物は独立にコミット (Phase 間でのマージ混在を避ける)
- 動作確認で問題が見つかったら、その場で差し戻し・設計見直しを行う (次フェーズには進まない)
- テストは各フェーズで書き、Phase 0 の CI に積み上げる
