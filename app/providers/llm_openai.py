import json

import httpx

from app.config import Config
from app.providers.errors import ProviderError


class OpenAiLlm:
    def __init__(self, cfg: Config):
        self.base_url = cfg.llm_base_url
        self.api_key = cfg.llm_api_key
        self.model = cfg.llm_model

    def complete_json(self, system: str, user: str) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        try:
            response = httpx.post(f"{self.base_url}/chat/completions",
                                  json=payload, headers=headers, timeout=300)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderError("llm_unavailable", "大模型请求超时", transient=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("llm_unavailable", f"大模型请求失败：{exc}", transient=True) from exc

        content = response.json()["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except ValueError as exc:
            raise ProviderError("llm_bad_json", "大模型未返回合法 JSON") from exc
