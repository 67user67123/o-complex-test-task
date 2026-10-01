"""The offer guard must respect refusals without mistaking missing supplies for one."""

import pytest

from app.policy import REFUSAL_REASON, SUPPORT_REASON, upsell_block_reason


def manager(content):
    return {"role": "manager", "content": content}


def client(content):
    return {"role": "client", "content": content}


def test_demo_refusal_survives_later_price_question():
    history = [
        client("Ищу кофемашину только для черного кофе."),
        manager("Подойдет Linea Black. Добавить Daily Blend 250 г за 650 ₽?"),
        client("Нет, кофе и средства ухода у меня уже есть. Дополнительные товары не нужны."),
    ]
    assert upsell_block_reason("Тогда беру Linea Black. Напомните цену самой кофемашины.", history) == REFUSAL_REASON


@pytest.mark.parametrize("message", [
    "Дополнительные товары не нужны", "Не предлагайте мне ничего", "Мне не нужны дополнительные услуги",
    "Без дополнительных покупок, пожалуйста", "Ничего больше не нужно", "Не хочу дополнительных товаров",
])
def test_unambiguous_general_refusal_needs_no_previous_offer(message):
    assert upsell_block_reason(message, []) == REFUSAL_REASON


@pytest.mark.parametrize("reply", [
    "Нет, спасибо", "Нет", "Не надо", "Спасибо, у меня уже есть", "Кофе и средства уже есть",
    "Уже купил нужные средства", "Мне не нужны зерна", "У меня есть запас",
])
def test_short_refusal_or_ownership_statement_after_offer(reply):
    assert upsell_block_reason(reply, [manager("Добавить кофе и средство ухода к заказу?")]) == REFUSAL_REASON


def test_refusal_remains_after_later_manager_turns_and_topic_change():
    history = [
        manager("Могу предложить дополнительный чехол."),
        client("Нет, спасибо."),
        manager("Хорошо. Какой город доставки?"),
        client("Казань."),
    ]
    assert upsell_block_reason("Когда будет доставка?", history) == REFUSAL_REASON


@pytest.mark.parametrize("message", [
    "Зерен пока нет", "Не знаю, какой выбрать", "Кофе пока нет, это первая кофемашина",
    "Нет", "У меня уже есть кофемашина, ищу средство ухода",
])
def test_absence_uncertainty_and_ownership_without_offer_are_not_refusal(message):
    assert upsell_block_reason(message, []) is None


def test_negative_answer_about_ownership_is_not_refusal():
    assert upsell_block_reason("Нет", [manager("У вас уже есть зерна?")]) is None


def test_latest_ownership_question_replaces_old_offer_context():
    history = [manager("Предлагаю зерна к кофемашине."), manager("У вас уже есть зерна?")]
    assert upsell_block_reason("Нет, пока нет", history) is None


def test_ownership_question_at_end_of_same_turn_is_not_offer():
    history = [manager("Добавить кофе? Или у вас уже есть зерна?")]
    assert upsell_block_reason("Нет", history) is None


def test_regular_reply_to_offer_consumes_context_before_another_negative():
    history = [manager("Добавить кофе к заказу?"), client("Да, добавьте одну пачку")]
    assert upsell_block_reason("Нет ответа про доставку", history) is None


def test_manager_words_are_not_treated_as_customer_refusal():
    assert upsell_block_reason("Зерен пока нет", [manager("Дополнительные товары не нужны? Не предлагать?")]) is None


@pytest.mark.parametrize("message", [
    "Кофемашина протекает, хочу вернуть ее", "У меня сломался чайник", "Пришел поврежденный товар",
])
def test_current_complaint_overrides_sales_conversation(message):
    assert upsell_block_reason(message, [manager("Добавим кофе?"), client("Да")]) == SUPPORT_REASON


def test_conservative_policy_keeps_refusal_even_after_reconsideration():
    # MVP limitation is intentional: block all recommendations for this context.
    history = [manager("Предложить кофе?"), client("Нет, спасибо")]
    assert upsell_block_reason("Передумал, хочу посмотреть дополнительные товары", history) == REFUSAL_REASON
