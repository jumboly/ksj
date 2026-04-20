from __future__ import annotations

import pytest

from ksj.catalog._normalizers import (
    classify_scope,
    classify_url_format,
    detect_formats_in_text,
    infer_geometry_types,
    normalize_crs,
    normalize_license,
)


class TestDetectFormats:
    def test_single_jpgis_2014(self) -> None:
        text = "データフォーマット: GML形式（JPGIS2014準拠）"
        assert detect_formats_in_text(text) == ["gml_jpgis2014"]

    def test_multiple_formats(self) -> None:
        text = "GML形式（JPGIS 2.1準拠）、シェープファイル形式、GeoJSON形式"
        assert detect_formats_in_text(text) == ["gml_jpgis21", "shp", "geojson"]

    def test_citygml(self) -> None:
        assert "citygml" in detect_formats_in_text("CityGML形式で配布")

    def test_csv(self) -> None:
        assert "csv" in detect_formats_in_text("CSV形式")

    def test_gml_without_version(self) -> None:
        assert detect_formats_in_text("GML形式") == ["gml_jpgis21"]


class TestClassifyUrlFormat:
    def test_single_format_passthrough(self) -> None:
        fmt = classify_url_format(filename="foo_GML.zip", formats_in_page=["shp"])
        assert fmt == "shp"

    def test_unknown_when_no_formats(self) -> None:
        assert classify_url_format(filename="foo.zip", formats_in_page=[]) == "unknown"

    def test_shp_suffix_picks_shp(self) -> None:
        fmt = classify_url_format(
            filename="1km_mesh_2024_13_SHP.zip",
            formats_in_page=["gml_jpgis21", "shp", "geojson"],
        )
        assert fmt == "shp"

    def test_geojson_suffix_picks_geojson(self) -> None:
        fmt = classify_url_format(
            filename="1km_mesh_2024_47_GEOJSON.zip",
            formats_in_page=["gml_jpgis21", "shp", "geojson"],
        )
        assert fmt == "geojson"

    def test_gml_suffix_with_multi_formats_returns_multi(self) -> None:
        # N03 ケース: filename は _GML.zip だが中身に shp/geojson も同梱されている想定
        fmt = classify_url_format(
            filename="N03-20250101_GML.zip",
            formats_in_page=["gml_jpgis2014", "shp", "geojson"],
        )
        assert fmt == "multi"


class TestNormalizeCRS:
    def test_tokyo_datum(self) -> None:
        epsg, raw = normalize_crs(cell_text="日本測地系", filename="A03-03_SYUTO-tky_GML.zip")
        assert epsg == 4301
        assert raw == "日本測地系"

    def test_old_datum_label(self) -> None:
        epsg, _ = normalize_crs(cell_text="旧測地系", filename=None)
        assert epsg == 4301

    def test_world_datum_with_jgd2011_suffix(self) -> None:
        epsg, _ = normalize_crs(cell_text="世界測地系", filename="L03-b-21_3036-jgd2011_GML.zip")
        assert epsg == 6668

    def test_world_datum_with_jgd_suffix(self) -> None:
        epsg, _ = normalize_crs(cell_text="世界測地系", filename="L03-b-09_4830-jgd_GML.zip")
        assert epsg == 4612

    def test_world_datum_default_to_jgd2011(self) -> None:
        # N03 / mesh1000h30 等、filename に測地系サフィックスが無いケース
        epsg, _ = normalize_crs(cell_text="世界測地系", filename="N03-20250101_GML.zip")
        assert epsg == 6668

    def test_wgs84(self) -> None:
        epsg, _ = normalize_crs(cell_text="WGS84", filename=None)
        assert epsg == 4326


