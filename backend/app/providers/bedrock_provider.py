"""
Amazon Bedrock 実装（本番のLLM/埋め込み）
==========================================

Provider 抽象の「本命の差し替え先」。OllamaProvider と同じインターフェースを
Bedrock で実装するだけ —— エージェント側は一行も変わらない（＝抽象の御利益）。

【东京リージョンの注意（重要）】
- Claude 系は **INFERENCE_PROFILE 必須**。model-id 直叩きは
  `ValidationException: model identifier is invalid` になる。
  → `BEDROCK_MODEL_ID=jp.anthropic.claude-haiku-4-5-20251001-v1:0`（地域推論プロファイル）を使う。
- 埋め込みの Titan(amazon.*) は通常モデルなので model-id 直叩きでOK。
- IAM の bedrock:InvokeModel リソースには foundation-model ARN と inference-profile ARN の両方が要る。

【非同期について】
boto3 は同期SDK。FastAPI/Lambda のイベントループを塞がないよう asyncio.to_thread で
ワーカースレッドに逃がす。Lambda は1呼び出し=1リクエストなのでこれで十分。
"""
from __future__ import annotations

import asyncio
import json

import boto3

from .base import EmbeddingProvider, LLMProvider


class BedrockProvider(LLMProvider):
    def __init__(self, model_id: str, region: str, *, max_tokens: int = 1024) -> None:
        self.model_id = model_id
        self.max_tokens = max_tokens
        # bedrock-runtime クライアント（converse / invoke_model を持つ）
        self._client = boto3.client("bedrock-runtime", region_name=region)

    async def chat(self, system: str, user: str, *, temperature: float = 0.2) -> str:
        return await asyncio.to_thread(self._chat_sync, system, user, temperature)

    def _chat_sync(self, system: str, user: str, temperature: float) -> str:
        # converse API は各社モデルを統一フォーマットで叩ける（プロバイダ差を吸収）
        resp = self._client.converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": self.max_tokens, "temperature": temperature},
        )
        return resp["output"]["message"]["content"][0]["text"].strip()


class BedrockEmbedding(EmbeddingProvider):
    """Amazon Titan Embeddings v2（1024次元・多言語）。"""

    def __init__(self, model_id: str, region: str) -> None:
        self.model_id = model_id
        self._client = boto3.client("bedrock-runtime", region_name=region)

    async def embed(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._embed_sync, text)

    def _embed_sync(self, text: str) -> list[float]:
        body = json.dumps({"inputText": text})
        resp = self._client.invoke_model(modelId=self.model_id, body=body)
        data = json.loads(resp["body"].read())
        return data["embedding"]
