"""
AgentRegistry —— エージェントのプラグイン登録簿
=================================================

【为什么要有 Registry / なぜレジストリが要るか】

平台不应该「认识」每一个具体 agent。它只应该认识「一组实现了 BaseAgent 的对象」。
Registry 就是这层间接（indirection）：

  - 启动时：把各个 agent 实例 register() 进来（一处集中装配）
  - 运行时：orchestrator 只通过 registry.all() / registry.get(name) 拿 agent

好处：
  1. 新增 agent = 写一个类 + 在装配处 register 一行，**编排层和 API 层零改动**。
  2. 可以做「特性开关」：某 agent 出问题，注释掉它的 register 即可下线，平台照常运行。
  3. 测试时可以注册 mock agent，隔离测试编排逻辑。

这其实就是「服务定位器(Service Locator) / プラグインレジストリ」模式，
LangChain 等框架内部也是类似思路，只是我们这里自己手写以看清本质。
"""
from __future__ import annotations

from .base_agent import BaseAgent


class AgentRegistry:
    def __init__(self) -> None:
        # name -> agent 实例。用 dict 保证 name 唯一、O(1) 取用。
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        """エージェントを登録する。name 重複は設計ミスなので即エラーにする。"""
        if agent.name in self._agents:
            raise ValueError(f"agent name 重複: {agent.name!r} は既に登録済み")
        self._agents[agent.name] = agent

    def get(self, name: str) -> BaseAgent:
        """名前で取り出す。存在しなければ明示的にエラー（暗黙の None で死なせない）。"""
        if name not in self._agents:
            raise KeyError(f"未登録のエージェント: {name!r} / 登録済み={list(self._agents)}")
        return self._agents[name]

    def all(self) -> list[BaseAgent]:
        """全エージェント。ルーティング(候補列挙)・/agents 一覧API で使う。"""
        return list(self._agents.values())

    def names(self) -> list[str]:
        return list(self._agents.keys())