class TestClassifyScope:
    def test_national(self) -> None:
        hints = classify_scope(cell_text="全国")
        assert hints.scope == "national"

    def test_prefecture_from_name_with_suffix(self) -> None:
        hints = classify_scope(cell_text="東京都", dom_id="prefecture13")
        assert hints.scope == "prefecture"
        assert hints.pref_code == 13
        assert hints.pref_name == "東京"

    def test_prefecture_from_short_name_and_id(self) -> None:
        hints = classify_scope(cell_text="北海道", dom_id="prefecture01")
        assert hints.scope == "prefecture"
        assert hints.pref_code == 1

    def test_region(self) -> None:
        hints = classify_scope(cell_text="東北地方")
        assert hints.scope == "region"
        assert hints.region_name == "東北地方"

    def test_regional_bureau(self) -> None:
        hints = classify_scope(cell_text="東北地方整備局")
        assert hints.scope == "regional_bureau"
        assert hints.bureau_name == "東北地方整備局"

    @pytest.mark.parametrize(
        ("text", "code"),
        [
            ("首都圏", "SYUTO"),
            ("中部圏", "CHUBU"),
            ("近畿圏", "KINKI"),
            ("関東圏", "SYUTO"),
        ],
    )
    def test_urban_area_text_wins_over_dom_id(self, text: str, code: str) -> None:
        # A03 は td id="prefecture01" だが text に "首都圏" が入る。text を優先するのが正。
        hints = classify_scope(
            cell_text=text, dom_id="prefecture01", filename=f"A03-03_{code}-tky_GML.zip"
        )
        assert hints.scope == "urban_area"
        assert hints.urban_area_code == code

    def test_mesh1_from_4digit_numeric_text(self) -> None:
        # JIS X 0410 の 1 次メッシュは 4 桁 (80km 区画。例: 3036 = 奄美大島付近)
        hints = classify_scope(cell_text="3036")
        assert hints.scope == "mesh1"
        assert hints.mesh_code == "3036"

    def test_mesh1_from_dom_id(self) -> None:
        # L03-b: id="a3036-1" のメッシュコード 3036 は 1 次メッシュ
        hints = classify_scope(cell_text="3036", dom_id="a3036-1")
        assert hints.scope == "mesh1"
        assert hints.mesh_code == "3036"

    def test_mesh2_from_6digit_numeric_text(self) -> None:
        # 2 次メッシュは 6 桁 (10km 区画)
        hints = classify_scope(cell_text="533945")
        assert hints.scope == "mesh2"
        assert hints.mesh_code == "533945"


class TestInferGeometryTypes:
    @pytest.mark.parametrize(
        "name, expected",
        [
            ("行政区画（ポリゴン）", ["polygon"]),
            ("道路（ライン）", ["line"]),
            ("ダム（ポイント）", ["point"]),
            ("景観計画区域（ポリゴン）（ポイント）", ["polygon", "point"]),
            ("河川（ライン）（ポイント）", ["line", "point"]),
            ("土地利用細分メッシュ（ラスタ版）", ["raster"]),
            ("土地利用細分メッシュ", []),  # カッコ表記なしは保守的に空
            ("3次メッシュ", []),
        ],
    )
    def test_parenthesized_markers(self, name: str, expected: list[str]) -> None:
        assert infer_geometry_types(name) == expected


