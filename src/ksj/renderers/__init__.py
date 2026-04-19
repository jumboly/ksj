"""出力整形レイヤ: handler 返却値を rich Table または JSON に書き出す。"""

from enum import Enum


class OutputFormat(Enum):
    """CLI の ``--format`` / ``--json`` フラグで選ばれる出力モード。"""

    RICH = "rich"
    JSON = "json"


__all__ = ["OutputFormat"]
