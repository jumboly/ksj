# カタログ設計

## 設計方針

KSJ サイトの全量調査で以下が確認された:

- **全データセット数: 132 件** (国土 / 政策区域 / 地域 / 交通 / 各種統計 の 5 カテゴリ)
- **URL テンプレートによる推測は不能**。データセットごとに完全に異なる:
  - N03: `https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03_2025/N03-20250101_XX_GML.zip`
  - L03-b: `L03-b-21_3036-jgd2011_GML.zip` (2 桁年、測地系サフィックス)
  - G04-a: 以前は `www.gsi.go.jp/GIS/...` 別ホスト配布 (現在は nlftp 移行済)
  - A03: `A03-03_SYUTO-tky_GML.zip` (圏域コード SYUTO/CHUBU/KINKI)
  - mesh1000r6: `1km_mesh_2024_01_GML.zip` (ファイル名にコードが現れない)
- **1 データセット内で年度ごとに測地系が異なる**: L03-b は 1976=Tokyo Datum、2009=JGD2000、2021=JGD2011 が併存
- **形式が同一年度で並列配布**される: 同じ分割単位で Shapefile / GML / GeoJSON の URL が複数並ぶ
- **機械可読 API・RSS は存在しない**。HTML スクレイプが唯一の取得手段

## 結論

カタログ YAML は**スクレイパ出力のバージョン管理済みスナップショット**として扱う。各ファイルの実 URL を直接列挙し、テンプレート展開は行わない。`ksj catalog refresh` で再生成、差分をレビューしてコミットする運用とする。

## 重要ルール: HTML を正、ファイル名を根拠にしない

データ形式 (Shapefile / GML / GeoJSON / CityGML / CSV / GeoTIFF) と測地系 (CRS) は、**必ず KSJ 詳細ページの HTML テーブル列から抽出する**。ファイル名サフィックス (`_GML.zip` / `-jgd2011` 等) を判定根拠にしてはならない。ファイル名と中身が乖離するケースを避けるため。

カタログには正規化値と HTML 原文の両方を保持する:

```yaml
format: gml_jpgis2014
format_raw: "GML形式"          # 詳細ページ「形式」列の原文
crs: 6668
crs_raw: "世界測地系"           # 詳細ページ「測地系」列の原文
```

`_raw` 欄は「その列のセルが当該行に存在したとき」にのみ値を持つ。ページに「形式」列がないデータセット (N03 等) の `format_raw` は空文字で、ページ全体の形式宣言をコピーしない (行単位の原文でなくなるため)。

## クローラの処理フロー

`ksj catalog refresh` の動作:

```
Step 1: トップ index.html から 132 データセットのコード・名称・カテゴリ・詳細ページ URL を抽出
Step 2: 各詳細ページの thead からラベル→列 index のマップを作り、tbody の各行から
        (scope, 識別子, crs, format, url, size, year) を抽出
```

- Step 2 は並列 2〜4、レート制限 1 req/sec で実行 (`--parallel`, `--rate` で変更可)
- HTML 構造の手がかり:
  - `<table><thead>` で列順を解釈 (「地域 / 形式 / 測地系 / 年度 or 年 / ファイル容量 / ファイル名」のいずれかを部分一致で特定)。**列順はデータセットごとに違う** (例: N13 のみ「形式」列あり)
  - `#prefectureNN` の id 属性から scope コードをフォールバック取得 (NN=01-47 都道府県、51-59 地方区分、81-89 開発局/整備局)
  - `a[onclick*="DownLd"]` がダウンロードリンク

## カタログファイル構成

カタログは 2 ファイルに分かれる:

| ファイル | 管理主体 | 内容 |
|---|---|---|
| `catalog/datasets.yaml` | scraper (`ksj catalog refresh` が上書き) | name / category / detail_page / geometry_types / license / license_raw / notes / versions |
| `catalog/annotations.yaml` | 人手 + LLM 補助生成 (`.scratch/python/generate_descriptions.py`) | description / use_cases |

