from __future__ import annotations

from pathlib import Path

from ksj.html_cache import cache_path, iter_cached, load, save, summary


def test_cache_path_preserves_host_and_path(tmp_path: Path) -> None:
    p = cache_path("https://nlftp.mlit.go.jp/ksj/index.html", tmp_path)
    assert p == tmp_path / "nlftp.mlit.go.jp" / "ksj" / "index.html"


def test_cache_path_different_host(tmp_path: Path) -> None:
    p = cache_path("https://www.gsi.go.jp/GIS/some.html", tmp_path)
    assert p == tmp_path / "www.gsi.go.jp" / "GIS" / "some.html"


def test_cache_path_directory_url_adds_index(tmp_path: Path) -> None:
    p = cache_path("https://example.com/dir/", tmp_path)
    assert p == tmp_path / "example.com" / "dir" / "index.html"


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    url = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2025.html"
    html = "<html><body>テスト</body></html>"
    saved = save(url, html, tmp_path)
    assert saved.exists()
    assert load(url, tmp_path) == html


def test_load_returns_none_for_missing(tmp_path: Path) -> None:
    assert load("https://example.com/nope.html", tmp_path) is None


def test_iter_cached_lists_all(tmp_path: Path) -> None:
    save("https://a.example/page.html", "a", tmp_path)
    save("https://b.example/sub/page.html", "bb", tmp_path)
    entries = list(iter_cached(tmp_path))
    assert len(entries) == 2
    urls = sorted(e.url for e in entries)
    assert urls == [
        "https://a.example/page.html",
        "https://b.example/sub/page.html",
    ]


def test_summary_counts_and_sums(tmp_path: Path) -> None:
    save("https://a.example/p1.html", "ab", tmp_path)
    save("https://a.example/p2.html", "cde", tmp_path)
    result = summary(tmp_path)
    assert result.file_count == 2
    assert result.total_bytes == 5


def test_summary_empty_dir(tmp_path: Path) -> None:
    result = summary(tmp_path)
    assert result.file_count == 0
    assert result.total_bytes == 0


def test_summary_missing_dir(tmp_path: Path) -> None:
    result = summary(tmp_path / "does-not-exist")
    assert result.file_count == 0