class TestNormalizeLicense:
    def test_empty_returns_unknown(self) -> None:
        profile = normalize_license("")
        assert profile.kind == "unknown"
        assert profile.commercial_use == "unknown"

    def test_none_returns_unknown(self) -> None:
        profile = normalize_license(None)
        assert profile.kind == "unknown"

    def test_non_commercial_standalone(self) -> None:
        profile = normalize_license("非商用")
        assert profile.kind == "non_commercial"
        assert profile.commercial_use is False
        assert profile.attribution_required is True

    def test_non_commercial_with_publication_note(self) -> None:
        # W01, P17 等で観測される: 「非商用 本データは有償刊行物を使用し〜」
        profile = normalize_license("非商用 本データは有償刊行物を使用し作成したものですので商用利用はできません。")
        assert profile.kind == "non_commercial"
        assert any("有償刊行物" in c for c in profile.constraints)

    def test_cc_by_4_0(self) -> None:
        # N13, L03-b 等の標準オープンデータ
        profile = normalize_license("オープンデータ（CC_BY_4.0）")
        assert profile.kind == "cc_by_4_0"
        assert profile.commercial_use is True
        assert profile.derivative_works is True

    def test_cc_by_4_0_partial(self) -> None:
        # A13, A12 等の典型的な一部制限パターン
        profile = normalize_license(
            "オープンデータ（CC_BY_4.0（一部制限）） 【重要：データ利用時の注意事項】 岡山県のみ非商用"
        )
        assert profile.kind == "cc_by_4_0_partial"
        assert profile.commercial_use == "conditional"
        assert any("岡山県" in c for c in profile.constraints)

    def test_cc_by_typo_variant(self) -> None:
        # A50 のタイポ: CC_B.Y_4.0（一部制限）
        profile = normalize_license(
            "オープンデータ（CC_B.Y_4.0（一部制限）） 【重要：データ利用時の注意事項】"
        )
        assert profile.kind == "cc_by_4_0_partial"

    def test_commercial_ok(self) -> None:
        profile = normalize_license("商用可")
        assert profile.kind == "commercial_ok"
        assert profile.commercial_use is True

    def test_site_terms_only(self) -> None:
        # A31a: CC_BY 明示なし、利用規約のみ参照
        profile = normalize_license(
            "国土数値情報ダウンロードサイトコンテンツ利用規約 のほか、都道府県毎に定められた利用条件を必ず遵守するようにしてください。"
        )
        assert profile.kind == "site_terms_only"
        assert any("都道府県毎" in c or "市区町村" in c for c in profile.constraints)

    def test_year_branch_onwards_vs_else(self) -> None:
        # L01: 「2019年以降：CC_BY_4.0 / 上記以外：商用可」
        profile = normalize_license(
            "2019年（平成31年）以降：オープンデータ（CC_BY_4.0）\n上記以外：商用可"
        )
        assert profile.kind == "mixed_by_year"
        assert profile.commercial_use == "conditional"
        assert profile.by_year is not None
        assert "2019" in profile.by_year
        assert profile.by_year["2019"].kind == "cc_by_4_0"
        assert "_else" in profile.by_year
        assert profile.by_year["_else"].kind == "commercial_ok"

    def test_year_branch_non_commercial_else(self) -> None:
        # A09: 「2018年度：CC_BY_4.0 / 上記以外：非商用」
        profile = normalize_license(
            "2018年度（平成30年度）：オープンデータ（CC_BY_4.0）\n上記以外：非商用"
        )
        assert profile.kind == "mixed_by_year"
        assert profile.by_year is not None
        assert profile.by_year.get("2018", None) is not None
        assert profile.by_year["2018"].kind == "cc_by_4_0"
        assert profile.by_year["_else"].kind == "non_commercial"

    def test_year_branch_multi_year_keys(self) -> None:
        # P29: 「2023年度、2021年度：CC_BY_4.0 / 2013年度：非商用」
        profile = normalize_license(
            "2023年度（令和5年度）、2021年度（令和3年度）：オープンデータ（CC_BY_4.0）\n2013年度（平成25年度）：非商用"
        )
        assert profile.kind == "mixed_by_year"
        assert profile.by_year is not None
        # 1 番目の年 (2023) が代表キー、2013 も独立キーになる
        assert "2023" in profile.by_year
        assert profile.by_year["2023"].kind == "cc_by_4_0"
        assert "2013" in profile.by_year
        assert profile.by_year["2013"].kind == "non_commercial"

    def test_maintenance_year_not_treated_as_branch(self) -> None:
        # N06: 「整備年度が2018年度以降〜」はライセンス分岐でなく属性条件
        profile = normalize_license(
            "オープンデータ（CC_BY_4.0（一部制限）） 【重要：データ利用時の注意事項】 ＜整備年度が2018年度（平成30年度）以降のものを〜"
        )
        assert profile.kind == "cc_by_4_0_partial"
