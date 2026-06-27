"""
DynamoDB へ初期データを投入する（顧客 + FAQ知識＋Titanベクトル）。
一度だけ実行する。default profile / 東京リージョンを使う。

使い方（CDK の Outputs を env に入れて実行）:
    export AWS_REGION=ap-northeast-1
    export CUSTOMERS_TABLE=<出力 CustomersTableName>
    export KNOWLEDGE_TABLE=<出力 KnowledgeTableName>
    python scripts/seed_dynamo.py

設計メモ:
- 知識のベクトルは **ここで Titan を1回だけ叩いて計算** し DynamoDB に保存する。
  → 本番の検索時に毎回ベクトル化しない（Bedrock 呼び出しコスト削減）。
- DynamoDB は float 不可なので数値は Decimal に変換して入れる。
"""
from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import boto3

# backend をパスに通して app.* を import 可能にする
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.data.seed import _CUSTOMERS  # noqa: E402  顧客データ（SQLiteと同じ元ネタを共有）

REGION = os.getenv("AWS_REGION", "ap-northeast-1")
CUSTOMERS_TABLE = os.getenv("CUSTOMERS_TABLE", "")
KNOWLEDGE_TABLE = os.getenv("KNOWLEDGE_TABLE", "")
EMBED_MODEL = os.getenv("BEDROCK_EMBED_MODEL", "amazon.titan-embed-text-v2:0")
KB_JSON = ROOT / "backend" / "app" / "data" / "knowledge_base.json"


def _embed(bedrock, text: str) -> list[Decimal]:
    resp = bedrock.invoke_model(modelId=EMBED_MODEL, body=json.dumps({"inputText": text}))
    vec = json.loads(resp["body"].read())["embedding"]
    # float → Decimal（DynamoDB 要件）
    return [Decimal(str(x)) for x in vec]


def seed_customers(ddb) -> int:
    table = ddb.Table(CUSTOMERS_TABLE)
    with table.batch_writer() as bw:
        for i, (name, region, industry, revenue, status, last) in enumerate(_CUSTOMERS, start=1):
            bw.put_item(
                Item={
                    "id": f"cust-{i:03d}",
                    "name": name,
                    "region": region,
                    "industry": industry,
                    "monthly_revenue": Decimal(revenue),
                    "status": status,
                    "last_contact": last,
                }
            )
    return len(_CUSTOMERS)


def seed_knowledge(ddb, bedrock) -> int:
    table = ddb.Table(KNOWLEDGE_TABLE)
    docs = json.loads(KB_JSON.read_text(encoding="utf-8"))
    for d in docs:
        vector = _embed(bedrock, f"{d['title']} {d['text']}")
        table.put_item(
            Item={"id": d["id"], "title": d["title"], "text": d["text"], "vector": vector}
        )
        print(f"  seeded {d['id']} ({d['title']}) dim={len(vector)}")
    return len(docs)


def main() -> None:
    if not CUSTOMERS_TABLE or not KNOWLEDGE_TABLE:
        sys.exit("CUSTOMERS_TABLE / KNOWLEDGE_TABLE を env で指定してください（CDK Outputs 参照）")

    ddb = boto3.resource("dynamodb", region_name=REGION)
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)

    print(f"[customers] -> {CUSTOMERS_TABLE}")
    n1 = seed_customers(ddb)
    print(f"[customers] {n1} 件投入")

    print(f"[knowledge] -> {KNOWLEDGE_TABLE} (Titan で埋め込み計算)")
    n2 = seed_knowledge(ddb, bedrock)
    print(f"[knowledge] {n2} 件投入")
    print("DONE")


if __name__ == "__main__":
    main()
