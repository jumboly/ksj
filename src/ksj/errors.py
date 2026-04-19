"""CLI / MCP 共通のエラー正規化レイヤ。

handler は stdout に書かず、失敗時は ``HandlerError`` を raise する。
上位 (cli dispatcher など) が ``ErrorKind`` と ``exit_code`` を見て、
rich / json の各 renderer に渡して整形する。
"""

from __future__ import annotations

from enum import StrEnum


class ErrorKind(StrEnum):
    """JSON 出力の安定 contract として外部に露出する error_kind 語彙。

    増やすときは ``docs/json-output.md`` も合わせて更新する。
    """

    CATALOG_NOT_FOUND = "catalog_not_found"
    DATASET_NOT_FOUND = "dataset_not_found"
    NO_MATCHING_FILES = "no_matching_files"
    DOWNLOAD_FAILED = "download_failed"
    INTEGRATE_FAILED = "integrate_failed"
    INVALID_ARGUMENT = "invalid_argument"


class HandlerError(Exception):
    """handler が呼び出し側に返す「既知のエラー」。

    未知の例外はそのまま伝搬させ、traceback を出すのは top-level の責務に残す。
    既知エラーだけ ``error_kind`` で分類して JSON 契約に乗せる。
    """

    def __init__(self, kind: ErrorKind, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.exit_code = exit_code
