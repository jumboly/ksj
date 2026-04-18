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
- `pyarrow.RecordBatch` ストリーム化 (pd.concat で現行 PC メモリに収まる想定、計測で問題が出たら対応)
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

## Phase 6: GeoParquet + convert

**成果物**:
- `src/ksj/writer/parquet.py` — GeoParquet 1.1 + key_value_metadata
- `ksj integrate --format parquet`
- `ksj convert <input.gpkg> --format parquet`

**動作確認**:
```bash
uv run ksj integrate L03-a --year 2021 --format parquet
uv run ksj convert data/integrated/N03-2025.gpkg --format parquet
uv run --with duckdb python -c "
import duckdb
duckdb.sql(\"SELECT count(*) FROM 'data/integrated/N03-2025.parquet'\").show()"
```

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

**動機**: 対話的な KSJ 探査 (「どのデータセットが全国版を持たない?」「A31a の最新版は何ファイル?」「N03 の最新版だけ DL して Parquet に変換して」等) を自然言語インタフェースから通せるようにする。現在の CLI は CliRunner で呼ばれる前提の rich 出力がデフォルトだが、エージェントは構造化データを期待する。

**成果物**:
- **`--json` / `--format json` 出力モード** (全サブコマンド対象、特に `list` / `info` / `catalog diff` / `download` / `integrate` / `convert` の実行結果):
  - rich Table / ログ風メッセージの代わりに JSON Lines または 単一 JSON を stdout に
  - 成功時スキーマと失敗時スキーマ (exit_code, error_kind, message) を docs 化
  - 既存動作との互換: フラグ未指定時は rich 出力のまま
- **MCP server** (`src/ksj/mcp/` 新設):
  - `ksj mcp serve` サブコマンドで stdio / SSE サーバー起動
  - 公開する Tool: `ksj_list` / `ksj_info` / `ksj_catalog_summary` / `ksj_download` / `ksj_integrate` / `ksj_convert` / `ksj_catalog_refresh` (取り扱い注意の副作用ありは明記)
  - Tool ごとに JSONSchema を定義 (scope / format / crs_filter の選択肢を enum で列挙)
  - 副作用の分離: read-only (list/info/summary) と write (download/integrate/convert/refresh) を明示マーク
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
