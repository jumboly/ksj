# カタログ設計

## 設計方針

KSJ サイトの全量調査 (2026-04-18) で以下が確認された:

- **全データセット数: 131 件**(国土 / 政策区域 / 地域 / 交通 / 各種統計 の 5 カテゴリ)
- **URL テンプレートによる推測は不能**。データセットごとに完全に異なる:
  - N03: `https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03_2025/N03-20250101_XX_GML.zip`
  - L03-b: `L03-b-21_3036-jgd2011_GML.zip` (2 桁年、測地系サフィックス)
  - G04-a: `https://www.gsi.go.jp/GIS/g04a_11_3036-jgd_GML.zip` (**別ホスト**)
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
format_raw: "GML形式 (JPGIS 2014準拠)"
crs: 6668
crs_raw: "世界測地系 (JGD2011)"
```

## クローラの二段構え

`ksj catalog refresh` の動作:

```
Step 1: トップ index.html から 131 データセットのコード・名称・カテゴリ・詳細ページ URL を抽出
Step 2: 各詳細ページの展開可能テーブルから (scope, 地域/県/メッシュコード, crs, format, url, size) を抽出
```

- Step 2 は並列 2〜4、レート制限 1 req/sec で実行
- HTML 構造の手がかり:
  - `#prefectureNN` (NN=00 全国、01-47 都道府県、52-59 地方)
  - `a[href$=".zip"]`
  - 展開可能ブロック: `_arrow_drop_down_` アイコンを含む `<button>` / `<summary>`
  - テーブル列は「地域 / 測地系 / 年 / ファイル容量 / ファイル名 / ダウンロード」の 6 列構成

## scope 語彙（全 14 種）

| scope | 付随キー | 説明 | 代表データセット |
|---|---|---|---|
| `national` | — | 全国一括 | N03, W01, L01, N06 |
| `region` | `region_code` (52-59), `region_name` | 地方ブロック (東北/関東/中部/関西/中国/四国/九州) | W05, N03, S05-c |
| `regional_bureau` | `bureau_code` (82-89), `bureau_name` | 地方整備局 | A53 |
| `prefecture` | `pref_code` (01-47), `pref_name` | 都道府県 | 多数 |
| `urban_area` | `urban_area_code` (SYUTO/CHUBU/KINKI) | 三大都市圏 | A03, L03-b-u, L03-b-c, S05-a/b |
| `river` | `river_id`, `river_name` | 一級河川単位 | A31a |
| `municipality` | `muni_code`, `muni_name` | 市町村単位 | P24, A51 の一部 |
| `mesh1` | `mesh_code` (2桁) | 1次メッシュ (80km) | A31b |
| `mesh2` | `mesh_code` (4桁) | 2次メッシュ (10km) | A30a5, L03-a の一部 |
| `mesh3` | `mesh_code` (6桁) | 3次メッシュ (1km, 標準地域メッシュ) | G04-a, P09, mesh1000r6 |
| `mesh4` | `mesh_code` (7桁) | 4次メッシュ (500m, 1/2細分) | G04-c, L03-b, mesh500r6 |
| `mesh5` | `mesh_code` (8桁) | 5次メッシュ (250m, 1/4細分) | G04-d, mesh250r6 |
| `mesh6` | `mesh_code` (9桁) | 6次メッシュ (100m, 1/10細分) | L03-b_r, L03-b-u |
| `special` | `special_code`, `special_name` | 離島・特殊単位 | A19s, A20s, A21s |

## CRS の正規化

HTML の「測地系」列記載を EPSG コードに正規化:

| HTML 記載 | 名称 | EPSG | 備考 |
|---|---|---|---|
| 「旧測地系」「日本測地系」「Tokyo Datum」 | Tokyo Datum | 4301 | 明治以来、L03-a/b の 1976 版、A03-2003、N04-1978 |
| 「世界測地系 (JGD2000)」 | JGD2000 | 4612 | 2002〜2011 の標準 |
| 「世界測地系 (JGD2011)」 | JGD2011 | 6668 | 現行 (2011 東北地方太平洋沖地震後)。新しいデータセットのデフォルト |
| 「WGS84」 | WGS84 | 4326 | mesh1000h30, mesh500h30 シリーズで使用 |
| 「TP」 | 東京湾平均海面 | — | 標高の Z 軸基準 (G04 系)。CRS ではないが注記として保持 |

## フォーマットの語彙

HTML の「形式」列から抽出:

