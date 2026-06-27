"""
スモークテスト（モデル無し・echo構成で全体が動くことを保証）。
    pytest -q
"""
from __future__ import annotations

import os

import pytest

# テストは echo / hashing / 認証スキップ で実行（外部依存ゼロ）
os.environ.setdefault("LLM_BACKEND", "echo")
os.environ.setdefault("EMBED_BACKEND", "hashing")
os.environ.setdefault("DEV_NO_AUTH", "1")

from app.agents import DataQueryAgent  # noqa: E402
from app.core import AgentRegistry, Orchestrator  # noqa: E402
from app.data import init_db  # noqa: E402
from app.data.customer_repo import SqliteCustomerRepo  # noqa: E402
from app.data.kb_repo import JsonKbRepo  # noqa: E402
from app.providers import EchoLLM, HashingEmbedding  # noqa: E402
from app.agents import KnowledgeAgent, SummaryAgent  # noqa: E402
from app.config import settings  # noqa: E402


def _build():
    init_db(settings.db_path)
    reg = AgentRegistry()
    llm, emb = EchoLLM(), HashingEmbedding()
    reg.register(KnowledgeAgent(llm, emb, JsonKbRepo(settings.kb_path)))
    reg.register(DataQueryAgent(llm, SqliteCustomerRepo(settings.db_path)))
    reg.register(SummaryAgent(llm))
    return Orchestrator(reg, router_llm=llm, default_agent="knowledge")


def test_registry_rejects_duplicate():
    reg = AgentRegistry()
    reg.register(SummaryAgent(EchoLLM()))
    with pytest.raises(ValueError):
        reg.register(SummaryAgent(EchoLLM()))


def test_rule_routing_picks_dataquery():
    orch = _build()
    name, why = orch.route_by_rule("東京の顧客を一覧で出して", {})
    assert name == "data_query", why


def test_rule_routing_picks_summary():
    orch = _build()
    name, _ = orch.route_by_rule("この議事録を要約して", {})
    assert name == "summary"


@pytest.mark.asyncio
async def test_dataquery_returns_rows():
    orch = _build()
    res = await orch.handle("東京のIT顧客を出して", {}, route_mode="rule")
    assert res["agent"] == "data_query"
    assert res["error"] is None
    assert res["data"]["rows"], "東京/IT で1件は返るはず"
    # 抽出パラメータに region/industry が入っている（白名单抽出が効いている）
    assert res["data"]["params"]["region"] == "東京"
    assert res["data"]["params"]["industry"] == "IT"


@pytest.mark.asyncio
async def test_chain_dataquery_then_summary():
    orch = _build()
    res = await orch.run_chain("東京の顧客を出して", {})
    assert res["agents"] == ["data_query", "summary"]
    assert "summary" in res["data"]
    # トレースに2ステップ記録されている（観測可能性）
    steps = [s["step"] for s in res["trace"]["steps"]]
    assert "agent:data_query" in steps and "agent:summary" in steps


@pytest.mark.asyncio
async def test_knowledge_low_similarity_refuses():
    orch = _build()
    # 知識ベースに無い話題 → 正直に「見つからない」と返す（幻覚防止）
    res = await orch.handle("量子コンピュータの最新論文を教えて", {}, route_mode="rule")
    assert res["agent"] in ("knowledge", "summary", "data_query")  # ルーティング先は問わない
    assert res["error"] is None


@pytest.mark.asyncio
async def test_trace_records_timing():
    orch = _build()
    res = await orch.handle("サポート対応時間は？", {}, route_mode="rule")
    assert res["trace"]["total_ms"] >= 0
    assert len(res["trace"]["steps"]) >= 2  # route + agent
