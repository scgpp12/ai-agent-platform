"""
依存ゼロのローカル実装（モデル無しでも動く）
=============================================

【为什么要有这个 / なぜモック実装が要るか】

「LLM が無いと一行も動かない」状態だと、設計の学習にも CI にも不便。
そこで **Ollama を立てなくても全 API が動く** フォールバック実装を用意する。

- EchoLLM         : ルールベースで「それっぽい」要約・回答を作る（抽出的）。
- HashingEmbedding: 純Pythonの決定的ベクトル化（外部モデル不要）。

本番では config 次第で OllamaProvider に差し替わる。
インターフェースが同じなので、エージェント側のコードは一切変わらない
（＝Provider 抽象の御利益をここで体感できる）。
"""
from __future__ import annotations

import hashlib
import math
import re

from .base import EmbeddingProvider, LLMProvider


class EchoLLM(LLMProvider):
    """
    LLM が無い環境用の簡易代替。
    system プロンプトの種類をヒューリスティックに見て、抽出的な応答を返す。
    """

    async def chat(self, system: str, user: str, *, temperature: float = 0.2) -> str:
        s = system.lower()
        # 要約タスクっぽいか
        if "要約" in system or "summar" in s:
            return self._extractive_summary(user)
        # 意図分類タスク（JSONで返せと言われている）っぽいか
        if "json" in s and ("intent" in s or "agent" in s or "分類" in system):
            return '{"agent": "knowledge", "reason": "EchoLLM fallback (no model)"}'
        # パラメータ抽出っぽいか
        if "パラメータ" in system or "parameter" in s:
            return "{}"
        # 通常の Q&A: 与えられた文脈の冒頭を返すだけの最低限
        head = user.strip().splitlines()
        return "（LLM未接続のためEcho応答）" + (head[0] if head else user)[:200]

    @staticmethod
    def _extractive_summary(text: str, max_sentences: int = 3) -> str:
        # 文を分割 → 長い文＝情報量が多いとみなし上位を残す、超素朴な抽出要約。
        sentences = re.split(r"(?<=[。．.!?！？\n])", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            return "(要約対象が空です)"
        ranked = sorted(sentences, key=len, reverse=True)[:max_sentences]
        # 元の出現順に戻す
        ordered = [s for s in sentences if s in ranked][:max_sentences]
        return "・" + "\n・".join(ordered)


class HashingEmbedding(EmbeddingProvider):
    """
    純Pythonの決定的埋め込み。文字 n-gram を固定次元のバケツにハッシュして詰める
    (feature hashing)。意味理解はしないが「語が被る文ほど近い」性質は持つので、
    簡易ベクトル検索のデモには十分。本番は OllamaEmbeddingProvider(bge-m3) に差し替え。
    """

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    async def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = self._tokenize(text)
        for tok in tokens:
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h >> 8) & 1 else -1.0
            vec[idx] += sign
        # L2 正規化（cosine 比較をしやすくする）
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        text = text.lower()
        # 英数字の単語 + 日本語は2文字bi-gram、で語彙を作る
        words = re.findall(r"[a-z0-9]+", text)
        cjk = re.findall(r"[぀-ヿ一-鿿]", text)
        bigrams = ["".join(pair) for pair in zip(cjk, cjk[1:])]
        return words + cjk + bigrams
