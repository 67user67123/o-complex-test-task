"""Exercise real persistent Chroma with small deterministic local embeddings."""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.errors import ServiceError
from app.retrieval import KnowledgeIndex, chunk_text, estimate_tokens, serialize_context, support_search_query


class FakeEmbedder:
    def __init__(self):
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(texts)
        groups = [{"coffee", "espresso", "cappuccino"}, {"cleaner", "descale"},
                  {"laser", "titanium", "microscope"}, {"tea", "kettle"}]
        result = []
        for text in texts:
            words = set(re.findall(r"\w+", text.lower()))
            vector = [float(bool(words & group)) for group in groups]
            result.append(vector + [0.0 if any(vector) else 1.0])
        return result


def record(item_id, text, kind="product", product_id=None):
    return {"id": item_id, "title": item_id, "kind": kind,
            "product_id": product_id or item_id, "updated_at": "2026-10-01", "text": text}


@pytest.fixture
def setup_index(tmp_path):
    settings = SimpleNamespace(
        knowledge_path=tmp_path / "knowledge.json", chroma_path=tmp_path / "chroma",
        embedding_model="fake-local", embed_batch_size=2, top_k=5, upsell_top_k=2,
        similarity_threshold=0.45, context_token_budget=3000, chunk_token_budget=400,
    )
    embedder = FakeEmbedder()
    index = KnowledgeIndex(settings, embedder)

    def write(records):
        settings.knowledge_path.write_text(json.dumps({"records": records}), encoding="utf-8")

    return settings, embedder, index, write


def test_incremental_update_delete_and_persistence(setup_index):
    settings, embedder, index, write = setup_index
    write([record("machine", "coffee price 100"), record("kettle", "tea price 50")])
    assert index.sync()["updated"] == 2
    assert index.status()["status"] == "ready"
    calls = len(embedder.calls)
    unchanged = index.sync()
    assert unchanged["updated"] == 0
    assert len(embedder.calls) == calls

    write([record("machine", "coffee new price 200")])
    assert index.status()["status"] == "stale"
    result = index.sync()
    assert result["updated"] == 1
    assert result["deleted"] == 1
    assert embedder.calls[-1] == ["machine\ncoffee new price 200"]

    # A fresh service object reuses saved embeddings and sees no deleted record.
    reopened = KnowledgeIndex(settings, embedder)
    hits = reopened.search("espresso", [])
    assert [hit["source_id"] for hit in hits] == ["machine"]
    assert "200" in hits[0]["text"]
    assert reopened.search("tea", []) == []


def test_search_reads_only_index_and_filters_unrelated_offers(setup_index, monkeypatch):
    settings, embedder, index, write = setup_index
    write([
        record("machine", "coffee machine"),
        record("beans", "coffee beans offer", "upsell", "machine"),
        record("microscope", "titanium laser"),
        # Semantically similar offer, but an explicit link to another product.
        record("wrong-offer", "coffee offer", "upsell", "microscope"),
    ])
    index.sync()
    read_text = Path.read_text

    def guard(path, *args, **kwargs):
        assert path != settings.knowledge_path, "search must never read knowledge.json"
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guard)
    embedder.calls.clear()
    hits = index.search("espresso", [])
    assert {hit["source_id"] for hit in hits} == {"machine", "beans"}
    assert len(embedder.calls) == 1
    assert embedder.calls[0] == ["espresso"]
    assert index.search("weather tomorrow", []) == []


def test_hard_context_budget_counts_metadata_without_cutting_facts(setup_index):
    settings, _, index, write = setup_index
    records = [record(f"machine-{i}", f"coffee costs {100 + i}; free shipping only above 300.")
               for i in range(12)]
    write(records)
    index.sync()
    settings.context_token_budget = 530
    hits = index.search("coffee", [])
    assert 0 < len(hits) < settings.top_k
    assert estimate_tokens(serialize_context(hits)) <= settings.context_token_budget
    assert all(hit["text"].endswith("free shipping only above 300.") for hit in hits)
    assert all("coffee costs" in hit["text"] for hit in hits)


def test_related_offer_gets_space_before_lower_priority_facts(setup_index):
    settings, _, index, write = setup_index
    write([record(f"fact-{i}", "coffee machine specifications", product_id="machine") for i in range(5)]
          + [record("offer", "coffee beans at 50", "upsell", "machine")])
    index.sync()
    settings.context_token_budget = 760
    hits = index.search("coffee", [])
    assert any(hit["kind"] == "upsell" for hit in hits)
    assert any(hit["kind"] == "product" and hit["product_id"] == "machine" for hit in hits)
    assert estimate_tokens(serialize_context(hits)) <= settings.context_token_budget


