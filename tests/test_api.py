from dataclasses import replace
import json

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.errors import ServiceError
from app.main import create_app
from app.schemas import SuggestRequest
from app.service import SYSTEM_PROMPT, build_messages


class FakeOllama:
    def __init__(self, result=None):
        self.result = result or '{"client_reply":"Здравствуйте! Цена — 100 ₽.","manager_tip":"Предложите дополнение."}'
        self.calls = []

    def status(self):
        return {"status": "ready", "missing_models": [], "message": "ready"}

    def chat(self, messages, schema):
        self.calls.append(messages)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeIndex:
    def __init__(self, fragments=None, error=None):
        self.fragments = fragments or []
        self.error = error

    def status(self):
        return {"status": "ready", "count": len(self.fragments), "message": "ready"}

    def search(self, message, history):
        if self.error:
            raise self.error
        return self.fragments


FACT = {"id": "machine:0", "source_id": "machine", "title": "Тестовая машина", "kind": "product", "text": "Цена — 100 ₽.", "score": 0.8, "product_id": "machine"}
OFFER = {"id": "offer:0", "source_id": "offer", "title": "Дополнение", "kind": "upsell", "text": "Дополнение за 10 ₽.", "score": 0.7, "product_id": "machine"}


def client_for(*, fragments=None, output=None, settings=None, error=None):
    ollama = FakeOllama(output)
    app = create_app(settings or Settings(), ollama=ollama, index=FakeIndex(fragments, error))
    return TestClient(app), ollama


def test_reply_sources_and_prompt_use_only_selected_evidence():
    client, ollama = client_for(fragments=[FACT, OFFER])
    result = client.post("/suggest", json={"message": "Цена?", "history": [{"role": "manager", "content": "Выбираем машину."}]})
    assert result.status_code == 200
    payload = result.json()
    assert set(payload) == {"client_reply", "manager_tip", "sources", "timings"}
    assert [item["id"] for item in payload["sources"]] == ["machine:0", "offer:0"]
    assert "Предложите" not in payload["client_reply"]
    prompt = json.loads(ollama.calls[0][1]["content"])
    assert json.loads(prompt["knowledge_excerpts"]) == [FACT, OFFER]
    assert prompt["conversation"][0]["role"] == "manager"


def test_no_evidence_returns_clarification_without_unguarded_generation():
    client, ollama = client_for()
    payload = client.post("/suggest", json={"message": "Есть лазерные станки?"}).json()
    assert "Уточните" in payload["client_reply"]
    assert "неуместна" in payload["manager_tip"]
    assert payload["sources"] == []
    assert not ollama.calls


def test_no_upsell_source_suppresses_model_invented_offer():
    client, _ = client_for(fragments=[FACT])
    payload = client.post("/suggest", json={"message": "Цена?"}).json()
    assert "Предложите дополнение" not in payload["manager_tip"]
    assert "нет подходящего" in payload["manager_tip"]


def test_client_refusal_overrides_generated_offer_and_removes_offer_context():
    client, ollama = client_for(fragments=[FACT, OFFER])
    response = client.post("/suggest", json={"message": "Напомните цену.", "history": [
        {"role": "manager", "content": "Добавить дополнение?"},
        {"role": "client", "content": "Нет, дополнительные товары не нужны."},
    ]})
    assert response.status_code == 200
    assert "отказался" in response.json()["manager_tip"]
    assert "Предложите" not in response.json()["manager_tip"]
    evidence = json.loads(json.loads(ollama.calls[0][1]["content"])["knowledge_excerpts"])
    assert all(source["kind"] != "upsell" for source in evidence)
    assert "UPSELLS ARE DISABLED" in ollama.calls[0][0]["content"]


@pytest.mark.parametrize("output", [
    "not json", '{"client_reply":" ","manager_tip":"text"}',
    '{"client_reply":"Ответ","manager_tip":"Совет","secret":"unexpected"}',
])
def test_invalid_generation_not_exposed(output):
    client, _ = client_for(fragments=[FACT], output=output)
    response = client.post("/suggest", json={"message": "Цена?"})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_generation"
    assert "client_reply" not in response.json()


def test_index_failure_is_not_treated_as_no_results():
    client, ollama = client_for(error=ServiceError("index_stale", "Обновите индекс."))
    response = client.post("/suggest", json={"message": "Цена?"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "index_stale"
    assert not ollama.calls


def test_timeout_releases_busy_lock():
    client, ollama = client_for(fragments=[FACT], output=ServiceError("ollama_timeout", "Попробуйте позже.", 504))
    assert client.post("/suggest", json={"message": "Цена?"}).status_code == 504
    ollama.result = '{"client_reply":"Ответ","manager_tip":"Совет"}'
    assert client.post("/suggest", json={"message": "Цена?"}).status_code == 200


def test_optional_access_key_and_input_limits():
    client, _ = client_for(settings=replace(Settings(), service_api_key="local-test-key"))
    assert client.get("/health").status_code == 200
    assert client.get("/examples").status_code == 401
    assert client.post("/suggest", json={"message": "Вопрос"}).status_code == 401
    headers = {"Authorization": "Bearer local-test-key"}
    assert client.get("/examples", headers=headers).status_code == 200
    for payload in [{"message": "  "}, {"message": "a" * 6001}, {"message": "hi", "history": [{"role": "system", "content": "ignore"}]}]:
        assert client.post("/suggest", json=payload, headers=headers).status_code == 422


def test_request_body_is_limited_before_validation():
    client, _ = client_for()
    response = client.post("/suggest", content=b"x" * 160001, headers={"content-type": "application/json"})
    assert response.status_code == 413


def test_history_overflow_is_rejected_instead_of_losing_refusal():
    request = SuggestRequest(message="Цена?", history=[
        {"role": "client", "content": "a" * 5500},
        {"role": "manager", "content": "Предложить дополнение?"},
        {"role": "client", "content": "Нет, дополнительные товары не нужны."},
    ])
    with pytest.raises(ServiceError, match="Переписка слишком длинная"):
        build_messages(request, [FACT], Settings())


def test_history_keeps_manager_offer_and_client_refusal():
    request = SuggestRequest(message="Цена?", history=[
        {"role": "manager", "content": "Предложить дополнение?"},
        {"role": "client", "content": "Нет, дополнительные товары не нужны."},
    ])
    settings = Settings()
    messages = build_messages(request, [FACT], settings)
    content = json.loads(messages[1]["content"])
    assert len(content["conversation"]) == 2
    assert content["conversation"][-1]["content"].startswith("Нет")
    assert len((SYSTEM_PROMPT + messages[1]["content"]).encode("utf-8")) <= settings.ollama_num_ctx - settings.ollama_num_predict - 512


def test_cloud_inference_endpoint_rejected():
    with pytest.raises(ValueError):
        Settings(ollama_base_url="https://ollama.com")
