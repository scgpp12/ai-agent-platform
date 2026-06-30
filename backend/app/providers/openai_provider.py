"""
OpenAI 兼容 Provider（llama-swap / vLLM / OpenAI / Together 等）
=============================================================

LLMProvider 抽象的又一个实现，走 **OpenAI 兼容** 的 `/v1/chat/completions`。
本项目用它接 sons02 的 **llama-swap(8080)**，把本地免费 LLM 当作一个后端。

- base_url 例：`http://10.32.1.41:8080/v1`（llama-swap）
- model 例：`qwen3.6`（对话主力）
- 关思考链：`chat_template_kwargs={enable_thinking:false}`（llama.cpp/vLLM 扩展字段，
  OpenAI 官方无此字段、其它后端会忽略，所以放着也安全）

【为什么不直接改 OllamaProvider】
llama-swap 不是 Ollama 原生 `/api/chat`，而是 OpenAI 兼容 `/v1`。与其魔改，不如新写一个
实现——这正是 Provider 抽象的好处：**多接一个后端 = 多写一个类，业务代码一行不改**。
要换成真·OpenAI / Together，只改 base_url + api_key 即可。
"""
from __future__ import annotations

import httpx

from .base import LLMProvider


class OpenAICompatProvider(LLMProvider):
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str = "not-needed",   # llama-swap 不校验 key，占位即可
        timeout: float = 120.0,        # 首次请求要载模型，给足时间
        disable_thinking: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.disable_thinking = disable_thinking

    async def chat(self, system: str, user: str, *, temperature: float = 0.2) -> str:
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "stream": False,
        }
        if self.disable_thinking:
            # llama.cpp/vLLM 扩展：关闭思考链。OpenAI /v1 官方关不掉，这里靠后端扩展字段。
            payload["chat_template_kwargs"] = {"enable_thinking": False}

        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