| 正規化 | HTML 記載例 | 対応データセット | pyogrio ドライバ |
|---|---|---|---|
| `gml_jpgis21` | 「GML形式 (JPGIS 2.1準拠)」 | 多数 (旧規格) | GML |
| `gml_jpgis2014` | 「GML形式 (JPGIS 2014準拠)」 | N02/N13/N05 等 2014 以降の新しめ | GML |
| `citygml` | 「CityGML形式」 | A55 のみ | CityGML (要検証) |
| `shp` | 「シェープファイル形式」 | ほぼ全件 | ESRI Shapefile |
| `geojson` | 「GeoJSON形式」 | 新しめ (A31a/A33/A40/A46/A47/A49/A51/P04/P29 等) | GeoJSON |
| `csv` | 「CSV形式」 | L01, L02 (地価系), mesh* 統計系 (完全属性版) | CSV + 座標列 |
| `geotiff` | ラスタ | L03-b_r のみ | GeoTIFF |

## カタログ YAML スキーマ

```yaml
# catalog/datasets.yaml
# 自動生成: ksj catalog refresh で再生成可能。差分はリポジトリにコミットする運用
schema_version: 1
generated_at: "2026-04-18T14:00:00+09:00"
source_index: https://nlftp.mlit.go.jp/ksj/index.html
total_datasets: 131

datasets:
  N03:
    name: 行政区域
    category: 政策区域 / 行政地域
    detail_page: https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2025.html
    geometry_types: [polygon]
    license: "CC BY 4.0"
    license_raw: "測量法に基づく国土地理院長承認 R6JHf 503"
    versions:
      "2025":
        reference_date: "2025-01-01"
        files:
          - scope: national
            crs: 6668
            crs_raw: "世界測地系 (JGD2011)"
            format: shp
            format_raw: "シェープファイル形式"
            url: https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03_2025/N03-20250101_GML.zip
            size_bytes: 447741952
          - scope: national
            crs: 6668
            format: geojson
            format_raw: "GeoJSON形式"
            url: https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03_2025/N03-20250101_GeoJSON.zip
          - scope: region
            region_code: "52"
            region_name: 東北地方
            crs: 6668
            format: shp
            url: https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03_2025/N03-20250101_52_GML.zip
          - scope: prefecture
            pref_code: 1
            pref_name: 北海道
            crs: 6668
            format: shp
            url: https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03_2025/N03-20250101_01_GML.zip

  L03-b:
    name: 土地利用細分メッシュ
    category: 国土 / 土地利用
    detail_page: https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b-2021.html
    geometry_types: [polygon]
    license_raw: "CC_BY_4.0 (新版) / 非商用 (旧版)"
    versions:
      "2021":
        files:
          - scope: mesh4
            mesh_code: "3036"
            crs: 6668
            format: shp
            url: https://nlftp.mlit.go.jp/ksj/gml/data/L03-b/L03-b-21_3036-jgd2011_GML.zip
      "1976":
        files:
          - scope: mesh4
            mesh_code: "4830"
            crs: 4301
            format: shp
            url: https://nlftp.mlit.go.jp/ksj/gml/data/L03-b/L03-b-76_4830-tky_GML.zip

  A53:
    name: 多段階浸水想定
    category: 政策区域 / 災害・防災
    notes: "東北/関東/中部/近畿/中国/四国/九州 整備局単位で配布。national 無し、bureau 別に統合される"
    versions:
      "2024":
        files:
          - scope: regional_bureau
            bureau_code: "82"
            bureau_name: 東北地方整備局
            crs: 6668
            format: shp
            url: https://nlftp.mlit.go.jp/ksj/gml/data/A53/A53-24_82_GML.zip

  A51:
    name: 雨水出水 (内水) 浸水想定区域
    notes: "47都道府県中9県のみ公開 (2024 時点)。統合時は coverage_summary に不足県が記録される"
    versions:
      "2024":
        files:
          - scope: municipality
            muni_code: "13101"
            muni_name: 千代田区
            crs: 6668
            format: shp
            url: https://...

  mesh1000h30:
    name: 1kmメッシュ別将来推計人口 (H30国政局推計)
    category: 各種統計
    notes: "WGS84 で配布。Shapefile 版は属性数制限で男女別削除、CSV が完全版"
    versions:
      "2018":
        files:
          - scope: mesh3
            format: shp
            crs: 4326
            crs_raw: "WGS84"
            attribute_caveat: "Shapefile 版は男女別属性を削除。完全版は CSV を取得"
            url: https://...

  A55:
    name: 都市計画決定情報
    notes: "唯一 CityGML 形式を提供"
    versions:
      "2024":
        files:
          - scope: prefecture
            pref_code: 13
            format: citygml
            format_raw: "CityGML形式"
            crs: 6668
            url: https://...
```

## 欠損値・特殊値の処理

一部データセットは独自の欠損値コードを使用している (データセット側のドキュメントから抽出):

- `-999` / `-998` / `-997`
- `9999` / `999999` / `99999998` / `99999999`
- `-1`

カタログの `null_values` フィールドでデータセット別に宣言し、読込時に NaN へ正規化する。
