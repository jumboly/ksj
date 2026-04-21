from __future__ import annotations

import pytest

from ksj.catalog._normalizers import (
    classify_scope,
    classify_url_format,
    detect_formats_in_text,
    infer_geometry_types,
    infer_version_year,
    normalize_crs,
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

    def test_world_datum_no_suffix_defaults_to_jgd2011_even_for_old_year(self) -> None:
        # 「世界測地系」+ suffix 無しは年度に関わらず 6668 既定。
        # KSJ は単一配信の pre-2011 データも JGD2011 に再投影しているため
        # (L01 1983 等の 40+ 年前データも全て suffix 無し + 6668)。
        epsg, _ = normalize_crs(cell_text="世界測地系", filename="L01-10_01_GML.zip")
        assert epsg == 6668


class TestClassifyScope:
    def test_national(self) -> None:
        hints = classify_scope(cell_text="全国")
        assert hints.scope == "national"

    def test_prefecture_from_name_with_suffix(self) -> None:
        # pref_name は text 原文をそのまま保存する (「東京都」→「東京」等のサフィックス
        # 除去はしない)。pref_code で JIS 標準識別子を別途保持。
        hints = classify_scope(cell_text="東京都", dom_id="prefecture13")
        assert hints.scope == "prefecture"
        assert hints.pref_code == 13
        assert hints.pref_name == "東京都"

    def test_prefecture_from_short_name_and_id(self) -> None:
        hints = classify_scope(cell_text="北海道", dom_id="prefecture01")
        assert hints.scope == "prefecture"
        assert hints.pref_code == 1

    def test_region(self) -> None:
        hints = classify_scope(cell_text="東北地方")
        assert hints.scope == "region"
        assert hints.region == "東北地方"

    def test_regional_bureau(self) -> None:
        # 原文保持: 日本語名が bureau フィールドに入る (数値 alias しない)
        hints = classify_scope(cell_text="東北地方整備局")
        assert hints.scope == "regional_bureau"
        assert hints.bureau == "東北地方整備局"

    @pytest.mark.parametrize(
        ("text", "filename_token"),
        [
            ("首都圏", "SYUTO"),
            ("中部圏", "CHUBU"),
            ("近畿圏", "KINKI"),
            # 「関東圏」は KSJ A03 の table cell で観測される表記揺れだが、「首都圏」に
            # 寄せずそのまま保存する (同一視は downstream/LLM 側の責務)
            ("関東圏", "SYUTO"),
        ],
    )
    def test_urban_area_text_is_preserved_as_is(self, text: str, filename_token: str) -> None:
        # A03 は td id="prefecture01" だが text を優先する (id 属性の流用を避けるため)
        hints = classify_scope(
            cell_text=text,
            dom_id="prefecture01",
            filename=f"A03-03_{filename_token}-tky_GML.zip",
        )
        assert hints.scope == "urban_area"
        assert hints.urban_area == text

    def test_urban_area_from_filename_when_text_absent(self) -> None:
        # HTML text が無い場合に filename の英字接頭辞 (SYUTO/CHUBU/KINKI) で urban_area 判定。
        # 現行カタログでは発火する entry は無いが保険
        hints = classify_scope(cell_text="", filename="A03-03_CHUBU-tky_GML.zip")
        assert hints.scope == "urban_area"
        assert hints.urban_area == "CHUBU"

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

    @pytest.mark.parametrize(
        ("dom_code", "expected_scope", "expected_code_attr", "expected_value"),
        [
            # 都道府県 01-47 の境界
            ("01", "prefecture", "pref_code", 1),
            ("47", "prefecture", "pref_code", 47),
            # 地方区分 51-59 の境界 (text 無しなら dom id 数値が region に入る)
            ("51", "region", "region", "51"),
            ("59", "region", "region", "59"),
            # 整備局 81-89 の境界 (DOM id fallback 経路、text 無し時は数値が bureau に入る)
            ("81", "regional_bureau", "bureau", "81"),
            ("89", "regional_bureau", "bureau", "89"),
        ],
    )
    def test_dom_id_valid_boundaries(
        self,
        dom_code: str,
        expected_scope: str,
        expected_code_attr: str,
        expected_value: object,
    ) -> None:
        # text 空 + dom_id のみの経路で区間判定が働くことを確認
        hints = classify_scope(cell_text="", dom_id=f"prefecture{dom_code}")
        assert hints.scope == expected_scope
        assert getattr(hints, expected_code_attr) == expected_value

    @pytest.mark.parametrize("dom_code", ["48", "49", "50", "60", "79", "80", "90", "99"])
    def test_dom_id_unknown_gaps_fallback_to_special(self, dom_code: str) -> None:
        # 旧実装では 48-50 は region, 80/90 は bureau 化して silent に誤分類していた。
        # 未使用帯は明示的に special へフォールバックさせる。
        hints = classify_scope(cell_text="", dom_id=f"prefecture{dom_code}")
        assert hints.scope == "special"

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


class TestInferVersionYear:
    def test_year_text_in_raw(self) -> None:
        assert infer_version_year(year_raw="2025年4月", filename="any.zip") == "2025"

    def test_raw_priority_over_filename(self) -> None:
        assert infer_version_year(year_raw="2018年", filename="foo-2025-bar.zip") == "2018"

    @pytest.mark.parametrize(
        ("era_text", "expected"),
        [
            ("平成21年度", "2009"),
            ("昭和60年", "1985"),
            ("令和3年度", "2021"),
        ],
    )
    def test_era_conversion(self, era_text: str, expected: str) -> None:
        assert infer_version_year(year_raw=era_text, filename="any.zip") == expected

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("N03-20250101_GML.zip", "2025"),
            ("L03-a-1976_5339_GML.zip", "1976"),
            # 旧実装 (50 閾値ヒューリスティック) で 1950/2049 に誤変換していた退行テスト
            ("X01-20500101_GML.zip", "2050"),
            ("X01-19490101_GML.zip", "1949"),
        ],
    )
    def test_4digit_year_in_filename(self, filename: str, expected: str) -> None:
        assert infer_version_year(year_raw=None, filename=filename) == expected

    @pytest.mark.parametrize(
        "filename",
        [
            # 2 桁年度のみは century 特定不能
            "foo-25-bar.zip",
            "catalog.zip",
        ],
    )
    def test_unknown_fallback(self, filename: str) -> None:
        assert infer_version_year(year_raw=None, filename=filename) == "unknown"
