"""JSON 出力モードの整形実装。

成功時は ``{"ok": true, "command": ..., "data": ...}``、失敗時は
``{"ok": false, "exit_code": ..., "error_kind": ..., "message": ...}`` を
stdout に 1 件ずつ書き出す。契約は ``docs/json-output.md`` を正とする。
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ksj.errors import HandlerError


def _default(value: Any) -> Any:
    """``json.dumps`` が扱えない型を文字列 / 素の dict に落とす。

    ``dataclass`` は asdict で再帰的に dict 化、pydantic は model_dump、
    Path / datetime は文字列化。ここで吸収することで handler / renderer 側は
    変換を意識せず生オブジェクトを渡せる。
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    raise TypeError(f"JSON serialization not supported for type {type(value).__name__}")


def _dump(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=_default))
    sys.stdout.write("\n")
    sys.stdout.flush()


def success(command: str, data: Any) -> None:
    _dump({"ok": True, "command": command, "data": data})


def failure(error: HandlerError) -> None:
    _dump(
        {
            "ok": False,
            "exit_code": error.exit_code,
            "error_kind": error.kind.value,
            "message": error.message,
        }
    )
