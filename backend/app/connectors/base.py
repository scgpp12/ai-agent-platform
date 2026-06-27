"""
外部サービス・コネクタ抽象
===========================

【为什么 / なぜ】

平台经常要让 agent 调用「外部 SaaS」：日程(Calendar)、聊天(Slack/LINE)、CRM…。
如果 agent 直接 `requests.post("https://api.xxx.com")`，会有三个问题：
  1. 各 agent 各写各的鉴权/重试/超时 → 重复且易错
  2. 难以 mock → 测试要打真网络
  3. 换供应商要改 agent

所以抽象出 `Connector`：定义「能力(action)」与「调用方式(invoke)」，
具体实现（真实 API or スタブ）放在子类。agent 只通过 ConnectorRegistry 拿 connector，
按统一方式 `invoke(action, params)` 调用 —— 这正是「外部サービスをエージェントが呼ぶ」的标准结构。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Connector(ABC):
    name: str = "connector"
    #: このコネクタが提供する操作の一覧（ルーティングや /connectors 表示に使う）
    actions: list[str] = []

    @abstractmethod
    async def invoke(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """action 名 + パラメータで外部サービスを呼ぶ。戻りは dict（JSON相当）。"""
        raise NotImplementedError


class ConnectorRegistry:
    """コネクタの登録簿（AgentRegistry と同じ思想の、外部サービス版）。"""

    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        self._connectors[connector.name] = connector

    def get(self, name: str) -> Connector:
        if name not in self._connectors:
            raise KeyError(f"未登録のコネクタ: {name!r}")
        return self._connectors[name]

    def all(self) -> list[Connector]:
        return list(self._connectors.values())
