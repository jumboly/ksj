# 統合パイプライン

`ksj integrate <code> --year YYYY` の処理フロー。

## パイプライン全体

1. **カタログ解決**: `catalog/datasets.yaml` から `<code>/<year>` の `files[]` を取得
2. **ダウンロード補填**: `data/raw/<code>/<year>/` に全分割が揃っているか確認。不足は `downloader` で取得
3. **読込**: 各分割を `pyogrio.read_dataframe` で読込 (エンコーディングは `cchardet` + フォールバックで自動判定)
4. **UTF-8 正規化**: 文字列カラムを UTF-8 へ (内部表現は Python `str`)
5. **CRS 変換**: `pyproj` で `--target-crs` へ再投影
6. **スキーマ統一**: 全分割のカラムの和集合を取り、欠損は NaN、型は最広義に揃える
7. **欠損値正規化**: カタログ `null_values` で宣言された値を NaN に変換
8. **結合**: `pyarrow.concat_tables` / `GeoDataFrame.pd.concat` で結合
9. **出力**:
   - `.gpkg`: `pyogrio.write_dataframe` で 1 レイヤに出力、`gpkg_metadata_reference` テーブルに出典 JSON を埋込
   - `.parquet`: GeoParquet 1.1 仕様、`geo` メタデータ + `ksj_metadata` キーで出典・生成日・元 URL・target_crs を記録
10. **マニフェスト生成**: `data/integrated/<code>-<year>.manifest.json` を並列に生成 (ファイル外でも出典情報を参照可能に)

## ソース選択アルゴリズム

`files[]` から「どの分割単位で統合するか」を決めるルール。複雑な優先順位・閾値判定は
置かず、**現在入手できる最良の 1 本を選ぶか、識別子ごとに最新年度を集める**の 2 本道にする。

1. `format-preference` 順で使える形式を 1 つ選ぶ (見つからなければエラー)
2. 対象年度 (`--year`) 以前 (含む) に **`national` scope のファイルが 1 本でも存在する**なら、
   その中で最も新しい年度の national を採用し、結合は行わず終了
3. national が無いとき:
   - ファイルを `scope` + 識別子 (`pref_code` / `mesh_code` / `bureau_code` /
     `urban_area_code` / `muni_code` / `river_id`) でバケット化
   - **各バケットについて、対象年度以前で最新の 1 件**を選ぶ
   - 選ばれた全ファイルを結合する (scope が異なっていても union する。例えば
     `region` + `prefecture` の混在もそのまま結合)
4. 出力レコードに `source_year` 属性を付与し、どの年度のファイルから来たかを保持
5. 出力メタデータに `coverage_summary` を記録 (採用ファイル数、識別子ごとの年度分布、
   期待される識別子数との差分 ─ 例: `prefecture: 46/47, 沖縄のみ 2015 年版で補填`)

### 背景

この設計は「`coverage: full|partial` フラグで統合を事前ブロックする」案を置き換える。
KSJ の各データセットは「整備範囲」が HTML の自然文で曖昧に書かれていて自動判定が
難しく、手で partial を貼ると保守負荷が大きい。代わりに **「national が無いときは
ある分だけ統合する」** ルールにすれば、どのデータセットでも同じロジックが適用でき、
ユーザー側は `coverage_summary` を見て不足を把握できる。

「対象年度以前で最新」を採用する理由は、例えば A09 のように**本州 46 県が 2018 年版、
沖縄のみ 2015 年版**というケースで沖縄を落とさないため。全国を貼り合わせる目的では、
多少古い年度を混ぜてでも識別子カバレッジを埋めるほうが有用な結果になる。

年度混在が不都合な用途 (同一年度の断面を厳密に取りたい等) のため、`--strict-year`
フラグで「対象年度と完全一致する識別子のみ採用」を選べるようにする。デフォルトは
最新補填ありの挙動。

## CRS 変換の方針

- デフォルト目標 CRS: JGD2011 (EPSG:6668)
- 入力ファイルの `crs` (カタログから) から pyproj で変換
- 旧測地系 (EPSG:4301, Tokyo Datum) からの変換は pyproj 標準で実施 (数 m 誤差)
  - A03-2003, L03-a/b の旧年度、N04-1978 等が対象
  - 変換時に WARNING ログを出す
  - 高精度が必要な用途では TKY2JGD / PatchJGD グリッド適用が必要だが、MVP スコープ外

## スキーマ統一ロジック

分割ファイル間でカラム構成が微妙に異なるケースへの対処:

- **同一データセットの同一年度内では基本的に同スキーマ**。念のため和集合を取る
- カラム型: 全ファイルの型を検査し、最広義に昇格 (int → float → str)
- 欠損カラムは NaN で埋める
- カラム順序: 統合時に一定の順序で並べ直す (カタログ定義順 or 辞書順)
- 属性フィールド名の英語化は**行わない**

## 属性正規化の範囲

- **UTF-8 化**: Shift_JIS 配布のデータを UTF-8 に統一 (Phase 5)
- **スキーマ統一**: 分割ファイル間のカラム型・順序を揃える
- **欠損値正規化**: 独自欠損値コード (`-999` 等) を NaN に
- **DBF 254 バイト制限への対処** (A46/A47/A48 等): 住所が別カラムに分割されているケースで結合ルールを定義

## 出力メタデータ

GeoPackage と GeoParquet の両方に以下を埋め込む:

```json
{
  "dataset_code": "N03",
  "dataset_name": "行政区域",
  "version_year": "2025",
  "reference_date": "2025-01-01",
  "source_index": "https://nlftp.mlit.go.jp/ksj/index.html",
  "source_detail": "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2025.html",
  "license": "CC BY 4.0",
  "license_notes": "測量法に基づく国土地理院長承認 R6JHf 503",
  "target_crs": "EPSG:6668",
  "source_files": [
    {"url": "...", "scope": "prefecture", "pref_code": 1, "source_year": "2018", "crs": 6668, "format": "shp"}
  ],
  "coverage_summary": {
    "strategy": "national",          // "national" | "latest-fill" | "strict-year"
    "national_year": "2025",         // national 採用時のみ
    "prefecture": {"covered": 47, "expected": 47, "year_distribution": {"2025": 47}},
    "regional_bureau": null,
    "mesh": null,
    "notes": []                      // 例: "沖縄のみ 2015 版で補填"
  },
  "generated_at": "2026-04-18T15:30:00+09:00",
  "ksj_tool_version": "0.1.0"
}
```

埋込先:

- GeoPackage: `gpkg_metadata` テーブル (MIME `application/json`)
- GeoParquet: `key_value_metadata` の `ksj_metadata` キー

加えて `data/integrated/<code>-<year>.manifest.json` に同内容を出力。

## ラスタデータ

L03-b_r (土地利用細分メッシュラスタ版、GeoTIFF) は**ベクタ統合とは別扱い**。MVP 対象外。将来的に `ksj integrate-raster` として `gdal_merge` / VRT によるモザイク処理を実装する。