**分離の理由**: `ksj catalog refresh` は KSJ サイトから datasets.yaml を再生成するため、LLM/人手で埋めた `description` や `use_cases` を datasets.yaml に置くと refresh のたびに消える。annotations.yaml は scraper が一切触らず、loader が読み込み時に code 単位で merge する。

`refresh` 完了時に「annotations.yaml 未整備 code」があれば stderr に warning を出す (`RefreshSummary.annotations_missing`)。新 code を見逃しにくくするための最小限の整合性チェック。

### annotations.yaml の形式

```yaml
datasets:
  N03:
    description: "都道府県・市区町村の行政境界ポリゴン。GIS 分析の基礎地図として最頻出のデータセット。"
    use_cases:
      - administrative_boundary
```

エントリが無い code は `description=None, use_cases=[]` で読み込まれる (エラーにはならない)。

## YAML ファイル構造 (リファレンス)

### ルート

```yaml
schema_version: 1                       # 現行 v1 のみ
generated_at: "2026-04-18T08:42:05Z"    # スクレイプ完了時刻 (UTC ISO8601)
source_index: https://nlftp.mlit.go.jp/ksj/index.html
total_datasets: 132                     # datasets の要素数と一致
datasets:                               # コード → Dataset
  N03: { ... }
  L03-b: { ... }
```

pydantic バリデーション: `model_config = ConfigDict(extra="forbid")`。未定義キーを含む YAML は読込時にエラー。

### Dataset

| フィールド | 型 | 必須 | 説明 | 格納先 |
|---|---|---|---|---|
| `name` | str | ✓ | トップ index 表示名 (例: 「行政区域」) | datasets.yaml |
| `category` | str | — | 「大カテゴリ / 小カテゴリ」形式 (例: 「政策区域 / 行政地域」) | datasets.yaml |
| `detail_page` | URL | — | `KsjTmplt-<code>*.html` の絶対 URL | datasets.yaml |
| `geometry_types` | list | — | `point` / `line` / `polygon` / `raster` の 0 個以上。name 末尾の「（ポリゴン）」等から推定 | datasets.yaml |
| `license` | LicenseProfile \| null | — | 正規化ライセンス (後述)。`license_raw` から scraper が生成 | datasets.yaml |
| `license_raw` | str | — | 詳細ページ「使用許諾条件」欄の原文 (全文、truncate なし) | datasets.yaml |
| `description` | str | — | 1〜3 文の要約 (Phase 12 の検索/推薦で使う) | annotations.yaml |
| `use_cases` | list[UseCase] | — | 用途タグ (enum 語彙、後述)。複数付与可 | annotations.yaml |
| `notes` | str | — | 補足 (フォームベース配布等) | datasets.yaml |
| `versions` | dict | ✓ | 年度文字列 (`"2025"` / `"unknown"`) → Version | datasets.yaml |

`description` / `use_cases` のみ `catalog/annotations.yaml` に分離しており、loader が読み込み時に merge する。理由は下の「カタログファイル構成」を参照。

### Version

| フィールド | 型 | 説明 |
|---|---|---|
| `reference_date` | date | データ基準日 (例: `2025-01-01`)。現状未出力 |
| `files` | list[FileEntry] | ダウンロード可能な ZIP URL 一覧。空 (`[]`) はフォームベース配布等で自動列挙できないことを示す |
| `null_values` | list | 独自欠損値コード (例: `[-999, 9999]`)。統合時に NaN 化する |
| `notes` | str | 年度固有の注記 |

年度キーは原則 4 桁西暦文字列。スクレイプで年度が特定できなかった場合のみ `"unknown"` (N13 のように複数年度が同一ページに並ぶパターンでは、全行が `"2024"` 等 1 つの年度にまとまる)。

### FileEntry

