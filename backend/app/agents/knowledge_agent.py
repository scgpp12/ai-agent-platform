"""
KnowledgeAgent —— 簡易RAG（FAQ/資料を検索して回答）
====================================================

流れ（RAGの最小形）:
  1. 起動時に FAQ を全部ベクトル化して in-memory に持つ（インデックス）
  2. 質問が来たらクエリをベクトル化 → cosine類似度で上位k件を retrieve
  3. retrieve した文書を「文脈」として LLM に渡し、grounded な回答を生成(generate)

【设计注釈】
- 文書取得は KnowledgeRepository に丸投げ → JSONファイルでも DynamoDB でも動く。
- ベクトル化は EmbeddingProvider に丸投げ → Titan でも自前ハッシュでも動く。
- 文書に保存済み vector があればそれを使い、無ければ embedder で計算（両対応）。
  → 本番は seed 時に Titan で計算した vector を Dynamo に持たせ、検索時の再計算を省く。
- 「検索 → LLMに食わせる」を分離しているので、検索器も生成器も独立に差し替え可能。
"""
from __future__ import annotations

import math
from typing import Any

from ..core.base_agent import AgentResult, BaseAgent
from ..data.kb_repo import KnowledgeRepository
from ..providers.base import EmbeddingProvider, LLMProvider


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class KnowledgeAgent(BaseAgent):
    name = "knowledge"
    description = "FAQ・社内資料・製品仕様などの知識を検索して質問に答える。価格/契約/サポート/セキュリティ等の「○○は？」系。"

    # ルールベース・ルーティング用のキーワード（自信度に反映）
    _KEYWORDS = ["とは", "何", "なに", "教えて", "?", "？", "方法", "条件", "期限",
                 "料金", "価格", "サポート", "セキュリティ", "解約", "見積"]

    def __init__(self, llm: LLMProvider, embedder: EmbeddingProvider, repo: KnowledgeRepository) -> None:
        self.llm = llm
        self.embedder = embedder
        self.repo = repo
        self._docs: list[dict[str, Any]] = []
        self._vectors: list[list[float]] = []
        self._indexed = False

    async def _ensure_index(self) -> None:
        """遅延インデックス（初回の検索時に1度だけ準備）。"""
        if self._indexed:
            return
        self._docs = await self.repo.all_docs()
        for d in self._docs:
            # 保存済みベクトルがあれば使う（Dynamo+Titan）、無ければ計算（JSON+ハッシュ）
            vec = d.get("vector") or await self.embedder.embed(f"{d['title']} {d['text']}")
            self._vectors.append(vec)
        self._indexed = True

    def can_handle(self, query: str, context: dict) -> float:
        q = query.lower()
        hits = sum(1 for k in self._KEYWORDS if k.lower() in q)
        # 0.3 を基礎点に、キーワード一致で加点（上限0.9）。質問記号があれば底上げ。
        score = min(0.9, 0.3 + 0.15 * hits)
        return score if hits else 0.2

    async def run(self, query: str, context: dict) -> AgentResult:
        await self._ensure_index()

        # --- retrieve: クエリベクトルと全文書の類似度 top-k ---
        qvec = await self.embedder.embed(query)
        scored = sorted(
            ((_cosine(qvec, v), d) for v, d in zip(self._vectors, self._docs)),
            key=lambda x: x[0],
            reverse=True,
        )
        top = scored[:3]
        retrieved = [{"id": d["id"], "title": d["title"], "score": round(s, 3)} for s, d in top]

        # 低スコアしか無い ＝ 知らないこと。幻覚を避けて正直に返す（低分拒答）。
        if not top or top[0][0] < 0.15:
            return AgentResult(
                agent=self.name,
                output="申し訳ありません、その内容は知識ベースに見つかりませんでした。担当者にお繋ぎします。",
                data={"retrieved": retrieved},
                meta={"reason": "low similarity"},
            )

        # --- generate: 取得文書を文脈にして回答（grounded） ---
        context_block = "\n".join(f"[{d['title']}] {d['text']}" for _, d in top)
        system = (
            "あなたは営業支援アシスタント。以下の社内資料**だけ**を根拠に、"
            "日本語で簡潔に回答する。資料に無いことは推測せず『資料に記載がない』と言う。\n"
            "--- 社内資料 ---\n" + context_block
        )
        answer = await self.llm.chat(system, query)
        return AgentResult(
            agent=self.name,
            output=answer,
            data={"retrieved": retrieved},
            meta={"context_docs": [d["id"] for _, d in top]},
        )
