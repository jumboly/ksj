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

## Phase 8: AI エージェント連携 (v0.2.0 候補)

**動機**: 対話的な KSJ 探査 (「どのデータセットが全国版を持たない?」「A31a の最新版は何ファイル?」「N03 の最新版だけ DL して GPKG に統合して」等) を自然言語インタフェースから通せるようにする。現在の CLI は CliRunner で呼ばれる前提の rich 出力がデフォルトだが、エージェントは構造化データを期待する。

**成果物**:
- **`--json` / `--format json` 出力モード** (全サブコマンド対象、特に `list` / `info` / `catalog diff` / `download` / `integrate` の実行結果):
  - rich Table / ログ風メッセージの代わりに JSON Lines または 単一 JSON を stdout に
  - 成功時スキーマと失敗時スキーマ (exit_code, error_kind, message) を docs 化
  - 既存動作との互換: フラグ未指定時は rich 出力のまま
- **MCP server** (`src/ksj/mcp/` 新設):
  - `ksj mcp serve` サブコマンドで stdio / SSE サーバー起動
  - 公開する Tool: `ksj_list` / `ksj_info` / `ksj_catalog_summary` / `ksj_download` / `ksj_integrate` / `ksj_catalog_refresh` (取り扱い注意の副作用ありは明記)
  - Tool ごとに JSONSchema を定義 (scope / format / crs_filter の選択肢を enum で列挙)
  - 副作用の分離: read-only (list/info/summary) と write (download/integrate/refresh) を明示マーク
- **エージェント向けドキュメント** (`docs/agent.md`):
  - どの Tool が副作用ありか、並列実行可否、レート制限の扱い
  - 典型フロー (「全国版のみ DL」「特定 scope 統合」) をサンプル
  - Claude Desktop / Claude Code での接続手順

**スコープ外** (Phase 8+ 以降):
- リアルタイム進捗のストリーミング (download の per-file 進捗を MCP の partial response で返す等)
- エージェント固有の高レベル DSL (「災害系で A31a + A53 を両方 DL → 結合」といった 1 行指示)

**動作確認**:
```bash
# --json 出力
uv run ksj list --json | jq '.[] | select(.scopes | contains(["national"]) | not) | .code'
uv run ksj info A31a --json | jq '.versions["2024"].files | length'

# MCP server 起動 (stdio)
uv run ksj mcp serve
# 別端末で Claude Code などから接続し、自然言語で ksj tool を呼べること
```

**参考**:
- MCP プロトコル仕様: https://modelcontextprotocol.io/
- 現 CLI は typer サブコマンド構造で薄いため、`cli.py` 各コマンドのハンドラ関数を再利用して JSON 出力分岐を足す形で収まる想定 (大きな refactor は不要)

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

### Phase 9: カタログ正規化 (情報密度の引き上げ) (draft)

**目的**: license / geometry / 用途タグなど、AI エージェントがフィルタ・推薦に使える構造化情報をカタログに揃える。

**成果物 (案)**:
- `Dataset.license: LicenseProfile | None` — `license_raw` を正規化 (商用可否・出典表示・改変・年度別/県別条件)
- `Dataset.geometry_types` を refresh で実際に充填 (現状型のみで空)。category + code prefix の規則ベース推定が第一近似、必要なら 1 ファイルだけサンプル読み
- `Dataset.description: str | None` — LLM 用の 1〜3 文要約 (初回は人手で 124 件)
- `Dataset.use_cases: list[str]` — 用途タグ (語彙設計は要決定、未確定事項 2)
- 修正対象: `src/ksj/catalog/schema.py`, `src/ksj/catalog/_normalizers.py`, `src/ksj/catalog/scraper/`, `catalog/datasets.yaml` (一括マイグレーション、差分レビュー用スクリプト推奨)
- 旧フィールド互換のため追加分はすべて optional。`integrator/pipeline.py:265-291` の metadata 書出しに retrofit が必要

**License 正規化スキーマ案**:
```python
class LicenseProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal[
        "cc_by_4_0", "cc_by_4_0_partial",
        "commercial_ok", "non_commercial",
        "site_terms_only", "mixed_by_year", "mixed_by_region",
        "unknown",
    ]
    commercial_use: bool | Literal["unknown", "conditional"] = "unknown"
    attribution_required: bool = True   # KSJ 約款が一律要求
    derivative_works: bool | Literal["unknown"] = "unknown"
    source_terms_url: str = "https://nlftp.mlit.go.jp/ksj/other/agreement.html"
    constraints: list[str] = Field(default_factory=list)
    by_year: dict[str, "LicenseProfile"] | None = None
```

`license_raw` の実測分布 (124 件): `非商用` 約 50 / `CC_BY_4.0` 系 約 30 / `CC_BY 一部制限` 約 12 / `商用可` 約 18 / 年度条件 5 / 県別制限 4 / 「KSJ 約款のほか個別条件」1。

**動作確認 (案)**:
```bash
uv run ksj catalog refresh --dry-run     # 全 124 件の license が正規化されることを確認
uv run ksj info A31a                      # license: LicenseProfile(...) が表示
uv run pytest                             # 既存 E2E (Phase 7) が壊れていない
```

依存: なし (Phase 8 と独立)

---

### Phase 10: フィルタ拡張 (list/info の表現力) (draft)

