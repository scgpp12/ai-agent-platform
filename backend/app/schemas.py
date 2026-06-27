"""API の入出力スキーマ（pydantic）。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., description="ユーザー入力")
    route_mode: Literal["rule", "llm"] = Field(
        "rule", description="ルーティング戦略: rule=ルールベース / llm=意図分類"
    )


class ChatResponse(BaseModel):
    agent: str
    output: str
    data: dict[str, Any] = {}
    error: str | None = None
    trace: dict[str, Any] = {}


class ChainResponse(BaseModel):
    agents: list[str]
    output: str
    data: dict[str, Any] = {}
    trace: dict[str, Any] = {}
