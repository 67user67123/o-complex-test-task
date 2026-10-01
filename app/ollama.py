import math

import httpx

from app.config import Settings
from app.errors import ServiceError


class OllamaClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _request(self, method: str, path: str, payload=None, timeout=None) -> dict:
        try:
            with httpx.Client(
                base_url=self.settings.ollama_base_url,
                timeout=httpx.Timeout(timeout or self.settings.ollama_timeout, connect=5),
                trust_env=False,
                follow_redirects=False,
            ) as client:
                response = client.request(method, path, json=payload)
            if response.status_code == 404:
                raise ServiceError("model_missing", "Нужная модель не найдена в Ollama. Проверьте загрузку Qwen и bge-m3.")
            if response.status_code >= 400 or response.is_redirect:
                raise ServiceError("ollama_error", "Ollama не смогла обработать запрос. Проверьте модель и доступную память.", 502)
            data = response.json()
            if not isinstance(data, dict) or data.get("error"):
                raise ValueError("Invalid Ollama response")
            return data
        except httpx.TimeoutException as exc:
            raise ServiceError("ollama_timeout", "Модель не успела ответить. Повторите запрос или увеличьте время ожидания.", 504) from exc
        except httpx.RequestError as exc:
            raise ServiceError("ollama_unavailable", "Нет соединения с Ollama. Запустите Ollama и повторите запрос.") from exc
        except (ValueError, TypeError) as exc:
            raise ServiceError("ollama_invalid_response", "Ollama вернула некорректный ответ. Повторите запрос.", 502) from exc

    def status(self) -> dict:
        try:
            data = self._request("GET", "/api/tags", timeout=5)
            names = {item.get("name", "") for item in data.get("models", [])}
            required = [self.settings.ollama_model, self.settings.embedding_model]
            missing = [name for name in required if name not in names and f"{name}:latest" not in names]
            return {
                "status": "ready" if not missing else "missing_models",
                "missing_models": missing,
                "message": "Модели готовы." if not missing else "Загрузите отсутствующие модели в Ollama.",
            }
        except ServiceError as exc:
            return {"status": "unavailable", "missing_models": [], "message": exc.message}

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        data = self._request("POST", "/api/embed", {
            "model": self.settings.embedding_model,
            "input": texts,
            "truncate": False,
            "keep_alive": "5m",
        })
        vectors = data.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise ServiceError("embedding_invalid", "Модель поиска вернула некорректные векторы.", 502)
        size = len(vectors[0]) if vectors and isinstance(vectors[0], list) else 0
        for vector in vectors:
            if not isinstance(vector, list) or not size or len(vector) != size or any(
                not isinstance(number, (int, float)) or not math.isfinite(number) for number in vector
            ):
                raise ServiceError("embedding_invalid", "Модель поиска вернула некорректные векторы.", 502)
        return vectors

    def chat(self, messages: list[dict], schema: dict) -> str:
        data = self._request("POST", "/api/chat", {
            "model": self.settings.ollama_model,
            "messages": messages,
            "format": schema,
            "stream": False,
            "think": False,
            "keep_alive": "5m",
            "options": {
                "temperature": 0.2,
                "num_ctx": self.settings.ollama_num_ctx,
                "num_predict": self.settings.ollama_num_predict,
                "seed": 42,
            },
        })
        if data.get("done_reason") == "length":
            raise ServiceError("generation_truncated", "Ответ модели прервался по лимиту длины. Повторите запрос или увеличьте OLLAMA_NUM_PREDICT.", 502)
        content = data.get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise ServiceError("generation_empty", "Модель не вернула текст ответа. Повторите запрос.", 502)
        return content
