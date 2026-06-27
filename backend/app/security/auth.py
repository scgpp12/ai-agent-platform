"""
JWT 検証の依存性(Depends)
=========================

【设计意图 / 設計意図】

「認証担当が作る Cognito」を想定し、こちら(プラットフォーム側)は
**JWTを検証する受け口だけ**用意する。トークン発行は Cognito の責務。

- FastAPI の Depends にすることで、各エンドポイントに `user = Depends(require_user)`
  と1行書くだけで保護できる（横断的関心事を宣言的に注入）。
- 検証ロジックを1か所に集約。AUTH_BACKEND で HS256(ローカル) ↔ Cognito(本番) を切替。

【二重防御について】
本番では API Gateway 側にも Cognito JWT Authorizer を付けるので、未認証は Lambda 到達前に弾かれる。
ここでの再検証は defense-in-depth ＋ FastAPI 内で claims を綺麗に扱うため。
"""
from __future__ import annotations

import functools
from dataclasses import dataclass

import jwt  # PyJWT
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import settings

# Authorization: Bearer <token> ヘッダを読む。auto_error=False で自前のエラーにする。
_bearer = HTTPBearer(auto_error=False)


@dataclass
class AuthUser:
    """検証済みトークンから取り出した最小ユーザー情報。"""
    sub: str
    scopes: list[str]
    raw: dict


@functools.lru_cache(maxsize=1)
def _jwks_client() -> "jwt.PyJWKClient":
    """
    Cognito の JWKS クライアント（公開鍵を取得・キャッシュ）。
    lru_cache で1個だけ作る ＝ Lambda コンテナ再利用時に鍵を使い回す（毎回HTTPしない）。
    """
    return jwt.PyJWKClient(settings.cognito_jwks_url)


def _verify_hs256(token: str) -> dict:
    """ローカル開発用 HS256（共有秘密鍵）。"""
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        options={"verify_aud": False},
    )


def _verify_cognito(token: str) -> dict:
    """
    本番 Cognito の RS256 + JWKS 検証。
    id_token を想定（aud=app_client_id）。issuer もユーザープールに固定して検証する。
    """
    signing_key = _jwks_client().get_signing_key_from_jwt(token).key
    return jwt.decode(
        token,
        signing_key,
        algorithms=["RS256"],
        audience=settings.cognito_app_client_id,
        issuer=settings.cognito_issuer,
    )


def verify_token(token: str) -> AuthUser:
    """JWTを検証して AuthUser を返す。失敗は HTTPException(401)。"""
    try:
        if settings.auth_backend == "cognito":
            payload = _verify_cognito(token)
        else:
            payload = _verify_hs256(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "トークンの有効期限切れ")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"無効なトークン: {e}")

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sub クレームがありません")
    raw_scope = payload.get("scope", "")
    scopes = raw_scope.split() if isinstance(raw_scope, str) else list(raw_scope or [])
    return AuthUser(sub=sub, scopes=scopes, raw=payload)


async def require_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    """
    保護したいエンドポイントで `user: AuthUser = Depends(require_user)` と書くための依存性。

    DEV_NO_AUTH=1 のときは検証をスキップ（ローカルで curl 練習しやすくする抜け道）。本番では必ず 0。
    """
    if settings.dev_no_auth:
        return AuthUser(sub="dev-user", scopes=["dev"], raw={"dev": True})
    if creds is None or not creds.credentials:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Authorization: Bearer <token> が必要です",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_token(creds.credentials)
