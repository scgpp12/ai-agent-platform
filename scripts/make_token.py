"""
テスト用JWTを発行する小道具。
本番では Cognito 等が発行するが、ローカルで /chat を叩くために手元で作る。

使い方:
    python scripts/make_token.py
    # 出力されたトークンを Authorization: Bearer <token> に使う
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import jwt

# app.config と同じ secret/alg を使う（環境変数で合わせる）
SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
ALG = os.getenv("JWT_ALGORITHM", "HS256")


def make_token(sub: str = "sales-user-001", scopes: str = "chat agents", hours: int = 12) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": sub,
        "scope": scopes,
        "iat": now,
        "exp": now + dt.timedelta(hours=hours),
    }
    return jwt.encode(payload, SECRET, algorithm=ALG)


if __name__ == "__main__":
    sub = sys.argv[1] if len(sys.argv) > 1 else "sales-user-001"
    print(make_token(sub))