共通フィールド:

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `scope` | Literal | ✓ | 下の scope 表を参照 |
| `url` | URL | ✓ | 絶対 URL の `.zip` ファイル |
| `format` | Literal | ✓ | 下の format 表を参照 |
| `format_raw` | str | — | 詳細ページ「形式」列の原文 (当該列が存在する行のみ) |
| `crs` | int | — | EPSG コード。未整備 (`unknown` 形式) の場合のみ省略可 |
| `crs_raw` | str | — | 詳細ページ「測地系」列の原文 |
| `size_bytes` | int | — | ZIP サイズ。KSJ が「0MB」表示で実サイズ不明なケースは省略 |
| `encoding` | `"utf-8"` \| `"cp932"` | — | 文字エンコーディング。Shapefile は cp932 既定だが、新しめの配布で UTF-8 のケースもあり HTML から自動抽出できないので手動 override 用 |
| `attribute_caveat` | str | — | データセット固有の但し書き (例: 「Shapefile 版は男女別削除」) |

scope ごとに必須となる識別子フィールド (どれか 1 つは埋まっている必要がある):

| scope | 必須識別子 | 付随名称 | 備考 |
|---|---|---|---|
| `national` | なし | — | 全国一括 |
| `region` | なし (推奨: `region_code`) | `region_name` | 慣用コード 51-59 が判明すれば記録。無ければ name のみでも成立 |
| `regional_bureau` | `bureau_code` | `bureau_name` | 81-89 の 2 桁文字列 |
| `prefecture` | `pref_code` | `pref_name` | 1-47 の int |
| `urban_area` | `urban_area_code` | `urban_area_name` | `SYUTO` / `CHUBU` / `KINKI` |
| `river` | `river_id` | `river_name` | 1 級河川 ID |
| `municipality` | `muni_code` | `muni_name` | 5 桁市町村コード文字列 |
| `mesh1`-`mesh6` | `mesh_code` | — | 下の「scope 語彙」表参照 |
| `special` | なし | `special_code`, `special_name` | 上記に当てはまらない例外 |

## scope 語彙 (全 14 種)

| scope | 付随キー | 説明 | 代表データセット |
|---|---|---|---|
| `national` | — | 全国一括 | N03, L01, N06 |
| `region` | `region_code` (51-59), `region_name` | 地方区分 (北海道/東北/関東/中部/近畿/中国/四国/九州/沖縄) | L01, W05, N03 |
| `regional_bureau` | `bureau_code` (81-89), `bureau_name` | 北海道開発局 + 地方整備局 | A53, A31a |
| `prefecture` | `pref_code` (1-47), `pref_name` | 都道府県 | 多数 |
| `urban_area` | `urban_area_code` (SYUTO/CHUBU/KINKI) | 三大都市圏 | A03, L03-b-u, L03-b-c |
| `river` | `river_id`, `river_name` | 一級河川単位 | (現状出現なし) |
| `municipality` | `muni_code`, `muni_name` | 市町村単位 | A51 の一部 |
| `mesh1` | `mesh_code` (4桁) | 1次メッシュ (80km) | N13, L03-b, G04-a |
| `mesh2` | `mesh_code` (6桁) | 2次メッシュ (10km) | — |
| `mesh3` | `mesh_code` (8桁) | 3次メッシュ (1km, 標準地域メッシュ) | — |
| `mesh4` | `mesh_code` (9桁) | 3次-1/2 (500m) | — |
| `mesh5` | `mesh_code` (10桁) | 3次-1/4 (250m) | — |
| `mesh6` | `mesh_code` (11桁) | 3次-1/10 (100m) | — |
| `special` | `special_code`, `special_name` | 上記に該当しない特殊単位 | (現状出現なし) |

メッシュの桁→次数は JIS X 0410 準拠。KSJ の配布は原則 1 次メッシュ単位 (4桁コード) で ZIP 化されており、内部データは 100m / 250m 等の細分メッシュでも ZIP スコープは `mesh1` になる。

### 地方整備局コード対応

```
81: 北海道開発局
82: 東北地方整備局
83: 関東地方整備局
84: 北陸地方整備局
85: 中部地方整備局
86: 近畿地方整備局
87: 中国地方整備局
88: 四国地方整備局
89: 九州地方整備局
```

