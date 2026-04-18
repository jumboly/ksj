"""統合結果を GeoPackage / GeoParquet として書き出す層。

Phase 4 では GeoPackage のみ。Phase 6 で GeoParquet を追加する。
"""

from ksj.writer.geopackage import write_layers

__all__ = ["write_layers"]
