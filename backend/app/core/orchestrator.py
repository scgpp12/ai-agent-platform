"""
オーケストレーション層（プラットフォームの核心）
=================================================

責務は3つだけ:
  1. ルーティング: 入力を「どのエージェントが処理すべきか」決める
       - ルールベース(can_handle のスコア比較)
       - LLMベース(意図分類)         ← 両方実装して比較できるようにする
  2. チェーン実行: 複数エージェントを連携させる（DataQuery → Summary）
  3. トレース: 各ステップの status / 処理時間 / エラー を記録

【设计要点 / 設計のキモ】
- orchestrator は **具体的な agent を一切 import しない**。registry 経由でしか触らない。
  だから agent が増減しても orchestrator は無傷（＝OCP）。
- タイムアウトは orchestrator が一括で掛ける。個々の agent に書かせない
  （横断的関心事(cross-cutting concern)は上位でまとめて面倒を見る）。
"""
from __future__ import annotations

import asyncio
import json
import time

from ..providers.base import LLMProvider
from .base_agent import AgentResult
from .registry import AgentRegistry
from .trace import ExecutionTrace, StepStatus


class Orchestrator:
    def __init__(
        self,
        registry: AgentRegistry,
        router_llm: LLMProvider,
        *,
        default_agent: str = "knowledge",
        step_timeout: float = 60.0,
    ) -> None:
        self.registry = registry
        self.router_llm = router_llm          # 意図分類に使う LLM（agent本体とは別注入でもよい）
        self.default_agent = default_agent    # どの agent も手を挙げないときの保険
        self.step_timeout = step_timeout

    # ------------------------------------------------------------------ #
    # ルーティング戦略① ルールベース
    # ------------------------------------------------------------------ #
    def route_by_rule(self, query: str, context: dict) -> tuple[str, str]:
        """
        各 agent の can_handle(score) を比べ、最高スコアの agent を選ぶ。

        ▼ 利点: 速い・無料・決定的(テストしやすい)・LLM障害に強い。
        ▼ 欠点: キーワード設計に依存。言い換え/曖昧入力に弱い。
        """
        scored = [(a.name, a.can_handle(query, context)) for a in self.registry.all()]
        scored.sort(key=lambda x: x[1], reverse=True)
        best_name, best_score = scored[0]
        if best_score <= 0.0:
            # 誰も手を挙げない → デフォルトへフォールバック
            return self.default_agent, f"no rule matched; fallback (scores={scored})"
        return best_name, f"rule best={best_name}({best_score:.2f}) all={scored}"

    # ------------------------------------------------------------------ #
    # ルーティング戦略② LLM による意図分類
    # ------------------------------------------------------------------ #
    async def route_by_llm(self, query: str, context: dict) -> tuple[str, str]:
        """
        agent の name/description を選択肢として LLM に渡し、最適な1つを選ばせる。

        ▼ 利点: 言い換え・曖昧入力・複合意図に強い。新agentは description を書くだけで参加。
        ▼ 欠点: 遅い・お金/GPU・非決定的・LLM障害時にコケる → ルールへフォールバックが定石。
        """
        catalog = "\n".join(f"- {a.name}: {a.description}" for a in self.registry.all())
        system = (
            "あなたはルーター。ユーザー入力を最も適切なエージェントに振り分ける。\n"
            "必ず次のJSONだけを出力: {\"agent\": \"<name>\", \"reason\": \"<理由>\"}\n"
            "選べるエージェント:\n" + catalog
        )
        raw = await self.router_llm.chat(system, query, temperature=0.0)
        name = self._parse_agent_choice(raw)
        if name not in self.registry.names():
            # LLM が変な名前を返したらルールベースへ退避（堅牢性）
            fallback, why = self.route_by_rule(query, context)
            return fallback, f"llm returned invalid {name!r}; fallback→{fallback} ({why})"
        return name, f"llm chose {name} raw={raw[:120]!r}"

    @staticmethod
    def _parse_agent_choice(raw: str) -> str:
        try:
            start, end = raw.find("{"), raw.rfind("}")
            obj = json.loads(raw[start : end + 1])
            return str(obj.get("agent", "")).strip()
        except Exception:
            return ""

    # ------------------------------------------------------------------ #
    # 単一エージェント実行（タイムアウト＋トレース付き）
    # ------------------------------------------------------------------ #
    async def _run_agent(self, name: str, query: str, context: dict, trace: ExecutionTrace) -> AgentResult:
        agent = self.registry.get(name)
        async with trace.start_step(f"agent:{name}") as st:
            # タイムアウトは orchestrator が一括管理（横断的関心事）
            result = await asyncio.wait_for(agent.run(query, context), timeout=self.step_timeout)
            st.detail = result.output[:80]
        return result

    # ------------------------------------------------------------------ #
    # メイン: ルーティング → 実行
    # ------------------------------------------------------------------ #
    async def handle(self, query: str, context: dict, *, route_mode: str = "rule") -> dict:
        t0 = time.perf_counter()
        trace = ExecutionTrace(route_mode=route_mode)

        # 1) ルーティング
        async with trace.start_step("route") as st:
            if route_mode == "llm":
                name, why = await self.route_by_llm(query, context)
            else:
                name, why = self.route_by_rule(query, context)
            st.detail = why
        trace.chosen_agent = name

        # 2) 実行（失敗してもトレースは返す ＝ 観測可能性を死守）
        output, data, error = "", {}, None
        try:
            result = await self._run_agent(name, query, context, trace)
            output, data = result.output, result.data
        except Exception as e:  # noqa: BLE001 - プラットフォーム境界なので握って整形して返す
            error = f"{type(e).__name__}: {e}"

        trace.total_ms = (time.perf_counter() - t0) * 1000
        return {
            "agent": name,
            "output": output,
            "data": data,
            "error": error,
            "trace": trace.to_dict(),
        }

    # ------------------------------------------------------------------ #
    # チェーン: 複数エージェント連携（DataQuery → Summary）
    # ------------------------------------------------------------------ #
    async def run_chain(self, query: str, context: dict) -> dict:
        """
        例: 「DBから条件に合う顧客を取得 → その一覧を要約して営業に渡す」

        ▼ ここがマルチエージェント統合の肝:
          上流(DataQuery)の **構造化データ(AgentResult.data)** を
          context["upstream"] に積んで下流(Summary)へ受け渡す。
          ＝エージェント間の「状態共有」を context 経由で行う。
        """
        t0 = time.perf_counter()
        trace = ExecutionTrace(route_mode="chain", chosen_agent="data_query→summary")

        # --- step1: DataQuery ---
        async with trace.start_step("agent:data_query") as st:
            dq = await asyncio.wait_for(
                self.registry.get("data_query").run(query, context), timeout=self.step_timeout
            )
            st.detail = f"{len(dq.data.get('rows', []))} 件取得"

        # 取得0件なら下流を呼ばず早期終了（無駄なLLM呼び出しを避ける）
        if not dq.data.get("rows"):
            trace.total_ms = (time.perf_counter() - t0) * 1000
            return {
                "agents": ["data_query"],
                "output": "条件に合致するデータがありませんでした。",
                "data": dq.data,
                "trace": trace.to_dict(),
            }

        # --- step2: Summary（上流の出力を渡す）---
        summary_context = dict(context)
        summary_context["upstream"] = dq.data          # ← 状態共有
        summarize_input = dq.output                     # 整形済みテキストを要約対象に
        async with trace.start_step("agent:summary") as st:
            sm = await asyncio.wait_for(
                self.registry.get("summary").run(summarize_input, summary_context),
                timeout=self.step_timeout,
            )
            st.detail = sm.output[:80]

        trace.total_ms = (time.perf_counter() - t0) * 1000
        return {
            "agents": ["data_query", "summary"],
            "output": sm.output,
            "data": {"rows": dq.data.get("rows"), "summary": sm.output},
            "trace": trace.to_dict(),
        }