URL の末尾コード (例: `A53-23-82_GML.zip`) で実証済み。沖縄総合事務局は現カタログに出現せずコード未確認 (出現を検知したら追加する運用)。

## CRS の正規化

HTML の「測地系」列記載を EPSG コードに正規化:

| HTML 記載 | 名称 | EPSG | 備考 |
|---|---|---|---|
| 「旧測地系」「日本測地系」「Tokyo Datum」 | Tokyo Datum | 4301 | L03-a/b の 1976 版、A03-2003、N04-1978 等 |
| 「世界測地系」+ filename に `-jgd` | JGD2000 | 4612 | 2002〜2011 の標準 |
| 「世界測地系」+ filename に `-jgd2011` / サフィックス無し | JGD2011 | 6668 | 現行。新しいデータセットのデフォルト |
| 「WGS84」 | WGS84 | 4326 | mesh1000h30, mesh500h30 シリーズ |

HTML の「世界測地系」表記は JGD2000 と JGD2011 を区別しないため、filename サフィックスで補完する。`crs_raw` は原文を保持。

## LicenseProfile の正規化

`license_raw` (HTML「使用許諾条件」欄の原文) を `normalize_license()` で以下の構造に変換する:

```yaml
license:
  kind: cc_by_4_0              # LicenseKind (下表)
  commercial_use: true         # true / false / "unknown" / "conditional"
  attribution_required: true   # KSJ 約款が一律要求するため既定 true
  derivative_works: true       # true / false / "unknown"
  source_terms_url: https://nlftp.mlit.go.jp/ksj/other/agreement.html
  constraints: []              # 「岡山県のみ非商用」等の自由文制約
  by_year:                     # 年度分岐。null 可
    "2019":
      kind: cc_by_4_0
      commercial_use: true
      ...
    _else:                     # 「上記以外」sentinel
      kind: commercial_ok
      commercial_use: true
```

### LicenseKind 分類

| kind | 判定条件 | 代表 code |
|---|---|---|
| `cc_by_4_0` | 「CC_BY_4.0」「CC-BY 4.0」等を含み「（一部制限）」無し | N03, N13 (29 件) |
| `cc_by_4_0_partial` | CC_BY 系 + 「（一部制限）」 | A13, A33 (14 件) |
| `commercial_ok` | 「商用可」を含み「非商用」無し | W09, G04-a (18 件) |
| `non_commercial` | 「非商用」を含み「商用可」無し | G02, C23 (60 件) |
| `mixed_by_year` | 年度分岐 trigger (「YYYY年以降」/「上記以外」/複数年度) | L01, A09, N07 (10 件) |
| `site_terms_only` | CC_BY / 商用可の明示無し、「利用規約」参照のみ | (現状未出現) |
| `mixed_by_region` | 県別・地域別条件をトップレベルで分岐 | (現状未使用、将来の県別ライセンス用に予約) |
| `unknown` | 空文字、または上記いずれにも該当しない | A48 (1 件) |

> **正典**: `src/ksj/catalog/schema.py:LicenseKind` Literal が kind 語彙の正。件数は 2026-04-21 時点のスナップショット (集計: `uv run python -c "from ksj.catalog.loader import load_catalog; ..."`)。分類ロジックは `src/ksj/catalog/_normalizers.py:normalize_license()`。KSJ 側の typo「CC_B.Y_4.0」も拾う。年度分岐 trigger の詳細条件は `_has_year_branching()` を参照 (「整備年度」「作成年度」のような属性的年度は分岐とみなさない)。

### 年度分岐 (by_year)

`mixed_by_year` の場合、`by_year` に年度文字列 → 子 LicenseProfile の dict が入る。`"_else"` キーは「上記以外：...」で指定されたデフォルト条件を表す sentinel。

例: L01 (地価公示) は「2019年以降：CC_BY_4.0 / 上記以外：商用可」なので:
```yaml
by_year:
  "2019": {kind: cc_by_4_0, commercial_use: true, ...}
  _else: {kind: commercial_ok, commercial_use: true, ...}
```

