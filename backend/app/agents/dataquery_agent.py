"""
DataQueryAgent —— 自然言語 → パラメータ → DB検索（SQLite/DynamoDB）
==================================================================

流れ:
  1. LLM に「自然文から検索パラメータ(JSON)を抜け」と指示（NL→構造化）
  2. パラメータを CustomerRepository に渡して安全に検索（SQLでもDynamoでも同じ呼び方）
  3. 結果を整形して返す（＋ data に生rows を載せてチェーンの下流へ渡せる）

【最重要の设计注釈：なぜ LLM に生SQL/生クエリを書かせないか】
  LLM に「SELECT文を書いて」と頼むと、インジェクションや DROP TABLE のリスク、
  存在しない列名でのエラーが起きる。プラットフォームとして危険。
  → LLM には「許可された項目の値(JSON)」だけ抜かせ、クエリ骨格は Repository が安全に組む。
    これは "structured extraction" パターン。RAG/NL2SQL の安全策の定番。

【リポジトリ抽象との関係】
  「どのDBで引くか」は本質ではないので CustomerRepository に分離した。
  このエージェントは Sqlite でも Dynamo でも無改修（差し替えは main の組み立てだけ）。
"""
from __future__ import annotations

import json
import re

from ..core.base_agent import AgentResult, BaseAgent
from ..data.customer_repo import (
    ALLOWED_INDUSTRIES,
    ALLOWED_REGIONS,
    CustomerRepository,
)
from ..providers.base import LLMProvider


class DataQueryAgent(BaseAgent):
    name = "data_query"
    description = "顧客データベースを条件検索する。地域/業種/ステータス別の顧客一覧、売上ランキング等の「○○の顧客を出して」系。"

    _KEYWORDS = ["顧客", "リスト", "一覧", "件", "売上", "ランキング", "トップ",
                 "地域", "業種", "アクティブ", "解約", "見込", "出して", "抽出", "検索"]

    def __init__(self, llm: LLMProvider, repo: CustomerRepository) -> None:
        self.llm = llm
        self.repo = repo  # ← DB依存はここに隔離。Sqlite/Dynamo を注入で選ぶ。

    def can_handle(self, query: str, context: dict) -> float:
        hits = sum(1 for k in self._KEYWORDS if k in query)
        return min(0.95, 0.2 + 0.2 * hits) if hits else 0.1

    async def _extract_params(self, query: str) -> dict:
        """LLM に検索条件を JSON で抜かせる。失敗してもルール抽出で補う（堅牢性）。"""
        system = (
            "あなたは検索パラメータ抽出器。ユーザー文から以下のJSONだけを出力する。\n"
            '{"region": null|地域名, "industry": null|業種名, "status": null|"active"|"prospect"|"churned",'
            ' "sort": null|"monthly_revenue"|"last_contact", "order": "desc"|"asc", "limit": 整数}\n'
            f"region候補={sorted(ALLOWED_REGIONS)} industry候補={sorted(ALLOWED_INDUSTRIES)}\n"
            "該当しない項目は null。説明文は書かずJSONのみ。"
        )
        raw = await self.llm.chat(system, query, temperature=0.0)
        params = self._safe_json(raw)
        return self._merge_rule_based(query, params)

    @staticmethod
    def _safe_json(raw: str) -> dict:
        try:
            s, e = raw.find("{"), raw.rfind("}")
            return json.loads(raw[s : e + 1]) if s >= 0 else {}
        except Exception:
            return {}

    def _merge_rule_based(self, query: str, params: dict) -> dict:
        """LLMが取りこぼした条件を素朴なルールで補完（LLM無し環境でも機能する保険）。"""
        if not params.get("region"):
            params["region"] = next((r for r in ALLOWED_REGIONS if r in query), None)
        if not params.get("industry"):
            params["industry"] = next((i for i in ALLOWED_INDUSTRIES if i in query), None)
        if not params.get("status"):
            if "解約" in query:
                params["status"] = "churned"
            elif "見込" in query:
                params["status"] = "prospect"
            elif "アクティブ" in query or "稼働" in query:
                params["status"] = "active"
        if not params.get("sort") and ("売上" in query or "ランキング" in query or "トップ" in query):
            params["sort"] = "monthly_revenue"
        m = re.search(r"(?:トップ|上位|top)\s*(\d+)", query, re.IGNORECASE)
        if m:
            params["limit"] = int(m.group(1))
        return params

    async def run(self, query: str, context: dict) -> AgentResult:
        params = await self._extract_params(query)
        result = await self.repo.query(params)  # ← 検証＋安全なクエリ組立は Repository が担当
        rows = result["rows"]

        if not rows:
            text = "条件に合致する顧客は見つかりませんでした。"
        else:
            lines = [
                f"- {r['name']}（{r['region']}/{r['industry']}, 月商{r['monthly_revenue']:,}円, {r['status']}）"
                for r in rows
            ]
            text = f"{len(rows)}件ヒットしました：\n" + "\n".join(lines)

        return AgentResult(
            agent=self.name,
            output=text,
            data={"rows": rows, "params": params},
            meta={"backend": self.repo.name, "debug": result["debug"]},
        )
