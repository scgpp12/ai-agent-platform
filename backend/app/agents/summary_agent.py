"""
SummaryAgent —— 会話ログ・文書を要約する
=========================================

チェーンの下流としても、単体としても使える。
入力テキストを LLM に渡して要約するだけのシンプルな agent だが、
「上流(DataQuery)の出力を受け取って要約する」連携のデモで主役になる。

【设计注釈】
- SummaryAgent は「自分がどこからテキストを得たか」を知らない。
  入力が DBの検索結果でも、議事録でも、メール本文でも、同じ run() で処理できる。
  ＝関心の分離。これがチェーンの組み替え自由度を生む。
"""
from __future__ import annotations

from ..core.base_agent import AgentResult, BaseAgent
from ..providers.base import LLMProvider


class SummaryAgent(BaseAgent):
    name = "summary"
    description = "長い会話ログ・議事録・文書を、要点を絞って短く要約する。「まとめて」「要約して」系。"

    _KEYWORDS = ["要約", "まとめ", "サマリ", "要点", "整理して", "短く"]

    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    def can_handle(self, query: str, context: dict) -> float:
        hits = sum(1 for k in self._KEYWORDS if k in query)
        return min(0.9, 0.3 + 0.2 * hits) if hits else 0.05

    async def run(self, query: str, context: dict) -> AgentResult:
        # チェーンで来た場合、上流の構造化データが context["upstream"] にある。
        # それも要約材料に加える（状態共有の活用例）。
        upstream = context.get("upstream")
        material = query
        if upstream and upstream.get("rows"):
            material = query + "\n（元データ件数: " + str(len(upstream["rows"])) + "件）"

        system = (
            "あなたは要約担当。入力を日本語で3点以内の箇条書きに要約する。"
            "営業が一目で把握できるよう、数字や固有名詞は残す。"
        )
        summary = await self.llm.chat(system, material)
        return AgentResult(
            agent=self.name,
            output=summary,
            data={"source_chars": len(material)},
        )
