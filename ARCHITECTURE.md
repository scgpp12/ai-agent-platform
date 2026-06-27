# ARCHITECTURE — プラットフォーム全体構成

## 1. 設計の狙い

このプロジェクトの主役は「個々のエージェント」ではなく、
**任意のエージェントを統一的に統合・調停・観測する“器”（プラットフォーム）** である。

設計上のたった1つの原則:

> **プラットフォーム本体（registry / orchestrator / API）は、具体的なエージェントを一切 import しない。**
> エージェントは `BaseAgent` という契約を通してのみ存在する。

これにより「エージェントを足しても本体を変えない（開放閉鎖原則 / OCP）」が成立する。

---

## 2. 全体構成図

```
                         ┌──────────────────────────────────────────┐
   HTTP (JWT必須)        │              FastAPI (app/main.py)         │
   ───────────────────▶ │   /chat  /chain/lead-digest  /connectors  │
                         │   Depends(require_user) でJWT検証          │
                         └───────────────┬──────────────────────────┘
                                         │ context={user, connectors}
                                         ▼
                         ┌──────────────────────────────────────────┐
                         │        Orchestrator (core/orchestrator)    │
                         │  1. ルーティング  ①rule ②llm              │
                         │  2. 単体実行 / チェーン実行                 │
                         │  3. タイムアウト & トレース(core/trace)     │
                         └───────────────┬──────────────────────────┘
                                         │ registry.get(name) でしか触らない
                       ┌─────────────────┼─────────────────┐
                       ▼                 ▼                 ▼
              ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
              │ KnowledgeAgent │ │ DataQueryAgent │ │  SummaryAgent  │   ← BaseAgent実装
              │ 簡易RAG/FAQ検索 │ │ NL→SQLite      │ │ 要約           │
              └───────┬────────┘ └───────┬────────┘ └───────┬────────┘
                      │                  │                  │
                      ▼                  ▼                  ▼
            EmbeddingProvider      SQLite(sales.db)    LLMProvider
            ┌─────────────────────────────────────────────────────┐
            │  Provider 抽象 (providers/base.py)                    │
            │   ├─ OllamaProvider / OllamaEmbeddingProvider (本物)  │
            │   └─ EchoLLM / HashingEmbedding (モデル不要フォールバック)│
            └─────────────────────────────────────────────────────┘

            ┌─────────────────────────────────────────────────────┐
            │  Connector 抽象 (connectors/base.py)                  │
            │   └─ CalendarStubConnector (外部SaaSのモック)         │
            └─────────────────────────────────────────────────────┘
```

### レイヤと責務

| レイヤ | ファイル | 責務 |
|--------|----------|------|
| API / 組み立て | `app/main.py` | エンドポイント定義、全部品の生成・配線(composition root) |
| 認証 | `app/security/auth.py` | JWT検証の`Depends`（Cognito差し替え前提） |
| オーケストレーション | `app/core/orchestrator.py` | ルーティング・チェーン・タイムアウト |
| 観測 | `app/core/trace.py` | ステップ status / 処理時間 / エラー記録 |
| エージェント契約 | `app/core/base_agent.py`, `registry.py` | `BaseAgent` / `AgentRegistry` |
| 具体エージェント | `app/agents/*` | Knowledge / DataQuery / Summary |
| LLM/埋め込み抽象 | `app/providers/*` | Ollama実装 と モック実装 |
| 外部連携抽象 | `app/connectors/*` | Connector契約 と カレンダースタブ |

**依存の向きは常に「上位→下位」**（main → orchestrator → registry → agent → provider）。
下位は上位を知らない。これが差し替え自由度の源泉。

---

## 3. 新しいエージェントを追加する手順

例として「競合分析エージェント(CompetitorAgent)」を足す。**本体コードは触らない。**

### Step 1. `BaseAgent` を実装する

```python
# app/agents/competitor_agent.py
from ..core.base_agent import AgentResult, BaseAgent
from ..providers.base import LLMProvider

class CompetitorAgent(BaseAgent):
    name = "competitor"
    description = "競合他社の比較・差別化ポイントを答える。「競合」「比較」「他社」系。"

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def can_handle(self, query: str, context: dict) -> float:        # ①ルールルーティング用
        hits = sum(1 for k in ["競合", "他社", "比較", "差別化"] if k in query)
        return min(0.9, 0.3 + 0.2 * hits) if hits else 0.0

    async def run(self, query: str, context: dict) -> AgentResult:    # 実処理
        answer = await self.llm.chat("あなたは競合分析担当。", query)
        return AgentResult(agent=self.name, output=answer)
```

### Step 2. composition root で1行 `register` する

```python
# app/main.py の build_platform() 内に追記するだけ
from .agents.competitor_agent import CompetitorAgent
registry.register(CompetitorAgent(llm))
```

これで完了。

- **ルールルーティング**: `can_handle` を見て自動で候補に入る → 本体無改修。
- **LLMルーティング**: `description` が分類プロンプトのカタログに自動で載る → 本体無改修。
- `/agents` API にも自動で出る。

> 👉 ここが「新しいエージェントを追加してもプラットフォーム本体を変えずに済む」の実体。
> orchestrator も API も `competitor` という名前を一切ハードコードしていない。

---

## 4. エージェント間連携（チェーン）の仕組み

`POST /chain/lead-digest` = **DataQuery → Summary** のチェーン（`orchestrator.run_chain`）。

```
入力「東京の顧客を出して」
      │
      ▼  ① DataQueryAgent.run()
   AgentResult.data = {"rows": [...10社...]}      ← 構造化データ
      │
      │  ② context["upstream"] = dq.data          ← ★状態共有はcontext経由
      ▼
   SummaryAgent.run(dq.output, context)            ← 上流の出力＋元データを要約
      │
      ▼
   出力「営業向け3点ダイジェスト」
```

