from __future__ import annotations

import pytest

from ksj.catalog._normalizers import (
    classify_scope,
    classify_url_format,
    detect_formats_in_text,
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

    def test_mesh2_from_numeric_text(self) -> None:
        hints = classify_scope(cell_text="3036")
        assert hints.scope == "mesh2"
        assert hints.mesh_code == "3036"

    def test_mesh2_from_dom_id(self) -> None:
        # L03-b: id="a3036-1"
        hints = classify_scope(cell_text="3036", dom_id="a3036-1")
        assert hints.scope == "mesh2"
        assert hints.mesh_code == "3036"
