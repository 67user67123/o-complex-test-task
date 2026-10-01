"""Small deterministic safeguards for the manager's upsell suggestion.

This is a conservative Russian-first heuristic, not a full dialogue classifier.
An explicit refusal anywhere in the supplied dialogue blocks *all* upsells for
that request, even if it concerned one item or the customer later reconsidered.
Short negatives and statements of ownership require a preceding manager offer;
an answer about stock/ownership alone is not treated as refusal. Only supplied
dialogue is considered; there is no customer profile or persistent memory.
"""

import re

from app.retrieval import support_search_query


SUPPORT_REASON = "Сначала помогите клиенту решить проблему; допродажа сейчас неуместна."
REFUSAL_REASON = "Клиент уже отказался от дополнительных предложений в этом диалоге. Не повторяйте допродажу."

_EXPLICIT_REFUSAL = re.compile(
    r"\b(?:"
    r"не\s+(?:предлагай\w*|надо\s+предлагать|нужно\s+предлагать)|"
    r"(?:дополнительн\w*\s+(?:товар\w*|услуг\w*|предложени\w*|покуп\w*)|"
    r"дополнени\w*|ничего\s+(?:дополнительного|больше))\s+(?:мне\s+)?не\s+нуж\w*|"
    r"(?:не\s+нуж\w*|не\s+хочу)\s+(?:никаких\s+)?дополнительн\w*|"
    r"без\s+(?:всяких\s+)?дополнительн\w*\s+(?:товар\w*|услуг\w*|предложени\w*|покуп\w*)|"
    r"do\s+not\s+(?:offer|suggest)|no\s+(?:additional|extra)\s+(?:items|products|offers)"
    r")\b",
    re.IGNORECASE,
)
_OFFER = re.compile(
    r"\b(?:добав(?:ить|им|лять)|докупить|дозаказать|дополнить|"
    r"предлага(?:ю|ем)|предлож(?:ить|у)|рекомендую|советую|"
    r"возьмете|приобрести|включить\s+в\s+заказ|"
    r"(?:would\s+you\s+like|want)\s+to\s+add|i\s+(?:can\s+)?(?:offer|suggest))\b",
    re.IGNORECASE,
)
_AVAILABILITY_QUESTION = re.compile(
    r"\b(?:есть\s+ли|у\s+вас\b.*\bесть|\w+(?:\s+уже)?\s+есть|"
    r"do\s+you\s+(?:already\s+)?have)\b",
    re.IGNORECASE,
)
_CONTEXTUAL_REFUSAL = re.compile(
    r"^(?:нет|не\s+надо|не\s+нужно|не\s+нужны|не\s+хочу|"
    r"откажусь|без\s+этого|не\s+сейчас|no(?:\s+thanks)?)(?:[,.!;?\s]|$)|"
    r"\b(?:уже\s+есть|уже\s+(?:купил\w*|заказал\w*|приобрел\w*)|"
    r"мне\s+не\s+нуж\w*|у\s+(?:меня|нас)\s+есть|"
    r"i\s+already\s+have)\b",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("ё", "е")).strip()


def _is_offer(text: str) -> bool:
    # A final ownership question changes the meaning of the next «нет».
    # Example: «Добавить кофе? Или у вас уже есть зерна?» — «Нет».
    clauses = [part.strip() for part in re.split(r"[.!?]", text) if part.strip()]
    if clauses and _AVAILABILITY_QUESTION.search(clauses[-1]):
        return False
    return bool(_OFFER.search(text))


def upsell_block_reason(message: str, history: list[dict]) -> str | None:
    """Return a reason to suppress offers, using current support intent and refusals.

    A manager turn sets context for the following client reply. A subsequent
    manager question replaces that context, so «нет» about existing supplies
    cannot be confused with refusing an older offer. Once a real refusal is
    found, it remains applicable to the current request.
    """
    if support_search_query(message):
        return SUPPORT_REASON
    preceding_offer = False
    turns = [*history, {"role": "client", "content": message}]
    for turn in turns:
        text = _normalize(turn.get("content", ""))
        if turn.get("role") == "manager":
            preceding_offer = _is_offer(text)
            continue
        if turn.get("role") != "client":
            continue
        if _EXPLICIT_REFUSAL.search(text):
            return REFUSAL_REASON
        if preceding_offer and _CONTEXTUAL_REFUSAL.search(text):
            return REFUSAL_REASON
        # Consume the offer context with the client's response. Later «нет»
        # without another offer is not enough evidence of a refusal.
        preceding_offer = False
    return None
