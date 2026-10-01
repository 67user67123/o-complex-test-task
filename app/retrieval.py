"""Local, persistent retrieval. The source JSON is opened only during indexing."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.errors import NotFoundError

from app.errors import ServiceError

logger = logging.getLogger(__name__)
COLLECTION_NAME = "knowledge-v1"
CHUNK_VERSION = "atomic-paragraphs-v1"
SUPPORT_INTENT = re.compile(
    r"\b(?:возврат\w*|верну(?:ть|л|ла|ли|лся|лась)\w*|обмен\w*|неисправ\w*|"
    r"полом\w*|слома\w*|протека\w*|протеч\w*|брак\w*|поврежд\w*|"
    r"недовол\w*|претензи\w*|жалоб\w*|не\s+(?:работа\w*|включа\w*)|"
    r"refund\w*|broken|defect\w*|malfunction\w*|leak\w*|complain\w*|"
    r"(?:want\s+to|can\s+i)\s+return|not\s+working)\b",
    re.IGNORECASE,
)


def support_search_query(message: str) -> str | None:
    """Conservative MVP heuristic for complaints, returns and unresolved faults.

    A product name can dominate an embedding of a short complaint. For Russian
    messages, remove Latin model words from the *additional FAQ topic*, keeping
    the customer's actual problem. Normal product searches keep model names.
    This is not a complete intent classifier: an ambiguous support phrase is
    deliberately handled as support, and does not trigger a sales suggestion.
    """
    if not SUPPORT_INTENT.search(message):
        return None
    topic = message
    if re.search(r"[а-яё]", message, re.IGNORECASE):
        topic = re.sub(r"\b[A-Za-z][A-Za-z0-9_-]*\b", " ", topic)
    return re.sub(r"\s+", " ", topic).strip()


def estimate_tokens(text: str) -> int:
    """Conservative budget: one UTF-8 byte counts as one token.

    Byte-based tokenizers need no more tokens than there are bytes. This estimate
    intentionally leaves spare room for Russian text without downloading another
    tokenizer. Budgets apply to serialized knowledge, not the whole model prompt.
    """
    return len(text.encode("utf-8"))


def serialize_context(fragments: list[dict]) -> str:
    """Use this representation in the prompt so metadata fits the same budget."""
    return json.dumps(fragments, ensure_ascii=False, separators=(",", ":"))


def chunk_text(text: str, budget: int) -> list[str]:
    """Pack complete paragraphs, keeping prices and their conditions together.

    A paragraph is an atomic unit authored in the source JSON. The chunk budget is
    a soft target: an oversized paragraph remains intact. Indexing rejects an
    atomic paragraph larger than the whole context; source facts are never cut.
    """
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        joined = f"{current}\n\n{paragraph}" if current else paragraph
        if current and estimate_tokens(joined) > budget:
            chunks.append(current)
            current = paragraph
        else:
            current = joined
    if current:
        chunks.append(current)
    return chunks


class KnowledgeIndex:
    """Chroma + local embeddings, with incremental indexing and freshness checks."""

    def __init__(self, settings: Any, ollama: Any):
        self.settings = settings
        self.ollama = ollama
        self._client = None
        self._lock = threading.RLock()

    @property
    def manifest_path(self) -> Path:
        return Path(self.settings.chroma_path) / "manifest.json"

    def _signature(self) -> str:
        config = {
            "embedding_model": self.settings.embedding_model,
            "chunk_version": CHUNK_VERSION,
            "chunk_token_budget": self.settings.chunk_token_budget,
            "distance": "cosine",
        }
        return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()

    def _source_stat(self) -> dict:
        path = Path(self.settings.knowledge_path).resolve()
        stat = path.stat()
        return {
            "path": str(path),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "ctime_ns": stat.st_ctime_ns,
        }

    def _db(self):
        if self._client is None:
            self._client = chromadb.PersistentClient(
                path=str(self.settings.chroma_path),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        return self._client

    def _collection(self):
        # Explicitly disable Chroma's default embedder: only local Ollama is used.
        return self._db().get_collection(COLLECTION_NAME, embedding_function=None)

    def _write_manifest(self, manifest: dict) -> None:
        path = self.manifest_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def status(self) -> dict:
        """Read small metadata and file stat, never the knowledge file content."""
        with self._lock:
            if not self.manifest_path.exists():
                return {"status": "missing", "count": 0, "message": "Индекс не создан. Выполните python -m app.index."}
            try:
                manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                count = manifest.get("count", 0)
                if manifest.get("state") != "ready":
                    return {"status": "stale", "count": count, "message": "Индексация не завершена. Выполните python -m app.index."}
                if manifest.get("signature") != self._signature():
                    return {"status": "stale", "count": count, "message": "Изменились модель или разбиение. Выполните python -m app.index."}
                largest = manifest.get("max_fragment_bytes")
                if largest is None:
                    return {"status": "stale", "count": count, "message": "Обновите метаданные индекса: выполните python -m app.index."}
                if largest > self.settings.context_token_budget:
                    return {"status": "stale", "count": count, "message": "Фрагмент индекса превышает бюджет контекста. Увеличьте CONTEXT_TOKEN_BUDGET или разбейте длинные абзацы базы и повторите индексацию."}
                if manifest.get("source") != self._source_stat():
                    return {"status": "stale", "count": count, "message": "База знаний изменилась. Выполните python -m app.index."}
                collection = self._collection()
                if collection.count() != count or (collection.metadata or {}).get("signature") != self._signature():
                    return {"status": "stale", "count": count, "message": "Индекс неполный. Выполните python -m app.index."}
                return {"status": "ready", "count": count, "message": "Локальный индекс готов."}
            except FileNotFoundError:
                return {"status": "stale", "count": 0, "message": "Файл базы знаний отсутствует. Проверьте KNOWLEDGE_PATH."}
            except NotFoundError:
                return {"status": "missing", "count": 0, "message": "Коллекция индекса отсутствует. Выполните python -m app.index."}
            except Exception:
                logger.exception("Cannot inspect knowledge index")
                return {"status": "error", "count": 0, "message": "Не удалось прочитать индекс. Проверьте журнал сервера и переиндексируйте базу."}

    def _load_records(self) -> list[dict]:
        payload = json.loads(Path(self.settings.knowledge_path).read_text(encoding="utf-8"))
        records = payload.get("records") if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            raise ValueError("knowledge.json должен содержать список records")
        seen: set[str] = set()
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("Каждая запись базы должна быть объектом")
            for field in ("id", "title", "kind", "text"):
                if not isinstance(record.get(field), str) or not record[field].strip():
                    raise ValueError(f"Запись {record.get('id', '?')}: требуется непустое поле {field}")
            if record["id"] in seen:
                raise ValueError(f"Повторяющийся id: {record['id']}")
            seen.add(record["id"])
            if record["kind"] not in {"product", "faq", "upsell"}:
                raise ValueError(f"Неизвестный тип записи: {record['kind']}")
            if record["kind"] in {"product", "upsell"} and not record.get("product_id"):
                raise ValueError(f"Записи {record['id']} требуется product_id")
            if record.get("product_id") is not None and not isinstance(record["product_id"], str):
                raise ValueError("product_id должен быть строкой")
        product_ids = {r["product_id"] for r in records if r["kind"] == "product"}
        for record in records:
            if record["kind"] == "upsell" and record["product_id"] not in product_ids:
                raise ValueError(f"Допродажа {record['id']} ссылается на неизвестный product_id")
        return records

    def sync(self) -> dict:
        """Embed changed fragments only; delete removed records and obsolete chunks."""
        with self._lock:
            try:
                before = self._source_stat()
                records = self._load_records()
                if self._source_stat() != before:
                    raise ServiceError("knowledge_changed", "База изменилась во время чтения. Повторите индексацию.")
                fragments: dict[str, dict] = {}
                max_fragment_bytes = 2
                for record in records:
                    record_hash = hashlib.sha256(
                        json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
                    ).hexdigest()
                    for number, chunk in enumerate(chunk_text(record["text"], self.settings.chunk_token_budget)):
                        fragment_id = f"{record['id']}:{number}"
                        fragments[fragment_id] = {
                            "text": chunk,
                            "metadata": {
                                "source_id": record["id"], "title": record["title"],
                                "kind": record["kind"], "product_id": record.get("product_id") or "",
                                "updated_at": record.get("updated_at", ""), "content_hash": record_hash,
                            },
                        }
                        # Measure the exact prompt format, including metadata and
                        # the longest positive rounded cosine score representation.
                        fragment_bytes = estimate_tokens(serialize_context([{
                            "id": fragment_id, "source_id": record["id"], "title": record["title"],
                            "kind": record["kind"], "text": chunk, "score": 0.9999,
                            "product_id": record.get("product_id") or None,
                        }]))
                        max_fragment_bytes = max(max_fragment_bytes, fragment_bytes)
                        if fragment_bytes > self.settings.context_token_budget:
                            raise ValueError(
                                f"Запись {record['id']}: абзац с метаданными ({fragment_bytes} байт) "
                                "превышает CONTEXT_TOKEN_BUDGET. Разбейте абзац, сохранив цену с условиями, "
                                "или увеличьте бюджет контекста."
                            )
                signature = self._signature()
                previous = {}
                if self.manifest_path.exists():
                    try:
                        previous = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                    except (ValueError, OSError):
                        pass
                rebuild = previous.get("signature") != signature
                # Any failed/interrupted mutation leaves an explicitly unusable index.
                self._write_manifest({"state": "indexing", "signature": signature, "count": 0})
                db = self._db()
                try:
                    collection = self._collection()
                    rebuild = rebuild or (collection.metadata or {}).get("signature") != signature
                    if rebuild:
                        db.delete_collection(COLLECTION_NAME)
                        collection = None
                except NotFoundError:
                    collection = None
                    rebuild = True
                if collection is None:
                    collection = db.create_collection(
                        COLLECTION_NAME, embedding_function=None,
                        metadata={"signature": signature},
                        configuration={"hnsw": {"space": "cosine"}},
                    )
                existing = collection.get(include=["metadatas"])
                hashes = {item_id: metadata.get("content_hash") for item_id, metadata in zip(
                    existing["ids"], existing["metadatas"] or []
                )}
                changed = [item_id for item_id, item in fragments.items()
                           if hashes.get(item_id) != item["metadata"]["content_hash"]]
                removed = sorted(set(hashes) - set(fragments))
                batch_size = max(1, min(self.settings.embed_batch_size, 128))
                for offset in range(0, len(changed), batch_size):
                    ids = changed[offset:offset + batch_size]
                    items = [fragments[item_id] for item_id in ids]
                    documents = [item["text"] for item in items]
                    embeddings = self.ollama.embed([
                        f"{item['metadata']['title']}\n{item['text']}" for item in items
                    ])
                    collection.upsert(ids=ids, embeddings=embeddings, documents=documents,
                                      metadatas=[item["metadata"] for item in items])
                for offset in range(0, len(removed), batch_size):
                    collection.delete(ids=removed[offset:offset + batch_size])
                if self._source_stat() != before:
                    raise ServiceError("knowledge_changed", "База изменилась во время индексации. Повторите команду.")
                self._write_manifest({
                    "state": "ready", "signature": signature, "source": before,
                    "count": len(fragments), "max_fragment_bytes": max_fragment_bytes,
                    "indexed_at": datetime.now(timezone.utc).isoformat(),
                })
                return {"status": "ready", "records": len(records), "count": len(fragments),
                        "updated": len(changed), "deleted": len(removed),
                        "unchanged": len(fragments) - len(changed), "rebuilt": rebuild}
            except ServiceError:
                raise
            except (ValueError, FileNotFoundError) as exc:
                raise ServiceError("invalid_knowledge", f"Не удалось подготовить базу знаний: {exc}") from exc
            except Exception as exc:
                logger.exception("Knowledge indexing failed")
                raise ServiceError("index_error", "Не удалось обновить локальный индекс. Проверьте журнал сервера.") from exc

    def _query(self, collection: Any, embedding: list[float], where: dict, limit: int) -> list[dict]:
        if limit <= 0 or not collection.count():
            return []
        result = collection.query(
            query_embeddings=[embedding], n_results=min(limit, collection.count()),
            where=where, include=["documents", "metadatas", "distances"],
        )
        fragments = []
        for item_id, document, metadata, distance in zip(
            result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]
        ):
            score = max(-1.0, min(1.0, 1.0 - distance))
            if score < self.settings.similarity_threshold:
                continue
            fragments.append({
                "id": item_id, "source_id": metadata["source_id"], "title": metadata["title"],
                "kind": metadata["kind"], "text": document, "score": round(score, 4),
                "product_id": metadata.get("product_id") or None,
            })
        return fragments

    def search(self, message: str, history: list[dict]) -> list[dict]:
        """Retrieve bounded evidence and related offers, without reading source JSON."""
        with self._lock:
            state = self.status()
            if state["status"] != "ready":
                raise ServiceError(f"index_{state['status']}", state["message"])
            if not state["count"]:
                return []
            # The latest question leads; the final four turns resolve references such as «она».
            recent = "\n".join(f"{turn.get('role', '')}: {turn.get('content', '')}"
                               for turn in history[-4:])
            query = f"{message}\n\nКонтекст диалога:\n{recent}" if recent else message
            query = query.encode("utf-8")[:8000].decode("utf-8", errors="ignore")
            support_topic = support_search_query(message)
            # A separate FAQ query addresses the latest problem, free from model
            # names and older sales talk that otherwise dominate similarity.
            if support_topic:
                query = support_topic.encode("utf-8")[:8000].decode("utf-8", errors="ignore")
            embedding = self.ollama.embed([query])[0]
            try:
                collection = self._collection()
                if support_topic:
                    facts = self._query(collection, embedding, {"kind": "faq"}, min(2, self.settings.top_k))
                else:
                    facts = self._query(collection, embedding, {"kind": {"$in": ["faq", "product"]}},
                                        self.settings.top_k)
                selected: list[dict] = []
                # Reserve space for an offer after the first two answer fragments.
                # Filling all top_k facts first often leaves no room for any offer.
                for fact in facts[:2]:
                    if estimate_tokens(serialize_context(selected + [fact])) <= self.settings.context_token_budget:
                        selected.append(fact)
                parents = sorted({item["product_id"] for item in facts if item.get("product_id")})
                if parents and self.settings.upsell_top_k and not support_topic:
                    offers = self._query(collection, embedding, {"$and": [
                        {"kind": "upsell"}, {"product_id": {"$in": parents}},
                    ]}, self.settings.upsell_top_k)
                    for offer in offers:
                        # Include the matching parent fact together with its offer.
                        # No offer can refer only to evidence dropped by the budget.
                        additions = []
                        if not any(item.get("product_id") == offer["product_id"] for item in selected):
                            additions.append(next(item for item in facts if item.get("product_id") == offer["product_id"]))
                        additions.append(offer)
                        if estimate_tokens(serialize_context(selected + additions)) <= self.settings.context_token_budget:
                            selected.extend(additions)
                selected_ids = {item["id"] for item in selected}
                for fact in facts:
                    if fact["id"] not in selected_ids and estimate_tokens(serialize_context(selected + [fact])) <= self.settings.context_token_budget:
                        selected.append(fact)
                        selected_ids.add(fact["id"])
                # Reject an index changed by a separate indexing process mid-request.
                if self.status()["status"] != "ready":
                    raise ServiceError("index_stale", "Индекс изменился во время поиска. Повторите запрос после индексации.")
                return selected
            except ServiceError:
                raise
            except Exception as exc:
                logger.exception("Knowledge search failed")
                raise ServiceError("index_error", "Ошибка поиска в локальном индексе. Попробуйте переиндексировать базу.") from exc