def test_lower_budget_marks_index_stale_when_parent_fact_cannot_fit(setup_index):
    settings, _, index, write = setup_index
    write([record("machine", "coffee " + "specification " * 80),
           record("offer", "coffee beans", "upsell", "machine")])
    index.sync()
    settings.context_token_budget = 300
    with pytest.raises(ServiceError) as exc:
        index.search("coffee", [])
    assert exc.value.code == "index_stale"


def test_atomic_paragraph_larger_than_context_is_rejected_during_sync(setup_index):
    settings, _, index, write = setup_index
    settings.context_token_budget = 400
    write([record("long-source", "coffee " + "specification " * 80)])
    with pytest.raises(ServiceError) as exc:
        index.sync()
    assert exc.value.code == "invalid_knowledge"
    assert "long-source" in exc.value.message
    assert "Разбейте абзац" in exc.value.message


def test_missing_stale_and_embedding_change_require_indexing(setup_index):
    settings, _, index, write = setup_index
    assert index.status()["status"] == "missing"
    with pytest.raises(ServiceError) as missing:
        index.search("coffee", [])
    assert missing.value.code == "index_missing"
    write([record("machine", "coffee machine")])
    index.sync()
    settings.embedding_model = "new-local-model"
    assert index.status()["status"] == "stale"
    with pytest.raises(ServiceError) as stale:
        index.search("coffee", [])
    assert stale.value.code == "index_stale"
    assert index.sync()["rebuilt"] is True
    assert index.status()["status"] == "ready"


def test_shrinking_record_removes_obsolete_chunks(setup_index):
    settings, _, index, write = setup_index
    settings.chunk_token_budget = 25
    write([record("machine", "coffee specifications\n\ncoffee price and terms")])
    assert index.sync()["count"] == 2
    write([record("machine", "coffee replaced")])
    result = index.sync()
    assert result["deleted"] == 1
    assert result["count"] == 1
    assert [hit["text"] for hit in index.search("coffee", [])] == ["coffee replaced"]


def test_chunking_keeps_price_with_conditions_and_oversized_paragraph_whole():
    price = "Стоимость 490 ₽; бесплатно только при сумме товаров от 30 000 ₽."
    paragraphs = chunk_text(f"Описание товара.\n\n{price}\n\nСроки доставки.", 45)
    assert price in paragraphs
    assert estimate_tokens(price) == len(price.encode("utf-8"))


def test_support_query_retrieves_problem_faq_despite_dominant_product_name(setup_index):
    settings, _, _, write = setup_index

    class BrandBiasedEmbedder:
        def embed(self, texts):
            # A product word dominates unless we search the actual problem.
            return [[1.0, 0.0] if "BrandX" in text else [0.0, 1.0] for text in texts]

    write([
        record("opaque-a", "BrandX appliance description", product_id="arbitrary-product"),
        record("opaque-b", "BrandX special offer", "upsell", "arbitrary-product"),
        record("opaque-c", "Что делать, если товар протекает", "faq"),
        record("opaque-d", "Как оформить возврат товара", "faq"),
    ])
    index = KnowledgeIndex(settings, BrandBiasedEmbedder())
    index.sync()
    hits = index.search("BrandX протекает, хочу вернуть товар", [
        {"role": "client", "content": "Мне понравился BrandX"},
        {"role": "manager", "content": "Для BrandX есть дополнительное предложение"},
    ])
    assert {hit["source_id"] for hit in hits} == {"opaque-c", "opaque-d"}
    assert all(hit["kind"] == "faq" for hit in hits)


@pytest.mark.parametrize("message", [
    "Прибор сломался", "Товар поврежден", "Хочу возврат денег", "Не включается чайник",
    "The appliance is broken", "Can I return this order?", "I want a refund",
])
def test_support_intent_covers_fault_and_return_variants(message):
    assert support_search_query(message)


def test_regular_product_question_keeps_model_name():
    assert support_search_query("Сколько стоит BrandX и как за ним ухаживать?") is None


def test_failed_indexing_cannot_serve_partial_changes(setup_index, monkeypatch):
    _, embedder, index, write = setup_index
    write([record("machine", "coffee price 100")])
    index.sync()
    write([record("machine", "coffee changed price 200")])

    def unavailable(_texts):
        raise ServiceError("ollama_unavailable", "Offline")

    monkeypatch.setattr(embedder, "embed", unavailable)
    with pytest.raises(ServiceError):
        index.sync()
    assert index.status()["status"] == "stale"


def test_empty_valid_index_is_no_evidence_not_failure(setup_index):
    _, embedder, index, write = setup_index
    write([])
    assert index.sync()["count"] == 0
    assert index.status()["status"] == "ready"
    assert index.search("coffee", []) == []
    assert embedder.calls == []
