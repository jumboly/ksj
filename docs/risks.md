# リスクと対処

| リスク | 影響 | 対処方針 |
|---|---|---|
| KSJ サイトの HTML 構造変更でスクレイパが壊れる | `catalog refresh` が失敗 | コミット済み YAML カタログで通常機能を維持。refresh 時に以下のヒューリスティックで異常検知: (1) 各詳細ページから URL が最低 1 件取れない、(2) データセット数が前回比 -10% 以上。差分レビュー後にコミット |
| 詳細ページ URL の年号付与がデータセット依存 | URL 構築を失敗 | トップ `index.html` から辿り、URL を直接組み立てない |
| 配布ホストが複数存在 (nlftp.mlit.go.jp + www.gsi.go.jp) | レート制御が効かない | URL をそのまま扱い、ホスト別にレート制限器を持つ (`nlftp`: 1req/s、`gsi`: 1req/s 独立) |
| 同一データセット内で年度により測地系が異なる (L03-a/b) | CRS 誤認識 | ファイル単位で `crs` を HTML から抽出して記録 |
| WGS84 / TP / CityGML 等の変則 | 正規化できない | `crs_raw` / `format_raw` を併記、未知値は警告出力。MVP では `format: unknown` として検出 |
| JPGIS 2.1 と 2014 の GML 混在 | 読込失敗 | pyogrio の GML ドライバが両方読めるか初回 refresh 後に検証。不足なら libxml で前処理 |
| 旧測地系 (EPSG:4301) からの変換精度 | 数 m の誤差 | pyproj 標準で変換、旧データには WARNING を出す。高精度が必要なら TKY2JGD/PatchJGD は将来フェーズ |
| 部分カバレッジデータ (A40 香川除外、A51 9 県のみ、A53 一部局欠、P32 東京/奈良/大分除外) | 「全国相当」の誤認 | カタログの `coverage: partial` + `coverage_notes` で明示、統合時に欠落リストを出力メタデータに記録 |
| Shapefile 属性数制限による情報欠落 (mesh* 統計系で男女別削除) | 属性欠如 | カタログの `attribute_caveat` で宣言、完全版が CSV にある場合は `--prefer-full-attributes` で CSV を選択可能に |
| DBF の 254 バイト住所制限 (A46/A47/A48) | 住所フィールドの切り詰め | 読込後に別記載列を結合する正規化ルールをデータセット毎に定義 |
| 欠損値の独自コード (`-999`/`-998`/`-997`/`9999`/`999999` 等) | 統計・可視化が歪む | カタログに `null_values` を持たせ、読込時に NaN に正規化 |
| ラスタデータ (L03-b_r のみ) | ベクタ統合では扱えない | MVP 対象外。`ksj integrate-raster` として将来追加 |
| 大規模メッシュデータ (mesh250r6: SHP 756MB / GML 1.9GB) | OOM | 分割を逐次読込、GeoPackage の `append` 書出でストリーミング結合。pandas で一気に concat しない |
| catalog refresh の所要時間 (131 詳細ページ × 1req/s ≒ 2.5 分) | 初回/全件更新で待たされる | 進捗を `catalog/.refresh_state.json` に記録、`--only <code>` で個別更新可 |
