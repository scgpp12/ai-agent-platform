"""
カレンダーAPI スタブ（モック外部サービス）
==========================================

実際の Google Calendar / Outlook API を呼ぶ代わりに、メモリ上で予定を管理する。
本物に差し替えるときは invoke() の中身を SDK 呼び出しにするだけ
（インターフェース＝Connector は変えない）。

「外部サービスをエージェントが呼ぶ」構造のデモ用。営業フォローの予定登録などを想定。
"""
from __future__ import annotations

from typing import Any

from .base import Connector


class CalendarStubConnector(Connector):
    name = "calendar"
    actions = ["create_event", "list_events"]

    def __init__(self) -> None:
        # 実APIの代わりのインメモリ・ストア
        self._events: list[dict[str, Any]] = []
        self._seq = 0

    async def invoke(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "create_event":
            self._seq += 1
            event = {
                "id": f"evt-{self._seq:04d}",
                "title": params.get("title", "（無題）"),
                "date": params.get("date", "未定"),
                "attendees": params.get("attendees", []),
                "note": params.get("note", ""),
            }
            self._events.append(event)
            # 実APIなら 201 Created 相当
            return {"status": "created", "event": event}

        if action == "list_events":
            return {"status": "ok", "events": list(self._events)}

        raise ValueError(f"calendar コネクタが知らない action: {action!r}")
