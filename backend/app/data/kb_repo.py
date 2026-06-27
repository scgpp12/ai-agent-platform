"""
KnowledgeRepository —— FAQ知識の取得を抽象（JSON ↔ DynamoDB）
=============================================================

KnowledgeAgent は「文書集合を受け取り、ベクトル検索して回答」するだけ。
文書が JSONファイルから来るか DynamoDB から来るかは本質ではないので Repository に分離。

【ベクトルの扱いの差】
- JSON(ローカル) : ベクトルは持たない → エージェントが embedder で都度計算（HashingEmbeddingなど）
- Dynamo(本番)   : seed 時に Titan で計算した `vector` を一緒に保存しておく
                   → 検索のたびに全文書を再ベクトル化しない（Bedrock呼び出し節約）
エージェントは「doc に vector があれば使う、無ければ計算」で両対応する。
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path


class KnowledgeRepository(ABC):
    name = "base"

    @abstractmethod
    async def all_docs(self) -> list[dict]:
        """全FAQ文書を返す。各 dict は id/title/text（任意で vector）。"""
        raise NotImplementedError


class JsonKbRepo(KnowledgeRepository):
    name = "json"

    def __init__(self, kb_path: str | Path) -> None:
        self.kb_path = Path(kb_path)

    async def all_docs(self) -> list[dict]:
        return json.loads(self.kb_path.read_text(encoding="utf-8"))


class DynamoKbRepo(KnowledgeRepository):
    name = "dynamo"

    def __init__(self, table_name: str, region: str) -> None:
        import boto3

        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    async def all_docs(self) -> list[dict]:
        import asyncio

        return await asyncio.to_thread(self._scan_sync)

    def _scan_sync(self) -> list[dict]:
        items = self._table.scan().get("Items", [])
        docs = []
        for it in items:
            doc = {"id": it["id"], "title": it.get("title", ""), "text": it.get("text", "")}
            if "vector" in it:
                # Decimal のリストを float に直す
                doc["vector"] = [float(x) for x in it["vector"]]
            docs.append(doc)
        return docs