## geometry_types の推定

データセット名末尾の KSJ 慣行表記「（ポリゴン）」「（ポイント）」「（ライン）」「（ラスタ版）」を検出して `geometry_types` に埋める (`infer_geometry_types()`)。

- 「道路（ライン）」→ `[line]`
- 「ダム（ポイント）」→ `[point]`
- 「景観計画区域（ポリゴン）（ポイント）」→ `[polygon, point]` (name 内の出現順)
- 「土地利用細分メッシュ」→ `[]` (カッコ表記なしは保守的に空)

メッシュデータ等で推定不能なケースは `[]` のまま残す。Phase 10 以降で実データから補完するか、必要なら手動で annotations 側に補足する。

## UseCase タグ語彙

`use_cases` は以下の Literal で型安全にフィルタ可能:

| tag | 用途 | 代表 code |
|---|---|---|
| `administrative_boundary` | 行政境界 | N03, A16 |
| `transportation` | 交通インフラ | N02, N13, P11 |
| `disaster_risk` | 災害リスク全般 | A33, A48, P20 |
| `flood_risk` | 水害特化 (disaster_risk と併用可) | A31a, A40, A51 |
| `land_use` | 土地利用 | L03-a/b, A12, A13 |
| `population` | 人口・統計 | mesh1000r6, A16 |
| `facility` | 施設 | P04, P05, P29 |
| `terrain` | 地形・水域 | G04-a, C23, W01 |
| `climate` | 気候 | G02, A22-m |
| `urban_planning` | 都市計画 | A09, A55, A17 |
| `economy` | 経済・地価 | L01, L02, P33 |

1 データセットに複数タグ付与可 (例: A31a = `[flood_risk, disaster_risk]`)。タグ付与は `catalog/annotations.yaml` で管理し、Phase 10 の `ksj list --use-case flood_risk` 等のフィルタで利用する。

> **正典**: `src/ksj/catalog/schema.py:UseCase` Literal が語彙の正。本表は 2026-04-21 時点のスナップショット。

## 形式の語彙

HTML 詳細ページの「データフォーマット」節、および「形式」列 (存在する場合) の両方から検出:

| 正規化 (`format`) | キーワード (部分一致、大文字比較) | pyogrio ドライバ |
|---|---|---|
| `gml_jpgis2014` | `JPGIS2014` / `JPGIS 2014` | GML |
| `gml_jpgis21` | `JPGIS2.1` / `JPGIS 2.1`、または「GML形式」単独 | GML |
| `citygml` | `CityGML` | (要検証) |
| `shp` | `シェープ` / `SHAPE` | ESRI Shapefile |
| `geojson` | `GeoJSON` | GeoJSON |
| `csv` | `CSV` | CSV + 座標列 |
| `geotiff` | `GeoTIFF` | GeoTIFF |
| `multi` | — | 1 つの ZIP に複数形式が同梱 (N03 の `_GML.zip` 等) |
| `unknown` | — | 判定不能 |

`multi` は「ページに複数形式の記載があり、かつ filename 末尾から単一形式に絞り込めない」場合の値。KSJ の `_GML.zip` は慣行的に ZIP 内部に Shapefile も同梱するため、形式宣言が 2 個以上かつ filename が `_GML.zip` なら `multi` とする。

## サンプル YAML

### datasets.yaml