ポイント:

1. **状態共有は`context`辞書で行う**。エージェントはグローバル変数や互いのクラスを直接触らない
   → 疎結合のままチェーンを組み替えられる。
2. **`AgentResult`が統一フォーマット**なので、上流が何であろうと下流は同じ受け取り方ができる。
   DataQueryの代わりにKnowledgeを上流にしても、Summaryは無改修。
3. **早期終了**: DataQueryが0件なら下流のLLMを呼ばない（無駄なコスト/レイテンシを避ける）。
4. 各ステップは`trace`に時間と成否が残る → どこが遅い/失敗したか一目で分かる。

---

## 5. ルーティング2方式の比較（`/chat`の`route_mode`）

| | ①ルールベース (`route_by_rule`) | ②LLM意図分類 (`route_by_llm`) |
|--|--|--|
| 仕組み | 各agentの`can_handle`スコア最大を選ぶ | agentの`description`をLLMに見せて1つ選ばせる |
| 速度/コスト | 速い・無料・GPU不要 | 遅い・GPU/課金 |
| 決定性 | 決定的（テスト容易） | 非決定的 |
| 曖昧入力 | 弱い（キーワード設計依存） | 強い（言い換え・複合意図に対応） |
| 障害耐性 | LLM障害に影響されない | LLM障害でコケる→**ルールにフォールバック実装済み** |

実務の定石は **「まずルール、外れたらLLM」または「LLM分類＋ルールでガードレール」** のハイブリッド。
本実装は両方を同じ入力で叩いて `trace.route_mode` と `detail` を見比べられる。

---

## 6. 外部サービス連携(Connector)の構造

`Connector` は「外部SaaSを叩く」を抽象化する。`invoke(action, params) -> dict` の一点契約。

- `CalendarStubConnector` は本物のCalendar APIの代わりにメモリで予定を管理。
- `/connectors/calendar/followup` で「DataQueryでフォロー対象抽出 → カレンダーに予定登録」を実演。
- 本番化は `invoke()` の中身をSDK呼び出しに変えるだけ。**呼ぶ側（agent/orchestrator）は無改修**。

これが「外部サービスをエージェントが呼ぶ」標準構造。鍵管理・リトライ・タイムアウトをConnectorに
集約できるので、各agentに散らばらない。

---

## 7. AWS デプロイ構成（本番）

ローカルと**全く同じ FastAPI コード**を、抽象の差し替えだけで AWS サーバーレスに載せる。

```
[Vercel: Next.js] ──Cognito Hosted UIでログイン→id_token取得
       │ fetch(Authorization: Bearer id_token)  ＋ CORS
       ▼
[API Gateway HTTP API] ── Cognito JWT Authorizer（issuer=UserPool, aud=AppClient）
       │  /health は認証なし、/{proxy+} は要認証
       ▼
[Lambda: handler.Mangum(app)]  ＝ backend/app そのまま
       ├ LLMProvider      → BedrockProvider（haiku 4.5 推論プロファイル）
       ├ EmbeddingProvider→ BedrockEmbedding（Titan v2）
       ├ CustomerRepository→ DynamoCustomerRepo（CustomersTable + region-index GSI）
       └ KnowledgeRepository→ DynamoKbRepo（KnowledgeTable, vector同梱）
[Cognito User Pool]  トークン発行（＝認証担当の責務）
   ※全部 infra/ の CDK 1スタックで定義
```

### ローカル抽象 → AWS 実装の対応（差し替え点）

| 抽象 | ローカル | AWS | 切替方法 |
|---|---|---|---|
| `LLMProvider` | EchoLLM / Ollama | `BedrockProvider` | env `LLM_BACKEND` |
| `EmbeddingProvider` | HashingEmbedding | `BedrockEmbedding` | env `EMBED_BACKEND` |
| `CustomerRepository` | `SqliteCustomerRepo` | `DynamoCustomerRepo` | env `DATA_BACKEND` |
| `KnowledgeRepository` | `JsonKbRepo` | `DynamoKbRepo` | env `DATA_BACKEND` |
| JWT 検証 | HS256(共有鍵) | Cognito RS256/JWKS | env `AUTH_BACKEND` |
| 配信 | uvicorn | Lambda + Mangum | `handler.py` |

**業務コード（core / agents / connectors）は AWS 化で一行も変えていない。**
変わったのは「組み立て(`main.build_*`)」と「新しい実装クラスの追加」だけ。これが抽象の投資回収。

### 認証の二重防御
1. **API Gateway の Cognito Authorizer**：未認証は Lambda 到達前に弾く（コスト/DoS 対策）。
2. **アプリ内 `require_user`（JWKS再検証）**：FastAPI 内で claims を扱う + 多層防御。
   `AUTH_BACKEND=cognito` で JWKS 検証、ローカルは `hs256`。

### NoSQL のアクセスパターン設計
DynamoDB は SQL の自由な WHERE/ORDER BY が無い。`DynamoCustomerRepo` は:
- region 指定 → GSI `region-index`(PK=region, SK=monthly_revenue) を Query（売上ソートが“ただ”で効く）
- region 無し → Scan + FilterExpression
「先にアクセスパターンを決めて GSI を設計する」という NoSQL の流儀をコードで示している。

### Docker 不要パッケージング
`cryptography`/`pydantic-core` は C/Rust 拡張。`scripts/build_lambda.sh` が
`pip install --platform manylinux2014_x86_64 --python-version 3.12 --only-binary=:all:`
で Linux x86_64 wheel を取得 → Windows からでも Docker 無しで Lambda asset を作れる。
