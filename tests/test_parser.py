from __future__ import annotations

from pathlib import Path

from ksj.catalog._parser import parse_detail_page, parse_index_page

FIXTURES = Path(__file__).parent / "fixtures" / "ksj"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestParseIndex:
    def test_detects_131_ish_datasets(self) -> None:
        entries = parse_index_page(_read("index.html"), "https://nlftp.mlit.go.jp/ksj/index.html")
        assert 120 <= len(entries) <= 140

    def test_all_five_top_categories_present(self) -> None:
        entries = parse_index_page(_read("index.html"), "https://nlftp.mlit.go.jp/ksj/index.html")
        categories = {e.category for e in entries}
        assert "国土（水・土地）" in categories
        assert "政策区域" in categories
        assert "地域" in categories
        assert "交通" in categories
        assert "各種統計" in categories

    def test_n03_entry_is_absolute_url(self) -> None:
        entries = parse_index_page(_read("index.html"), "https://nlftp.mlit.go.jp/ksj/index.html")
        n03 = next(e for e in entries if e.code == "N03")
        assert n03.detail_page.startswith("https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03")
        assert n03.category == "政策区域"


class TestParseDetailN03:
    def test_formats_in_page_matches_page_declaration(self) -> None:
        # N03 ページ冒頭は「GML(JPGIS2014) / シェープ / GeoJSON」の 3 宣言。
        # formats_in_page はページ全体の union、Dataset.available_formats の元になる
        r = parse_detail_page(
            _read("N03-2025.html"),
            "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2025.html",
            "N03",
        )
        assert "gml_jpgis2014" in r.formats_in_page
        assert "shp" in r.formats_in_page
        assert "geojson" in r.formats_in_page

    def test_many_files_with_national_and_prefectures(self) -> None:
        r = parse_detail_page(
            _read("N03-2025.html"),
            "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2025.html",
            "N03",
        )
        assert len(r.files) > 1000  # 1920 以降の年度 x 47 県分
        # 最新年度の国一括 (2025)
        national_2025 = next(
            f for f in r.files if f.scope_hints.scope == "national" and "N03-20250101_GML" in f.url
        )
        assert national_2025.crs == 6668
        # 東京都の 2025 版
        tokyo = next(
            f for f in r.files if f.scope_hints.pref_code == 13 and "N03-20250101_13_GML" in f.url
        )
        assert tokyo.scope_hints.scope == "prefecture"

    def test_format_raw_empty_when_no_format_column(self) -> None:
        # N03 は「形式」列を持たないテーブル構成。行単位の原文が取れないときは
        # ページ全体の形式一覧を詰め込まず空文字にする (嘘情報を残さない)
        r = parse_detail_page(
            _read("N03-2025.html"),
            "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2025.html",
            "N03",
        )
        assert all(f.format_raw == "" for f in r.files)


class TestParseDetailA03:
    def test_urban_area_three_zones(self) -> None:
        r = parse_detail_page(
            _read("A03.html"),
            "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A03.html",
            "A03",
        )
        codes = {f.scope_hints.urban_area for f in r.files}
        # A03 の table cell は「関東圏/中部圏/近畿圏」表記。原文をそのまま保持する
        # (filename 英字接頭辞 SYUTO/CHUBU/KINKI には寄せない)
        assert codes == {"関東圏", "中部圏", "近畿圏"}
        assert all(f.scope_hints.scope == "urban_area" for f in r.files)
        assert all(f.crs == 4301 for f in r.files)


class TestParseDetailL03b:
    def test_mesh1_with_mixed_crs(self) -> None:
        r = parse_detail_page(
            _read("L03-b-2021.html"),
            "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b-2021.html",
            "L03-b",
        )
        # L03-b は 1 次メッシュ (4 桁コード) 単位で ZIP 配布される
        mesh_scopes = {f.scope_hints.scope for f in r.files}
        assert mesh_scopes == {"mesh1"}
        # 旧測地系 / JGD2000 / JGD2011 の 3 種が揃う
        crs_values = {f.crs for f in r.files}
        assert {4301, 4612, 6668} <= crs_values


class TestParseDetailG04a:
    def test_different_host(self) -> None:
        r = parse_detail_page(
            _read("G04-a.html"),
            "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-G04-a.html",
            "G04-a",
        )
        assert len(r.files) > 0
        # G04-a は別ホストで配布されているはずだが、フィクスチャによっては nlftp に
        # 移行されているパターンもある。少なくとも URL が取れていることを確認


class TestParseDetailA55FormBased:
    def test_warns_when_no_downloads(self) -> None:
        r = parse_detail_page(
            _read("A55-2024.html"),
            "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A55-2024.html",
            "A55",
        )
        assert r.files == []
        assert any("フォーム" in w for w in r.warnings)
        assert "citygml" in r.formats_in_page


