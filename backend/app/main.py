"""
プラットフォーム本体（FastAPI アプリ＋組み立て＝Composition Root）
================================================================

ここが「全部品を1か所で組み立てる」場所(composition root)。
- Provider を選んで生成
- 3つの Agent を作って Registry に register
- Connector を Registry に register
- Orchestrator に Registry と router用LLM を注入
- エンドポイントを定義

【重要】ここ以外のどこにも「具体クラスの生成」を散らさない。
依存の向きを「上位(main)→下位(agent/provider)」に一本化することで、
差し替え(Ollama↔Echo, Agent追加)がこのファイルの編集だけで済む。
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agents import DataQueryAgent, KnowledgeAgent, SummaryAgent
from .config import settings
from .connectors import CalendarStubConnector, ConnectorRegistry
from .core import AgentRegistry, Orchestrator
from .data import init_db
from .data.customer_repo import DynamoCustomerRepo, SqliteCustomerRepo
from .data.kb_repo import DynamoKbRepo, JsonKbRepo
from .providers import (
    BedrockEmbedding,
    BedrockProvider,
    EchoLLM,
    HashingEmbedding,
    OllamaEmbeddingProvider,
    OllamaProvider,
    OpenAICompatProvider,
)
from .schemas import ChainResponse, ChatRequest, ChatResponse
from .security import AuthUser, require_user


# --------------------------------------------------------------------------- #
# Provider / Repository 生成（config に応じて本物/モックを選ぶ）
# --------------------------------------------------------------------------- #
def build_llm():
    if settings.llm_backend == "bedrock":
        return BedrockProvider(settings.bedrock_model_id, settings.aws_region)
    if settings.llm_backend == "ollama":
        return OllamaProvider(settings.ollama_base_url, settings.ollama_model, settings.step_timeout)
    if settings.llm_backend == "llamaswap":
        # sons02 の llama-swap(8080, OpenAI互換)。首次载模型慢→timeout 取大值。
        return OpenAICompatProvider(
            settings.llamaswap_base_url, settings.llamaswap_model,
            timeout=max(settings.step_timeout, 180.0),
        )
    return EchoLLM()  # モデル不要のフォールバック


def build_embedder():
    if settings.embed_backend == "bedrock":
        return BedrockEmbedding(settings.bedrock_embed_model, settings.aws_region)
    if settings.embed_backend == "ollama":
        return OllamaEmbeddingProvider(settings.ollama_base_url, settings.ollama_embed_model)
    return HashingEmbedding()


def build_customer_repo():
    if settings.data_backend == "dynamo":
        return DynamoCustomerRepo(settings.customers_table, settings.aws_region)
    return SqliteCustomerRepo(settings.db_path)


def build_kb_repo():
    if settings.data_backend == "dynamo":
        return DynamoKbRepo(settings.knowledge_table, settings.aws_region)
    return JsonKbRepo(settings.kb_path)


# --------------------------------------------------------------------------- #
# 組み立て（registry に agent / connector を登録）
# --------------------------------------------------------------------------- #
def build_platform() -> tuple[Orchestrator, AgentRegistry, ConnectorRegistry]:
    llm = build_llm()
    embedder = build_embedder()
    customer_repo = build_customer_repo()
    kb_repo = build_kb_repo()

    registry = AgentRegistry()
    # ★ 新しい agent を増やすときは「ここに1行 register する」だけ。
    #   orchestrator も API も無改修＝OCP の御利益。
    registry.register(KnowledgeAgent(llm, embedder, kb_repo))
    registry.register(DataQueryAgent(llm, customer_repo))
    registry.register(SummaryAgent(llm))

    connectors = ConnectorRegistry()
    connectors.register(CalendarStubConnector())

    orchestrator = Orchestrator(
        registry,
        router_llm=llm,
        default_agent="knowledge",
        step_timeout=settings.step_timeout,
    )
    return orchestrator, registry, connectors


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ローカル(sqlite)のときだけ SQLite を作ってシード投入。本番(dynamo)は seed スクリプトで投入済み。
    if settings.data_backend == "sqlite":
        init_db(settings.db_path)
    app.state.orchestrator, app.state.registry, app.state.connectors = build_platform()
    yield
    # 終了時のクリーンアップがあればここに


app = FastAPI(
    title="AIエージェント統合プラットフォーム (mini)",
    description="複数AIエージェントの統合・ルーティング・連携・観測のミニ実装",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: ローカル(uvicorn)では FastAPI が処理する。
# 本番(API Gateway)では **ゲートウェイ側で CORS を付ける**ので、ここは無効化する
# （二重に Access-Control-Allow-Origin を付けるとブラウザがエラーにする）。
# → Lambda 側は env CORS_ALLOW_ORIGINS="" を渡し、ローカルだけ origins を設定する。
_origins = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )


# --------------------------------------------------------------------------- #
# エンドポイント
# --------------------------------------------------------------------------- #
@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "llm_backend": settings.llm_backend,
        "embed_backend": settings.embed_backend,
        "data_backend": settings.data_backend,
        "auth_backend": settings.auth_backend,
    }


@app.get("/agents")
async def list_agents() -> dict:
    """登録済みエージェントのカタログ（プラグインが見えることの確認）。"""
    reg: AgentRegistry = app.state.registry
    return {"agents": [{"name": a.name, "description": a.description} for a in reg.all()]}


@app.get("/connectors")
async def list_connectors() -> dict:
    conns: ConnectorRegistry = app.state.connectors
    return {"connectors": [{"name": c.name, "actions": c.actions} for c in conns.all()]}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, user: AuthUser = Depends(require_user)) -> ChatResponse:
    """
    オーケストレーションの主入口。route_mode で rule / llm を切り替えて比較できる。
    JWT 必須（require_user）。DEV_NO_AUTH=1 のときだけ検証スキップ。
    """
    orch: Orchestrator = app.state.orchestrator
    # context に認証ユーザーやコネクタを載せて、agent / chain から参照できるようにする。
    context = {"user": {"sub": user.sub, "scopes": user.scopes}, "connectors": app.state.connectors}
    result = await orch.handle(req.message, context, route_mode=req.route_mode)
    return ChatResponse(**result)


@app.post("/chain/lead-digest", response_model=ChainResponse)
async def chain_lead_digest(req: ChatRequest, user: AuthUser = Depends(require_user)) -> ChainResponse:
    """
    チェーンのデモ: DataQuery で顧客抽出 → Summary で営業向けダイジェスト化。
    マルチエージェント連携＋状態共有(context["upstream"])の実演。
    """
    orch: Orchestrator = app.state.orchestrator
    context = {"user": {"sub": user.sub, "scopes": user.scopes}, "connectors": app.state.connectors}
    result = await orch.run_chain(req.message, context)
    return ChainResponse(**result)


@app.post("/connectors/calendar/followup")
async def calendar_followup(req: ChatRequest, user: AuthUser = Depends(require_user)) -> dict:
    """
    「外部サービスをエージェント/プラットフォームが呼ぶ」構造のデモ。
    DataQuery でフォロー対象を取り、各社のフォローアップ予定をカレンダー(スタブ)に登録。
    """
    orch: Orchestrator = app.state.orchestrator
    conns: ConnectorRegistry = app.state.connectors
    context = {"user": {"sub": user.sub, "scopes": user.scopes}, "connectors": conns}

    # 1) どの顧客をフォローするかを DataQueryAgent に決めさせる
    dq = await orch.registry.get("data_query").run(req.message, context)
    rows = dq.data.get("rows", [])

    # 2) 取得した各社について、カレンダー・コネクタに予定を作る（外部サービス呼び出し）
    calendar = conns.get("calendar")
    created = []
    for r in rows[:5]:
        res = await calendar.invoke(
            "create_event",
            {
                "title": f"営業フォロー: {r['name']}",
                "date": "2026-07-01",
                "attendees": [user.sub],
                "note": f"{r['region']}/{r['industry']} 月商{r['monthly_revenue']:,}円",
            },
        )
        created.append(res["event"])

    return {"matched": len(rows), "created_events": created, "query_params": dq.data.get("params")}
