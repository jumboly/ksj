# JSON 出力モード (`--json` / `--format json`)

`ksj` CLI はすべてのサブコマンドで JSON 出力モードをサポートする。
AI エージェント (Claude Code 等) や自動化スクリプトが結果を構造化して扱う
ときに使う。人間向け表示 (rich Table / カラー付きメッセージ) はフラグ未指定時
のデフォルトのまま保持され、JSON モードと**共存**する。

## フラグ

- `--json`: JSON 出力を有効化する (ブーリアン)
- `--format [rich|json]`: 出力形式を明示指定する (デフォルト `rich`)
- 両方を指定したときは `--json` を優先する (警告は出さない)

フラグは root レベルなので、サブコマンドより**前**に置く:

```bash
uv run ksj --json list                       # OK
uv run ksj --format json info N03            # OK
uv run ksj list --json                       # NG (Typer が未知オプション扱い)
```

## 成功時スキーマ

1 件の JSON オブジェクトを stdout に 1 行で出す (JSON Lines ではなく単発)。

```json
{
  "ok": true,
  "command": "<コマンド識別子>",
  "data": { /* コマンド固有のペイロード */ }
}
```

- `command` はドット区切りの安定 ID。現時点で使う値:
  - `list`
  - `info`
  - `catalog.diff`
  - `catalog.refresh`
  - `catalog.summary`
  - `html.list`
  - `html.fetch`
  - `download`
  - `ingest-local`
  - `integrate`
- `data` の型は下表参照。`Path` は文字列化 (`default=str`)、`datetime` は
  ISO8601 文字列、pydantic モデルは `model_dump(mode="json")` 相当。

### `list` の `data`

```json
{
  "total": 131,
  "rows": [
    {
      "code": "N03",
      "name": "行政区域",
      "category": "政策区域",
      "versions": 18,
      "scopes": ["national", "prefecture"]
    }
  ]
}
```

- `total`: フィルタ前のカタログ収録総数
- `rows`: `--category` / `--scope` でフィルタ後の行

### `info` の `data`

```json
{
  "code": "N03",
  "name": "行政区域",
  "category": "政策区域",
  "detail_page": "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-v3_1.html",
  "license_raw": "オープンデータ（CC_BY_4.0） ※本データを二次利用する場合には、国土地理院に申請等必要な場合があります。",
  "geometry_types": ["polygon"],
  "description": "都道府県・市区町村の行政境界ポリゴン。…",
  "use_cases": ["administrative_boundary"],
  "notes": null,
  "versions": [
    {
      "year": "2025",
      "files": [
        {
          "scope": "national",
          "scope_identifier": "",
          "crs": 6668,
          "format": "shp",
          "url": "https://..."
        }
      ]
    }
  ]
}
```

`versions` は年昇順。`files` は HTML に出現した順序を保持する。

### `catalog.diff` の `data`

```json
{ "added": ["X01"], "removed": ["Y02"], "changed": ["Z03"] }
```

### `html.list` の `data`

```json
{
  "cache_dir": "data/html_cache",
  "entries": [
    {
      "relative_path": "nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-v3_1.html",
      "size_bytes": 23456,
      "modified_at": "2026-04-10T12:34:56"
    }
  ],
  "total_bytes": 234567
}
```

### `catalog.summary` の `data`

カタログ全体のメタ集計 (per-dataset は返さない)。件数は降順ソート済み。

```json
{
  "total_datasets": 132,
  "categories": {"国土（水・土地） / 土地利用": 12, "交通 / 交通": 9, ...},
  "scope_histogram": {"national": 78, "prefecture": 64, "mesh3": 12, ...},
  "years_seen": ["1920", "1950", ..., "2025"],
  "warnings": []
}
```

### `catalog.refresh` の `data`

```json
{
  "summary": {
    "total_datasets": 132,
    "added": ["L02"],
    "updated": ["N03"],
    "skipped": [...],
    "warnings": [...],
    "unsupported": ["A55"]
  },
  "saved_path": "catalog/datasets.yaml"
}
```

- `--dry-run` 時は `saved_path: null`
- `summary` は `RefreshSummary` dataclass の dump

### `html.fetch` の `data`

```json
{
  "summary": { /* RefreshSummary と同構造 */ },
  "cache_dir": "data/html_cache",
  "cache_stats": {"file_count": 132, "total_bytes": 18000000}
}
```

### `download` の `data`

```json
{
  "code": "N03",
  "year": "2025",
  "results": [
    {
      "url": "https://...",
      "path": "data/raw/N03/2025/N03-2025.zip",
      "downloaded_bytes": 512000000,
      "skipped": false,
      "resumed": false,
      "error": null
    }
  ]
}
```

- `results[].error` が null なら成功、文字列なら失敗理由
- 全件失敗時は `exit_code=1` で終了する (ペイロードは ok=true のまま返る場合あり: 個別ファイルの失敗は results 側で表現される)。**呼び出し側は `exit_code` で最終判定すること**
- Progress UI は JSON モードでは出力しない (handler 内の `on_start` / `progress` callback を None にする)

### `ingest-local` の `data`

```json
{
  "code": "N03",
  "year": "2025",
  "dest_root": "data/raw/N03/2025",
  "copied": ["data/raw/N03/2025/src.zip"]
}
```

### `integrate` の `data`

```json
{
  "output_path": "data/integrated/N03-2025.gpkg",
  "layer_names": ["N03_2025"],
  "source_zips": ["data/raw/N03/2025/N03-2025.zip"],
  "target_crs": "EPSG:6668",
  "crs_converted": false,
  "strategy": "national",
  "source_count": 1
}
```

- `strategy` は `"national"` / `"latest-fill"` のいずれか
- Path 系フィールドはすべて文字列化される (`default=str`)

## 失敗時スキーマ

```json
{
  "ok": false,
  "exit_code": 1,
  "error_kind": "<enum>",
  "message": "<人間可読メッセージ>"
}
```

- 失敗時はプロセスも `exit_code` で終了する (ペイロードの `exit_code` と同値)
- traceback は **JSON には含めない** (エージェントが mitigation に使えないノイズを避ける)。運用ログが欲しい場合は stderr を見る

### `error_kind` の語彙

| 値 | 発生コマンド | 意味 |
|---|---|---|
| `catalog_not_found` | 全 | `catalog/datasets.yaml` が無い |
| `dataset_not_found` | info / download / integrate | `code` がカタログに無い |
| `no_matching_files` | download | フィルタで 0 件 |
| `download_failed` | download | 全ファイル失敗 (個別失敗は `results[].error` で表現、全件失敗時に `exit_code=1`) |
| `integrate_failed` | integrate | 統合処理中の既知エラー (NoSourcesError / DownloadRequiredError / NoMatchingFormatError) |
| `invalid_argument` | 全 | 引数不整合 (例: `--scope` + `--prefer-national`、`ingest-local --from` の不在パス) |

未知例外は JSON に載せず Python traceback として stderr に落ち、`exit_code=1` で終了する。これは **契約に含まれないバグ扱い**。

## stderr / ログ

- JSON モードでも `ksj` ロガーの WARNING 以上は `stderr` に rich 形式で出続ける
- stdout は **JSON 1 行のみ**になる設計で、エージェントは `| jq` でパイプ処理できる
- Progress (ダウンロードバー / spinner) は JSON モード時には描画しない (handler の `on_start` / `progress` callback を None にする)

## 互換性ポリシー

- `error_kind` enum の値追加は後方互換 (既存値の意味は変えない)
- `data` への**新規キー追加は非破壊**、既存キー削除はメジャー bump 相当
- `command` 識別子の renaming はメジャー bump 相当