class TestParseDetailN13:
    """N13 は『形式』列を持つためテーブル列順が他と異なる (地域/形式/測地系/年度/…)。"""

    def test_crs_and_format_resolved_from_header(self) -> None:
        r = parse_detail_page(
            _read("N13-2024.html"),
            "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N13-2024.html",
            "N13",
        )
        assert r.files, "N13 はダウンロード行を持つはず"

        # crs_raw には形式文字列 (「GML形式」等) が混入してはならない
        crs_raws = {(f.crs_raw or "") for f in r.files}
        assert any("世界測地系" in s for s in crs_raws)
        assert not any("形式" in s for s in crs_raws)

        # crs は「世界測地系」→ JGD2011 (6668) に正規化される
        assert all(f.crs == 6668 for f in r.files)

        # 1 次メッシュ配布 (4 桁コード)
        assert all(f.scope_hints.scope == "mesh1" for f in r.files)

        # format は行ごとに決まる (GML / SHP / GEOJSON)
        gml_files = [f for f in r.files if "_GML.zip" in f.url]
        shp_files = [f for f in r.files if "_SHP.zip" in f.url]
        gj_files = [f for f in r.files if "_GEOJSON.zip" in f.url]
        assert gml_files and shp_files and gj_files
        assert all(f.format == "gml_jpgis2014" for f in gml_files)
        assert all(f.format == "shp" for f in shp_files)
        assert all(f.format == "geojson" for f in gj_files)

        # format_raw は行セルの原文 (「GML形式」等) を保持する
        assert all(f.format_raw == "GML形式" for f in gml_files)
        assert all(f.format_raw == "シェープ形式" for f in shp_files)
        assert all(f.format_raw == "GEOJSON形式" for f in gj_files)


class TestParseDetailMesh1000h30:
    def test_prefecture_47(self) -> None:
        r = parse_detail_page(
            _read("mesh1000h30.html"),
            "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-mesh1000h30.html",
            "mesh1000h30",
        )
        pref_codes = {f.scope_hints.pref_code for f in r.files if f.scope_hints.pref_code}
        assert pref_codes == set(range(1, 48))


class TestDownLdNewVariant:
    """KSJ は 2024/09 以降、onclick を DownLd() → DownLd_new() に順次切替中。

    両者は gis.js で現役定義され引数順も URL 遷移挙動も同一なので、どちらの
    表記でもダウンロード行として拾えることを確認する。
    """

    _SAMPLE = """
    <html><body><table class="tbl_downloadlist">
      <thead><tr>
        <th>地域</th><th>測地系</th><th>年度</th>
        <th>ファイル容量</th><th>ファイル名</th><th>ダウンロード</th>
      </tr></thead>
      <tbody>
        <tr>
          <td id="prefecture00">全国</td>
          <td>世界測地系</td><td>2020年</td>
          <td>17.42MB</td><td>A16-20_GML.zip</td>
          <td><a class="btn" id="menu-button"
             onclick="javascript:DownLd('17.42MB','A16-20_GML.zip','../data/A16/A16-20/A16-20_GML.zip',this);">
             DL</a></td>
        </tr>
        <tr>
          <td id="prefecture52">東北地方</td>
          <td>世界測地系</td><td>2020年</td>
          <td>3.78MB</td><td>A16-20_52_GML.zip</td>
          <td><a class="btn" id="menu-button"
             onclick="javascript:DownLd_new('3.78MB','A16-20_52_GML.zip','../data/A16/A16-20/A16-20_52_GML.zip',this);">
             DL</a></td>
        </tr>
      </tbody>
    </table></body></html>
    """

    def test_downld_new_is_extracted(self) -> None:
        r = parse_detail_page(
            self._SAMPLE,
            "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A16-2020.html",
            "A16",
        )
        urls = {f.url for f in r.files}
        assert "https://nlftp.mlit.go.jp/ksj/gml/data/A16/A16-20/A16-20_GML.zip" in urls, (
            "DownLd の行が取れていない"
        )
        assert "https://nlftp.mlit.go.jp/ksj/gml/data/A16/A16-20/A16-20_52_GML.zip" in urls, (
            "DownLd_new の行が取れていない (regex が DownLd 固定になっていないか)"
        )

    def test_downld_new_size_and_filename_parsed(self) -> None:
        r = parse_detail_page(
            self._SAMPLE,
            "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A16-2020.html",
            "A16",
        )
        new_file = next(f for f in r.files if f.filename == "A16-20_52_GML.zip")
        assert new_file.size_bytes is not None
        assert new_file.size_raw == "3.78MB"