**目的**: 自然言語要求のうち「商用可」「ポリゴン」「最新版のみ」「特定 CRS」等の制約条件を CLI / MCP で明示的に指定できるようにする。

**成果物 (案)**:
- `ksj list` に追加: `--geometry {point|line|polygon|raster}` / `--license {commercial|attribution-only|cc-by|any}` / `--include-unknown-license` / `--format-filter` / `--crs-filter` / `--year-min` / `--year-max` / `--latest-only` / `--use-case <tag>`
- `ksj list --format {table|csv|json}` (Phase 8 の `--json` を拡張)
- `ksj info <code> --json --year YYYY`
- フィルタロジックは `src/ksj/catalog/query.py` 新設、CLI / MCP で共有
- MCP `ksj_list` / `ksj_info` も同フィルタに連動

依存: Phase 9 (license / geometry / use_cases が無いとフィルタが空回り)

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

- **License 誤分類**: 「年度条件」「県別制限」は機械判定が難しい。`unknown` はフィルタ既定で除外、LLM 提示時には `license_raw` を併記して人間レビューを促す
- **推薦のハルシネーション**: 戻り値はカタログ実在 code に限定。`reasoning` フィールドで根拠を必ず添える。`limit` 既定 5
- **互換破壊**: `Dataset.license` を str → LicenseProfile に変える際は `metadata["license"]` 書出し経路 (`integrator/pipeline.py:265-291`) の retrofit が必要。`license_summary: str` の派生 property を併設して既存利用箇所を壊さない
- **インデックス規模**: 124 dataset は SQLite FTS5 で十分。embedding 索引は必須ではない
- **transactional 性**: `ksj_integrate_many` の部分失敗時に rollback するか残すか (未確定事項 5)

### 主要な未確定事項 (Phase 9 着手前にユーザー確認)

1. **License 構造**: 案 1 (nested `LicenseProfile`、型安全だが YAML 冗長) vs 案 2 (フラット `commercial_use_default` + 例外時のみ nested)
2. **`use_cases` タグ語彙**: enum 固定 (型安全) vs フリータグ + 正規化辞書 (拡張性)。`flood_risk` を独立か `disaster_risk` で統括か
3. **空間結合バックエンド**: GeoPandas のみ (軽量) vs DuckDB-spatial (大規模 OK だが依存重)
4. **推薦エンジン**: BM25 のみ (依存軽量、決定的) vs sentence-embeddings 同梱 (重量、再現性低下)
5. **`integrate_many` の transactional 性**: 部分成功を残すか全 rollback するか

---

## 要調査項目

### `DownLd_new(...)` 変種とカタログ漏れの扱い (2026-04-18 発見)

**現象**: 現行パーサー (`src/ksj/catalog/_parser.py:170-172`) の `_DOWNLD_RE` は `DownLd\(` のみにマッチし、`DownLd_new(...)` 呼び出しを取りこぼす。影響を受けるデータセット:

| コード | ページ | DownLd( 数 | DownLd_new 数 | 現カタログ収録 |
|---|---|---|---|---|
| L02-2025 (地価調査) | `KsjTmplt-L02-2025.html` | 0 | 2,073 | 0 files (versions=[]) |
| A16-2020 (密集市街地) | `KsjTmplt-A16-2020.html` | 612 | 8 | 2020 年は 48 files (DownLd_new 由来の 8 件だけ漏れ) |

引数順は `DownLd` と同じ `(size, filename, rel_path)` で、regex を `DownLd(?:_new)?\(` に緩めれば両方拾える (実装確認済み、巻き戻し保留中)。

**未確定の論点**:

1. **公式配布ステータス**: L02 / A16 は KSJ トップのカード一覧には載っていないが、`<ul class="collapsible">` パネル (「国土」「政策区域」カテゴリの折りたたみ内) に `<li class="collection-item">` として配置されている。KSJ としての公式配布扱いか、過去アーカイブかをサイト側の位置付けで確認する必要がある。同じ collapsible 内にある A13 (森林地域) 等は現行カタログに登録済みで、構造自体は正規
2. **他の DownLd 変種の有無**: `DownLd_new` だけか、`DownLd_foo` のような別変種が他ページに無いか、`data/html_cache/` 全体で onclick の関数名を列挙して確認すべき
3. **カタログ YAML の差分サイズ**: 拾うようにすると YAML が +2,078 URL で膨らむ。コミット粒度・レビュー負荷を踏まえた取り込み方針 (一括 or 段階的、L02 のみ先行 等)

**調査手順 (案)**:
```bash
# onclick の関数名を全列挙
uv run python -c "
from pathlib import Path
import re
names = set()
for p in Path('data/html_cache').rglob('KsjTmplt-*.html'):
    for m in re.finditer(r\"onclick=['\\\"][^'\\\"]*?([A-Za-z_][A-Za-z0-9_]*)\\(\", p.read_text(encoding='utf-8', errors='replace')):
        names.add(m.group(1))
print(sorted(names))
"

# KSJ サイト側の L02 / A16 の位置付けを公式ページで目視確認
# → 確認結果をこの roadmap に追記
```

**暫定対応状況**:
- 2026-04-18 時点で実装修正は巻き戻し済み (`src/ksj/catalog/_parser.py` / `tests/test_parser.py` / `catalog/datasets.yaml` は元の状態)
- 本調査が終わってから、regex 修正 + テスト追加 + `ksj catalog refresh --only L02 --only A16` を正式に適用する

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
