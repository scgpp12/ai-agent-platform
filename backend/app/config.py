"""
設定（環境変数で上書き可能）。依存最小のため pydantic-settings は使わず os.getenv。

各 backend スイッチで「ローカル(無料)」と「本番(AWS)」を切り替える:
  LLM_BACKEND   : echo | ollama | bedrock
  EMBED_BACKEND : hashing | ollama | bedrock
  DATA_BACKEND  : sqlite | dynamo
  AUTH_BACKEND  : hs256 | cognito
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_BASE = Path(__file__).resolve().parent


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    # --- LLM Provider 選択 ---
    llm_backend: str = os.getenv("LLM_BACKEND", "echo")       # echo / ollama / bedrock
    embed_backend: str = os.getenv("EMBED_BACKEND", "hashing")  # hashing / ollama / bedrock
    data_backend: str = os.getenv("DATA_BACKEND", "sqlite")   # sqlite / dynamo
    auth_backend: str = os.getenv("AUTH_BACKEND", "hs256")    # hs256 / cognito

    # --- Ollama ---
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3:8b")
    ollama_embed_model: str = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")

    # --- llama-swap / OpenAI 兼容（sons02 :8080 本地免费 LLM）---
    llamaswap_base_url: str = os.getenv("LLAMASWAP_BASE_URL", "http://10.32.1.41:8080/v1")
    llamaswap_model: str = os.getenv("LLAMASWAP_MODEL", "qwen3.6")

    # --- Bedrock（東京）---
    aws_region: str = os.getenv("AWS_REGION", "ap-northeast-1")
    # Claude は INFERENCE_PROFILE 必須（model-id 直叩きは不可）
    bedrock_model_id: str = os.getenv("BEDROCK_MODEL_ID", "jp.anthropic.claude-haiku-4-5-20251001-v1:0")
    bedrock_embed_model: str = os.getenv("BEDROCK_EMBED_MODEL", "amazon.titan-embed-text-v2:0")

    # --- ローカルデータ(SQLite/JSON) ---
    db_path: str = os.getenv("DB_PATH", str(_BASE / "data" / "sales.db"))
    kb_path: str = os.getenv("KB_PATH", str(_BASE / "data" / "knowledge_base.json"))

    # --- DynamoDB（本番）---
    customers_table: str = os.getenv("CUSTOMERS_TABLE", "ai-agent-platform-customers")
    knowledge_table: str = os.getenv("KNOWLEDGE_TABLE", "ai-agent-platform-knowledge")

    # --- 認証 ---
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-secret-change-me")   # HS256用
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    dev_no_auth: bool = field(default_factory=lambda: _flag("DEV_NO_AUTH", "0"))
    # Cognito（auth_backend=cognito のとき使う）
    cognito_region: str = os.getenv("COGNITO_REGION", os.getenv("AWS_REGION", "ap-northeast-1"))
    cognito_user_pool_id: str = os.getenv("COGNITO_USER_POOL_ID", "")
    cognito_app_client_id: str = os.getenv("COGNITO_APP_CLIENT_ID", "")

    # --- オーケストレーション ---
    step_timeout: float = float(os.getenv("STEP_TIMEOUT", "60"))

    @property
    def cognito_issuer(self) -> str:
        """Cognito の iss（JWKS取得とissuer検証に使う）。"""
        return f"https://cognito-idp.{self.cognito_region}.amazonaws.com/{self.cognito_user_pool_id}"

    @property
    def cognito_jwks_url(self) -> str:
        return f"{self.cognito_issuer}/.well-known/jwks.json"


settings = Settings()
