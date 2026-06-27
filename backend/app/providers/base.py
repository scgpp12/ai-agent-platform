"""
LLM / Embedding Provider 抽象
==============================

【为什么把 LLM 调用也抽象掉 / なぜ LLM 呼び出しも抽象化するか】

エージェントの中に `httpx.post("http://localhost:11434/api/chat", ...)` を直接書くと、
- Ollama → Bedrock / OpenAI に乗り換えるとき全エージェントを書き換える羽目になる
- テスト時に本物の LLM を立てないと動かない（遅い・不安定・お金がかかる）

そこで「文章を入れたら文章が返る」「文章を入れたらベクトルが返る」という
**最小の契約**だけ決めて、実装(Ollama/Bedrock/モック)を差し替え可能にする。

エージェントは `LLMProvider` 型にだけ依存する（＝依存性逆転 / DIP）。
本番は OllamaProvider、CI は EchoProvider、というように注入する側で選ぶ。
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """テキスト生成の最小契約。"""

    @abstractmethod
    async def chat(self, system: str, user: str, *, temperature: float = 0.2) -> str:
        """
        system プロンプト + user 入力を渡し、生成テキストを返す。

        ここを実装するだけで Ollama / Bedrock / OpenAI を切り替えられる。
        （Bedrock 例: bedrock-runtime.converse(modelId=inference_profile, ...) を呼ぶ
          OpenAIProvider 例: client.chat.completions.create(...) を呼ぶ
          —— インターフェースが同じなのでエージェント側は無改修）
        """
        raise NotImplementedError


class EmbeddingProvider(ABC):
    """ベクトル化の最小契約（KnowledgeAgent の簡易ベクトル検索で使う）。"""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """テキストを固定長ベクトルにする。Ollama の bge-m3 でも自前ハッシュでも可。"""
        raise NotImplementedError
