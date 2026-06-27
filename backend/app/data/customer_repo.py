"""
CustomerRepository —— 顧客データ取得の抽象（SQLite ↔ DynamoDB 差し替え）
========================================================================

【为什么把「查询」也抽象成 Repository / なぜリポジトリ抽象か】

DataQueryAgent の本質は「自然言語 → 検証済みパラメータ → 安全に検索」。
「どのDBで検索するか」は本質ではない。そこを Repository に切り出すと:
  - ローカル開発 = SqliteCustomerRepo（ファイル1個、無料）
  - 本番(AWS)    = DynamoCustomerRepo
を **エージェント無改修** で差し替えられる。Provider 抽象と全く同じ思想。

【最重要のセキュリティ設計（SQLでもDynamoでも不変）】
LLM には「許可された項目の“値”」だけ抜かせ、クエリ骨格はこちらが組む。
ここで params をホワイトリスト検証してから組み立てる → インジェクション不可。
（SQL なら ?バインド、Dynamo なら KeyCondition/FilterExpression）
"""
from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

# 検索を許可する値のホワイトリスト（エージェントのLLMプロンプトでも候補提示に使う）
ALLOWED_REGIONS = {"東京", "大阪", "北海道", "福岡", "愛知", "神奈川", "宮城"}
ALLOWED_INDUSTRIES = {"小売", "IT", "食品", "製造", "物流", "医療", "観光"}
ALLOWED_STATUS = {"active", "prospect", "churned"}
SORTABLE = {"monthly_revenue", "last_contact"}


def _clean_params(params: dict) -> dict:
    """ホワイトリストに無い値は捨てる（＝クエリに混入させない）。"""
    region = params.get("region") if params.get("region") in ALLOWED_REGIONS else None
    industry = params.get("industry") if params.get("industry") in ALLOWED_INDUSTRIES else None
    status = params.get("status") if params.get("status") in ALLOWED_STATUS else None
    sort = params.get("sort") if params.get("sort") in SORTABLE else None
    order = "asc" if str(params.get("order", "desc")).lower() == "asc" else "desc"
    try:
        limit = int(params.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 100))
    return {"region": region, "industry": industry, "status": status,
            "sort": sort, "order": order, "limit": limit}


class CustomerRepository(ABC):
    name = "base"

    @abstractmethod
    async def query(self, params: dict) -> dict:
        """検証済みパラメータで検索し {"rows": [...], "debug": "<実行内容>"} を返す。"""
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# SQLite 実装（ローカル開発用）
# --------------------------------------------------------------------------- #
class SqliteCustomerRepo(CustomerRepository):
    name = "sqlite"

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    async def query(self, params: dict) -> dict:
        p = _clean_params(params)
        where, args = [], []
        if p["region"]:
            where.append("region = ?")
            args.append(p["region"])
        if p["industry"]:
            where.append("industry = ?")
            args.append(p["industry"])
        if p["status"]:
            where.append("status = ?")
            args.append(p["status"])

        sql = "SELECT name, region, industry, monthly_revenue, status, last_contact FROM customers"
        if where:
            sql += " WHERE " + " AND ".join(where)
        if p["sort"]:  # ソート列はホワイトリストのみ（ユーザー値を埋め込まない）
            sql += f" ORDER BY {p['sort']} {'ASC' if p['order'] == 'asc' else 'DESC'}"
        sql += " LIMIT ?"
        args.append(p["limit"])

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
        finally:
            conn.close()
        return {"rows": rows, "debug": f"SQL: {sql} | args={args}"}


# --------------------------------------------------------------------------- #
# DynamoDB 実装（本番 AWS 用）
# --------------------------------------------------------------------------- #
class DynamoCustomerRepo(CustomerRepository):
    """
    DynamoDB には SQL のような自由な WHERE/ORDER BY が無い。設計で吸収する:
      - region 指定あり → GSI(region-index, PK=region, SK=monthly_revenue) を Query
        （SK が売上なので売上ソートが“ただで”効く。industry/status は FilterExpression）
      - region 指定なし → Scan + FilterExpression（10件程度のデモなら十分。本番大規模なら別GSI）
    これが「NoSQLはアクセスパターンから設計する」の実演。
    """
    name = "dynamo"

    def __init__(self, table_name: str, region: str, gsi_name: str = "region-index") -> None:
        import boto3  # ローカルのecho構成では import させないため遅延import

        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        self.gsi_name = gsi_name

    async def query(self, params: dict) -> dict:
        import asyncio

        return await asyncio.to_thread(self._query_sync, params)

    def _query_sync(self, params: dict) -> dict:
        from boto3.dynamodb.conditions import Attr, Key

        p = _clean_params(params)

        # FilterExpression（industry/status）を組む共通部品
        filt = None
        for col in ("industry", "status"):
            if p[col]:
                cond = Attr(col).eq(p[col])
                filt = cond if filt is None else (filt & cond)

        if p["region"]:
            # GSI Query：region で絞り、SK(monthly_revenue)順で返る
            kwargs: dict[str, Any] = {
                "IndexName": self.gsi_name,
                "KeyConditionExpression": Key("region").eq(p["region"]),
                "ScanIndexForward": p["order"] == "asc",  # desc=売上高い順
            }
            if filt is not None:
                kwargs["FilterExpression"] = filt
            resp = self._table.query(**kwargs)
            debug = f"Query GSI {self.gsi_name} region={p['region']} order={p['order']}"
        else:
            kwargs = {}
            if filt is not None:
                kwargs["FilterExpression"] = filt
            resp = self._table.scan(**kwargs)
            debug = "Scan + Filter"

        rows = [self._to_row(it) for it in resp.get("Items", [])]
        # Scan は未ソート。sort 指定があれば（または region 無し売上ソート）メモリで整える
        if p["sort"]:
            rows.sort(key=lambda r: r.get(p["sort"], 0), reverse=(p["order"] == "desc"))
        rows = rows[: p["limit"]]
        return {"rows": rows, "debug": debug + f" limit={p['limit']}"}

    @staticmethod
    def _to_row(item: dict) -> dict:
        # DynamoDB の数値は Decimal で返るので int に直す（JSON化のため）
        return {
            "name": item.get("name"),
            "region": item.get("region"),
            "industry": item.get("industry"),
            "monthly_revenue": int(item.get("monthly_revenue", 0)),
            "status": item.get("status"),
            "last_contact": item.get("last_contact"),
        }
