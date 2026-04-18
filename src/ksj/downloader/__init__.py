"""KSJ ZIP 配布のダウンローダ層 (Phase 3)。

- `client`: httpx 非同期、レート制限、Range レジュームによる ZIP 取得
- `selector`: カタログ FileEntry の絞り込み (crs / format preference)
- `manifest`: data/manifest.json の読み書き
"""

from ksj.downloader.client import (
    DownloadResult,
    DownloadTarget,
    download_file,
    download_many,
    filename_from_url,
)
from ksj.downloader.manifest import (
    DatasetManifest,
    Manifest,
    ManifestEntry,
    load_manifest,
    save_manifest,
)
from ksj.downloader.selector import pick_targets

__all__ = [
    "DatasetManifest",
    "DownloadResult",
    "DownloadTarget",
    "Manifest",
    "ManifestEntry",
    "download_file",
    "download_many",
    "filename_from_url",
    "load_manifest",
    "pick_targets",
    "save_manifest",
]
