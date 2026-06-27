"""
AWS Lambda エントリポイント
============================

既存の FastAPI アプリ(app.main:app)を Mangum でラップするだけ。
→ ローカルでは uvicorn、本番では Lambda、**同じ FastAPI コードを動かす**。

API Gateway(HTTP API) の event を Mangum が ASGI に変換して app に渡す。
CDK の Lambda の handler 設定は `handler.handler`。
"""
from __future__ import annotations

from mangum import Mangum

from app.main import app

handler = Mangum(app)
