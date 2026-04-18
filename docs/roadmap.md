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
