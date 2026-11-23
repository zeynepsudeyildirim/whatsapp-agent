from datetime import date

import pytest

from waagent.llm.base import Audio
from waagent.pipeline.schemas import (
    BackExtraction,
    ComposedMessage,
    Intent,
    OrderItem,
    UnderstoodMessage,
    Unit,
)
from waagent.pipeline.supplier_order import admin_summary, draft_supplier_message
from waagent.pipeline.verify import resolve_supplier, verify

TODAY = date(2026, 11, 23)
SUPPLIERS = {"s-de": ("Metro Großhandel", "de"), "s-en": ("Fresh Farms Ltd", "en")}

UNDERSTOOD = UnderstoodMessage(
    transcript="Metro'ya yarın için 20 kilo dana kıyma, 10 kasa domates, 2,5 kilo maydanoz",
    language="tr",
    intent=Intent.ORDER,
    supplier_name="Metro",
    items=[
        OrderItem(product="dana kıyma", quantity=20, unit=Unit.KG),
        OrderItem(product="domates", quantity=10, unit=Unit.CRATE),
        OrderItem(product="maydanoz", quantity=2.5, unit=Unit.KG),
    ],
    delivery_date=date(2026, 11, 24),
)

GOOD_TEXT = (
    "Guten Tag, wir bestellen für den 24.11.2026:\n"
    "- 20 kg Rinderhackfleisch\n- 10 Kisten Tomaten\n- 2,5 kg Petersilie\nVielen Dank!"
)
GOOD_BACK = BackExtraction(items=UNDERSTOOD.items, delivery_date=date(2026, 11, 24))


class FakeLLM:
    """Returns queued responses per schema, records calls."""

    def __init__(self, responses: dict[type, list]):
        self.responses = {k: list(v) for k, v in responses.items()}
        self.calls: list[type] = []

    async def structured(self, *, system, prompt, schema, audio=None, temperature=0.0):
        self.calls.append(schema)
        return self.responses[schema].pop(0)


# --- verify -------------------------------------------------------------------------------


def test_verify_accepts_correct_message():
    assert verify(UNDERSTOOD, GOOD_TEXT, GOOD_BACK).ok


def test_verify_does_not_read_date_as_quantity():
    # 24 is not an ordered quantity; the date must not satisfy or confuse the check
    u = UNDERSTOOD.model_copy(
        update={"items": [OrderItem(product="x", quantity=24, unit=Unit.PIECE)]}
    )
    back = BackExtraction(items=u.items, delivery_date=u.delivery_date)
    result = verify(u, "Lieferung am 24.11.2026: Stück x", back)
    assert not result.ok


def test_verify_catches_wrong_quantity():
    bad = GOOD_TEXT.replace("20 kg", "50 kg")
    back = BackExtraction(
        items=[
            OrderItem(product="Rinderhackfleisch", quantity=50, unit=Unit.KG),
            *UNDERSTOOD.items[1:],
        ],
        delivery_date=date(2026, 11, 24),
    )
    result = verify(UNDERSTOOD, bad, back)
    assert not result.ok
    assert any("20" in p for p in result.problems)


def test_verify_catches_wrong_unit_and_date():
    back = BackExtraction(
        items=[
            UNDERSTOOD.items[0],
            OrderItem(product="Tomaten", quantity=10, unit=Unit.KG),  # crate -> kg
            UNDERSTOOD.items[2],
        ],
        delivery_date=date(2026, 11, 25),
    )
    result = verify(UNDERSTOOD, GOOD_TEXT, back)
    assert not result.ok
    assert len(result.problems) == 2


def test_resolve_supplier():
    names = {sid: name for sid, (name, _) in SUPPLIERS.items()}
    assert resolve_supplier("Metro", names) == "s-de"
    assert resolve_supplier("fresh farms", names) == "s-en"
    assert resolve_supplier("Selgros", names) is None
    assert resolve_supplier(None, names) is None


def test_admin_summary_is_turkish_and_exact():
    s = admin_summary(UNDERSTOOD, "Metro Großhandel")
    assert "• 20 kg dana kıyma" in s
    assert "• 10 kasa domates" in s
    assert "• 2,5 kg maydanoz" in s
    assert "Teslim: 24.11.2026" in s


# --- full draft ---------------------------------------------------------------------------


async def test_draft_happy_path():
    llm = FakeLLM(
        {
            UnderstoodMessage: [UNDERSTOOD],
            ComposedMessage: [ComposedMessage(text=GOOD_TEXT)],
            BackExtraction: [GOOD_BACK],
        }
    )
    draft = await draft_supplier_message(
        llm, today=TODAY, suppliers=SUPPLIERS, audio=Audio(b"ogg", "audio/ogg; codecs=opus")
    )
    assert draft.ready_for_approval
    assert draft.supplier_id == "s-de"
    assert draft.outbound_text == GOOD_TEXT


async def test_draft_retries_once_then_flags():
    bad = ComposedMessage(text=GOOD_TEXT.replace("20 kg", "50 kg"))
    bad_back = BackExtraction(
        items=[OrderItem(product="R", quantity=50, unit=Unit.KG), *UNDERSTOOD.items[1:]],
        delivery_date=date(2026, 11, 24),
    )
    llm = FakeLLM(
        {
            UnderstoodMessage: [UNDERSTOOD],
            ComposedMessage: [bad, bad],
            BackExtraction: [bad_back, bad_back],
        }
    )
    draft = await draft_supplier_message(llm, today=TODAY, suppliers=SUPPLIERS, text="...")
    assert not draft.ready_for_approval
    assert llm.calls.count(ComposedMessage) == 2


async def test_draft_recovers_on_second_attempt():
    bad = ComposedMessage(text=GOOD_TEXT.replace("20 kg", "50 kg"))
    bad_back = BackExtraction(
        items=[OrderItem(product="R", quantity=50, unit=Unit.KG), *UNDERSTOOD.items[1:]],
        delivery_date=date(2026, 11, 24),
    )
    llm = FakeLLM(
        {
            UnderstoodMessage: [UNDERSTOOD],
            ComposedMessage: [bad, ComposedMessage(text=GOOD_TEXT)],
            BackExtraction: [bad_back, GOOD_BACK],
        }
    )
    draft = await draft_supplier_message(llm, today=TODAY, suppliers=SUPPLIERS, text="...")
    assert draft.ready_for_approval


async def test_unknown_supplier_asks_instead_of_guessing():
    u = UNDERSTOOD.model_copy(update={"supplier_name": "Selgros"})
    llm = FakeLLM({UnderstoodMessage: [u]})
    draft = await draft_supplier_message(llm, today=TODAY, suppliers=SUPPLIERS, text="...")
    assert not draft.ready_for_approval
    assert draft.outbound_text is None
    assert "Hangi tedarikçiye gönderilecek?" in draft.needs_clarification
    assert llm.calls == [UnderstoodMessage]  # nothing composed


async def test_unclear_audio_is_not_composed():
    u = UNDERSTOOD.model_copy(update={"unclear": ["Domates miktarı anlaşılmadı"]})
    llm = FakeLLM({UnderstoodMessage: [u]})
    draft = await draft_supplier_message(llm, today=TODAY, suppliers=SUPPLIERS, text="...")
    assert draft.needs_clarification == ["Domates miktarı anlaşılmadı"]
    assert draft.outbound_text is None


async def test_requires_exactly_one_input():
    with pytest.raises(ValueError):
        await draft_supplier_message(FakeLLM({}), today=TODAY, suppliers=SUPPLIERS)
