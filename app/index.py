"""Run ``python -m app.index`` after editing knowledge.json or embedding settings."""

import json
import sys

from app.config import get_settings
from app.errors import ServiceError
from app.ollama import OllamaClient
from app.retrieval import KnowledgeIndex


def main() -> int:
    settings = get_settings()
    try:
        result = KnowledgeIndex(settings, OllamaClient(settings)).sync()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ServiceError as exc:
        print(f"Ошибка индексации: {exc.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
