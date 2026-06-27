"""
Ollama 実装（本機 Ubuntu / sons02 などローカル無料 LLM）
=========================================================

LLMProvider / EmbeddingProvider を Ollama のネイティブ API で実装する。

ポイント:
- `/api/chat` に `"think": false` を渡して **思考連鎖(reasoning)を抑制**する
  （qwen3 系は放っておくと <think> を吐く。OpenAI 互換 /v1 では消せないので native を使う）。
- タイムアウトは必ず設定する（LLM はたまに固まる → プラットフォーム全体を巻き込まない）。
"""
from __future__ import annotations

import httpx

from .base import EmbeddingProvider, LLMProvider


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str, model: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def chat(self, system: str, user: str, *, temperature: float = 0.2) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "think": False,  # ← 思考連鎖オフ（native /api/chat 限定の効き方）
            "options": {"temperature": temperature},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        return (data.get("message") or {}).get("content", "").strip()


class OllamaEmbeddingProvider(EmbeddingProvider):
    """bge-m3 等の埋め込みモデルでベクトル化する実装。"""

    def __init__(self, base_url: str, model: str = "bge-m3", timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def embed(self, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
            )
            resp.raise_for_status()
            return resp.json()["embedding"]
