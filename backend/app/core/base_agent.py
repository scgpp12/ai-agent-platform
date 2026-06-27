"""
エージェント抽象（プラットフォームのコア設計）
================================================

【为什么需要这个抽象 / なぜこの抽象が必要か】

一个「AIエージェント統合プラットフォーム」最重要的资产不是某一个具体 Agent，
而是「能让任意 Agent 以统一方式接入、被统一调度」的契约（contract）。

如果没有统一契约，orchestrator（编排层）就必须 `if isinstance(agent, KnowledgeAgent): ...`
对每种 agent 写分支 —— 每加一个新 agent 就要改编排层。这违反「開放閉鎖原則(OCP)」：
对扩展开放、对修改封闭。

所以这里把每个 Agent 都收敛到 3 个能力上：
  - name / description : 自我描述（给路由层做意图分类、给前端做展示）
  - can_handle()       : 「我能处理这个请求吗？」—— 路由判断的依据（返回置信度）
  - run()              : 「真正处理」—— 统一的执行入口

只要新 agent 实现了 BaseAgent，平台本体（registry / orchestrator / API）**一行都不用改**。
这就是「插件化」的本质。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    """
    エージェント実行結果の統一フォーマット。

    把「输出」统一成一个结构，是为了让 orchestrator 在做 **链式调用(chain)** 时，
    能用同样的方式读取上一个 agent 的产物，再喂给下一个 agent。
    （例：DataQueryAgent.run() の data を SummaryAgent が受け取って要約する）
    """
    agent: str                                  # どのエージェントが出したか
    output: str                                 # 人间可读的最终文本
    data: dict[str, Any] = field(default_factory=dict)   # 构造化数据（链式调用时下游用）
    meta: dict[str, Any] = field(default_factory=dict)   # 调试信息（命中的文档、生成的SQL等）


class BaseAgent(ABC):
    """
    全エージェントが実装する共通インターフェース。

    継承先は最低限 name / description / run() を埋める。
    can_handle() はデフォルト 0.0（＝自分から手を挙げない）を返すので、
    ルーティングに参加しないユーティリティ的エージェントも作れる。
    """

    #: 一意な識別子（registry のキー、ルーティング結果のラベルになる）
    name: str = "base"
    #: LLM ルーティング(意図分類)のプロンプトに渡す説明文。ここが分類精度を左右する。
    description: str = "base agent"

    def can_handle(self, query: str, context: dict[str, Any]) -> float:
        """
        「この入力を自分が処理できるか」を 0.0〜1.0 の **自信度(score)** で返す。

        ▼ なぜ bool ではなく float(スコア)にするか:
          複数エージェントが「処理できる」と手を挙げたとき、bool だと優劣を付けられない。
          スコアにしておけば orchestrator は「一番スコアが高い奴」を選べる（＝競合解決ができる）。
          これは将来エージェントが増えても破綻しない設計。

        デフォルトは 0.0。ルールベース・ルーティングに参加したいエージェントだけ override する。
        """
        return 0.0

    @abstractmethod
    async def run(self, query: str, context: dict[str, Any]) -> AgentResult:
        """
        実処理。async にしているのは LLM / DB / 外部API はすべて I/O 待ちであり、
        プラットフォームとして多リクエストを捌くには非同期が前提だから。

        context には「共有状態」が入る（認証ユーザー、直前エージェントの出力、
        コネクタ群など）。これにより **エージェント間で状態を引き継げる**。
        """
        raise NotImplementedError
