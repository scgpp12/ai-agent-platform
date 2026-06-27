# AIエージェント統合プラットフォーム (mini)

営業支援を想定した「複数AIエージェントを統合・オーケストレーションする」バックエンドを、
**ローカル(無料)でも AWS サーバーレスでも同じコードで動く**ように作った実戦練習プロジェクト。

LangChain 等は使わず、エージェント抽象・レジストリ・ルーティング・連携・観測を自前で実装。

```
ローカル: FastAPI + Echo/Ollama + SQLite + HS256
   │  ＝ Provider / Repository / Auth 抽象で差し替え
   ▼
本番(AWS): Lambda(FastAPI) + Bedrock + DynamoDB + Cognito + API Gateway
フロント:  Next.js on Vercel（Cognito で本物の JWT を取得して API を叩く）
```

## リポジトリ構成（monorepo）

| ディレクトリ | 中身 |
|---|---|
| `backend/` | FastAPI プラットフォーム本体（Lambda 化対応）。コアは [`backend/app/core`](backend/app/core) |
| `infra/` | AWS CDK(TypeScript)。1 スタックで Lambda+DynamoDB+Bedrock権限+Cognito+API GW |
| `frontend/` | Next.js（Vercel デプロイ）。Cognito ログイン → JWT で API 呼び出し |
| `scripts/` | `build_lambda.sh`（Docker不要パッケージング）/ `seed_dynamo.py`（データ投入）/ `make_token.py` |
| `ARCHITECTURE.md` / `LEARNING.md` | 設計解説・面談用論点 |

---

## A. まずローカルで動かす（AWS不要・最速）

```bash
cd backend
python -m venv .venv && source .venv/Scripts/activate   # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
DEV_NO_AUTH=1 python -m uvicorn app.main:app --reload --port 8077
```
モデルが無くても `EchoLLM`+ハッシュ埋め込み+SQLite で全 API が動く。

```bash
# 確認（Windowsの curl は日本語 body が化けるので UTF-8 ファイル + --data-binary）
curl -s http://localhost:8077/health
printf '{"message":"東京のIT顧客を出して","route_mode":"rule"}' > q.json
curl -s -X POST http://localhost:8077/chat -H "Content-Type: application/json" --data-binary @q.json
```

### ローカルから本物の Bedrock を使う（任意）

```bash
export AWS_REGION=ap-northeast-1
LLM_BACKEND=bedrock EMBED_BACKEND=bedrock DEV_NO_AUTH=1 \
  python -m uvicorn app.main:app --port 8077
```
`default` profile + 東京で haiku 4.5 推論プロファイル / Titan v2 を呼ぶ。

### テスト

```bash
cd backend && pytest -q     # echo+sqlite で 7 件のスモークテスト
```

---

## B. AWS へデプロイ（CDK）

前提: `default` profile / 東京は bootstrap 済み / Node 入り。

```bash
# 1) Lambda パッケージを作る（Docker 不要・Windowsでも Linux wheel を取得）
bash scripts/build_lambda.sh

# 2) CDK デプロイ
cd infra
npm install
export AWS_REGION=ap-northeast-1
npx cdk deploy            # 初回は frontendOrigin=localhost のまま

# 出力(Outputs)を控える: ApiUrl / UserPoolId / AppClientId / CognitoIssuer / HostedUiDomain / *TableName
```

```bash
# 3) DynamoDB に初期データ投入（顧客 + FAQ知識を Titan で埋め込み計算して保存）
cd ..
export AWS_REGION=ap-northeast-1
export CUSTOMERS_TABLE=<出力 CustomersTableName>
export KNOWLEDGE_TABLE=<出力 KnowledgeTableName>
python scripts/seed_dynamo.py
```

```bash
# 4) 動作確認（認証なしの /health は通る、/chat は 401）
curl -s <ApiUrl>/health
curl -s -o /dev/null -w "%{http_code}\n" -X POST <ApiUrl>/chat   # → 401
```

JWT 付きで叩くには Cognito でユーザーを作ってトークンを取得する（= フロント経由が楽。次節）。

---

## C. フロントエンド（Vercel）

```bash
cd frontend
npm install
cp .env.local.example .env.local   # CDK Outputs を貼る
npm run dev                         # http://localhost:3000
```

`.env.local`（または Vercel の環境変数）:

| 変数 | 値（CDK Outputs） |
|---|---|
| `NEXT_PUBLIC_API_URL` | `ApiUrl` |
| `NEXT_PUBLIC_COGNITO_AUTHORITY` | `CognitoIssuer` |
| `NEXT_PUBLIC_COGNITO_CLIENT_ID` | `AppClientId` |
| `NEXT_PUBLIC_COGNITO_DOMAIN` | `HostedUiDomain` |
| `NEXT_PUBLIC_REDIRECT_URI` | ローカル`http://localhost:3000/` / 本番`https://<app>.vercel.app/` |

### Vercel デプロイの順番（CORS / コールバックの鶏卵問題）

1. `cdk deploy`（localhost のまま）→ Vercel に frontend をデプロイ → URL 確定
2. その URL を渡して **再デプロイ**: `cd infra && npx cdk deploy -c frontendOrigin=https://<app>.vercel.app`
   （API GW の CORS 許可 + Cognito コールバック/ログアウト URL に Vercel ドメインが入る）
3. Vercel の `NEXT_PUBLIC_REDIRECT_URI` を本番URLにして再デプロイ
4. ブラウザでログイン → 対話。`trace` に選択エージェント・各ステップ処理時間が出る

---

## D. 後片付け & コスト

```bash
cd infra && npx cdk destroy     # DynamoDB/Lambda/API/Cognito を全削除
```
練習時のコストはほぼ無料（Bedrock haiku 従量数円・DynamoDB 按需・Lambda/Cognito/Vercel 無料枠）。

---

## ドキュメント
- [ARCHITECTURE.md](ARCHITECTURE.md) — 構成図 / 新エージェント追加手順 / 連携機構 / AWSマッピング
- [LEARNING.md](LEARNING.md) — マルチエージェント統合の設計論点（面談で言える日本語一文つき）
