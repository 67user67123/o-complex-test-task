"""Evaluate retrieval and optionally generation on fictional demo conversations.

Run: python scripts/evaluate.py [--generate] [--output logs/evaluation.json]
This is an opt-in real-model check, not part of the isolated test suite.
"""

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ROOT, get_settings
from app.ollama import OllamaClient
from app.retrieval import KnowledgeIndex, estimate_tokens, serialize_context
from app.schemas import SuggestRequest
from app.service import SuggestionService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--output", default="logs/evaluation.json")
    args = parser.parse_args()
    settings = get_settings()
    ollama = OllamaClient(settings)
    index = KnowledgeIndex(settings, ollama)
    service = SuggestionService(settings, ollama, index)
    examples = json.loads((ROOT / "data" / "examples.json").read_text(encoding="utf-8"))
    report = {
        "model": settings.ollama_model,
        "embedding_model": settings.embedding_model,
        "similarity_threshold": settings.similarity_threshold,
        "context_token_budget": settings.context_token_budget,
        "cases": [],
    }
    for example in examples:
        start = perf_counter()
        fragments = index.search(example["message"], example["history"])
        actual = {fragment["source_id"] for fragment in fragments}
        expected = set(example["expected_sources"])
        entry = {
            "id": example["id"],
            "retrieval_ms": round((perf_counter() - start) * 1000),
            "expected_sources": sorted(expected),
            "sources": [{"id": f["source_id"], "score": f["score"], "kind": f["kind"]} for f in fragments],
            "expected_found": expected <= actual if expected else not actual,
            "context_budget_used": estimate_tokens(serialize_context(fragments)),
            "expected_behavior": example["expected_behavior"],
        }
        if args.generate:
            try:
                reply = service.suggest(SuggestRequest(message=example["message"], history=example["history"]))
                entry["response"] = reply.model_dump()
            except Exception as exc:
                entry["error"] = str(exc)
        report["cases"].append(entry)
        print(json.dumps(entry, ensure_ascii=False), flush=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if any(not case["expected_found"] or "error" in case for case in report["cases"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