```yaml
schema_version: 1
generated_at: "2026-04-18T08:42:05Z"
source_index: https://nlftp.mlit.go.jp/ksj/index.html
total_datasets: 132
datasets:

  N03:
    name: 行政区域（ポリゴン）
    category: 政策区域 / 行政地域
    detail_page: https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2025.html
    geometry_types: [polygon]
    license:
      kind: cc_by_4_0
      commercial_use: true
      attribution_required: true
      derivative_works: true
      source_terms_url: https://nlftp.mlit.go.jp/ksj/other/agreement.html
      constraints:
        - 二次利用時に二次利用申請が必要な場合あり
    license_raw: "オープンデータ（CC_BY_4.0） ※本データを二次利用する場合には、国土地理院に申請等必要な場合があります。"
    versions:
      "2025":
        files:
          - scope: national
            url: https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03_2025/N03-20250101_GML.zip
            format: multi
            crs: 6668
            crs_raw: 世界測地系
            size_bytes: 632289627
          - scope: prefecture
            pref_code: 1
            pref_name: 北海道
            url: https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03_2025/N03-20250101_01_GML.zip
            format: multi
            crs: 6668
            crs_raw: 世界測地系

  N13:
    name: 道路（ライン）
    category: 交通 / 交通
    detail_page: https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N13-2024.html
    geometry_types: [line]
    license:
      kind: cc_by_4_0
      commercial_use: true
      attribution_required: true
      derivative_works: true
      source_terms_url: https://nlftp.mlit.go.jp/ksj/other/agreement.html
      constraints: []
    license_raw: オープンデータ（CC_BY_4.0）
    versions:
      "2024":
        files:
          - scope: mesh1
            mesh_code: "3622"
            url: https://nlftp.mlit.go.jp/ksj/gml/data/N13/N13-24/N13-24_3622_GML.zip
            format: gml_jpgis2014
            format_raw: GML形式
            crs: 6668
            crs_raw: 世界測地系
            size_bytes: 73400

  A53:
    name: 多段階浸水想定
    category: 政策区域 / 災害・防災
    versions:
      "2023":
        files:
          - scope: regional_bureau
            bureau_code: "82"
            bureau_name: 東北地方整備局
            url: https://nlftp.mlit.go.jp/ksj/gml/data/A53/A53-23/A53-23-82_GML.zip
            format: multi
            crs: 6668
            crs_raw: 世界測地系

  L01:
    name: 地価公示
    versions:
      "2026":
        files:
          - scope: region
            region_code: "54"
            region_name: 甲信越・北陸地方
            url: https://nlftp.mlit.go.jp/ksj/gml/data/L01/L01-26/L01-26_54_GML.zip
            format: multi
            crs: 6668
            crs_raw: 世界測地系

  A55:
    name: 都市計画決定情報
    notes: "フォームベース配布のため URL 列挙ができません。KSJ サイトで手動取得してください。"
    versions:
      "2024":
        files: []   # 空リストで配布形態だけ記録
```

### annotations.yaml

```yaml
datasets:
  N03:
    description: "都道府県・市区町村の行政境界ポリゴン。GIS 分析の基礎地図として最頻出のデータセット。"
    use_cases:
      - administrative_boundary
  N13:
    description: "全国の道路センターラインデータ。道路種別 (国道・都道府県道等) や路線名を属性に持つ、道路分析の基礎データ。"
    use_cases:
      - transportation
  L01:
    description: "地価公示法に基づく標準地の価格・所在地・利用現況等。不動産価格の地域分析や時系列比較で広く利用される。"
    use_cases:
      - economy
```

## 欠損値・特殊値の処理

一部データセットは独自の欠損値コードを使用する (KSJ 製品仕様書の付録から抽出):

- `-999` / `-998` / `-997`
- `9999` / `999999` / `99999998` / `99999999`
- `-1`

`Version.null_values` にデータセット別に宣言し、統合時 (Phase 4) に NaN へ正規化する。現状スクレイパは自動抽出しないため、仕様書を見て手動で追記する運用。

## 整備範囲 (coverage) について

Dataset レベルの `coverage: full|partial` フィールドは**廃止済み**。全国整備判定を HTML の自然文から自動で行うのが困難で、手動で維持するコストも高いため、統合時の動作は以下 2 本道に単純化している:

1. `national` scope のファイルがあれば最新年度のそれを単独採用
2. 無ければ識別子 (`pref_code` / `mesh_code` / `bureau_code` / `urban_area_code` / `muni_code` / `river_id`) ごとに対象年度以前で最新の 1 件を選び union

この挙動の詳細は `docs/integration.md` を参照。整備範囲の実績は出力ファイルのメタデータ `coverage_summary` に記録される。
