from dataclasses import dataclass
from functools import lru_cache
import ipaddress
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
GENERATION_MODEL = "qwen3.5:9b-q4_K_M"


def _path(name: str, default: str) -> Path:
    path = Path(os.getenv(name, default))
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


@dataclass(frozen=True)
class Settings:
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = GENERATION_MODEL
    embedding_model: str = "bge-m3"
    ollama_timeout: float = 180
    ollama_num_ctx: int = 8192
    ollama_num_predict: int = 700
    knowledge_path: Path = ROOT / "data" / "knowledge.json"
    chroma_path: Path = ROOT / "data" / "chroma"
    embed_batch_size: int = 16
    top_k: int = 5
    upsell_top_k: int = 2
    similarity_threshold: float = 0.45
    context_token_budget: int = 3000
    chunk_token_budget: int = 400
    service_api_key: str = ""

    def __post_init__(self):
        url = urlparse(self.ollama_base_url)
        # The project explicitly uses local inference. Avoid accidentally sending
        # conversations to a cloud endpoint via an environment setting.
        host = url.hostname or ""
        local = host == "localhost"
        try:
            addr = ipaddress.ip_address(host)
            local = addr.is_loopback or addr.is_private
        except ValueError:
            pass
        if not local or url.scheme not in {"http", "https"} or url.username or url.password:
            raise ValueError("OLLAMA_BASE_URL должен указывать на localhost или IP в локальной сети.")
        if url.path not in {"", "/"} or url.query or url.fragment:
            raise ValueError("OLLAMA_BASE_URL должен содержать только адрес сервера и порт.")
        if self.ollama_model != GENERATION_MODEL:
            raise ValueError(f"В этом проекте OLLAMA_MODEL должен быть {GENERATION_MODEL}.")
        if self.embedding_model != "bge-m3":
            raise ValueError("EMBEDDING_MODEL должен быть локальной bge-m3.")
        if not 0 <= self.similarity_threshold <= 1:
            raise ValueError("SIMILARITY_THRESHOLD должен быть от 0 до 1.")
        if not 1 <= self.top_k <= 20 or not 0 <= self.upsell_top_k <= 5:
            raise ValueError("TOP_K: 1–20; UPSELL_TOP_K: 0–5.")
        if not 256 <= self.context_token_budget <= 12000 or self.chunk_token_budget < 100:
            raise ValueError("Проверьте CONTEXT_TOKEN_BUDGET и CHUNK_TOKEN_BUDGET.")
        if self.ollama_timeout <= 0 or self.ollama_num_ctx < 8192 or not 128 <= self.ollama_num_predict <= 2000:
            raise ValueError("Проверьте OLLAMA_TIMEOUT, OLLAMA_NUM_CTX (от 8192), OLLAMA_NUM_PREDICT (128–2000).")


@lru_cache
def get_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    return Settings(
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", GENERATION_MODEL),
        embedding_model=os.getenv("EMBEDDING_MODEL", "bge-m3"),
        ollama_timeout=float(os.getenv("OLLAMA_TIMEOUT", "180")),
        ollama_num_ctx=int(os.getenv("OLLAMA_NUM_CTX", "8192")),
        ollama_num_predict=int(os.getenv("OLLAMA_NUM_PREDICT", "700")),
        knowledge_path=_path("KNOWLEDGE_PATH", "data/knowledge.json"),
        chroma_path=_path("CHROMA_PATH", "data/chroma"),
        top_k=int(os.getenv("TOP_K", "5")),
        upsell_top_k=int(os.getenv("UPSELL_TOP_K", "2")),
        similarity_threshold=float(os.getenv("SIMILARITY_THRESHOLD", "0.45")),
        context_token_budget=int(os.getenv("CONTEXT_TOKEN_BUDGET", "3000")),
        chunk_token_budget=int(os.getenv("CHUNK_TOKEN_BUDGET", "400")),
        service_api_key=os.getenv("SERVICE_API_KEY", ""),
    )
