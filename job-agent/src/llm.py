from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


class OllamaError(RuntimeError):
    pass


@dataclass(frozen=True)
class OllamaClient:
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:7b"
    timeout_seconds: int = 180

    def generate(self, prompt: str, system: str = "") -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_ctx": 20000,
            },
        }
        try:
            response = requests.post(
                f"{self.base_url.rstrip('/')}/api/generate",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise OllamaError(f"Ollama request failed: {exc}") from exc
        except ValueError as exc:
            raise OllamaError("Ollama returned invalid JSON") from exc
        text = str(data.get("response") or "").strip()
        if not text:
            raise OllamaError("Ollama returned an empty response")
        return text


def ollama_client_from_config(config: dict[str, Any]) -> OllamaClient:
    return OllamaClient(
        base_url=str(config.get("base_url") or "http://127.0.0.1:11434"),
        model=str(config.get("model") or "qwen2.5:7b"),
        timeout_seconds=int(config.get("timeout_seconds") or 180),
    )
