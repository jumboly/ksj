"""ベクタファイルを読み込む層。pyogrio + GDAL /vsizip/ で ZIP を直接読む。"""

from ksj.reader.vector import (
    NoMatchingFormatError,
    VectorLayer,
    default_encoding_for,
    read_zip,
)

__all__ = [
    "NoMatchingFormatError",
    "VectorLayer",
    "default_encoding_for",
    "read_zip",
]
