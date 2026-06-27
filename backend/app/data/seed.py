"""
SQLite シードデータ（DataQueryAgent 用の営業DB）
================================================

顧客テーブルを作って初期データを入れる。アプリ起動時に1度呼ぶ。
本番なら Aurora 等になるが、練習はファイル1個の SQLite で十分。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_CUSTOMERS = [
    # (name, region, industry, monthly_revenue, status, last_contact)
    ("株式会社あおぞら商事", "東京", "小売", 1200000, "active", "2026-06-01"),
    ("みどりテック株式会社", "東京", "IT", 3500000, "active", "2026-05-20"),
    ("北日本フーズ株式会社", "北海道", "食品", 800000, "prospect", "2026-04-10"),
    ("関西製造株式会社", "大阪", "製造", 5200000, "active", "2026-06-15"),
    ("九州ロジ株式会社", "福岡", "物流", 1500000, "churned", "2026-02-28"),
    ("さくらメディカル株式会社", "東京", "医療", 2800000, "active", "2026-06-18"),
    ("名古屋オート株式会社", "愛知", "製造", 4100000, "prospect", "2026-03-05"),
    ("湘南リゾート株式会社", "神奈川", "観光", 950000, "active", "2026-05-30"),
    ("仙台システム株式会社", "宮城", "IT", 1700000, "prospect", "2026-06-10"),
    ("博多商会株式会社", "福岡", "小売", 600000, "churned", "2026-01-15"),
]


def init_db(db_path: str | Path) -> None:
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS customers")
        conn.execute(
            """
            CREATE TABLE customers (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                region          TEXT NOT NULL,
                industry        TEXT NOT NULL,
                monthly_revenue INTEGER NOT NULL,
                status          TEXT NOT NULL,   -- active / prospect / churned
                last_contact    TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            "INSERT INTO customers (name, region, industry, monthly_revenue, status, last_contact)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            _CUSTOMERS,
        )
        conn.commit()
    finally:
        conn.close()
