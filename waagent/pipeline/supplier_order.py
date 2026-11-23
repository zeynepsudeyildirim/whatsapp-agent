"""Supplier channel, admin -> supplier: voice/text -> structured order -> message -> verification.

Produces a draft for the approval card. Nothing here sends anything.
"""

import json
from dataclasses import dataclass, field
from datetime import date

from waagent.llm.base import LLM, Audio
from waagent.pipeline.schemas import (
    BackExtraction,
    ComposedMessage,
    Intent,
    UnderstoodMessage,
    Unit,
)
from waagent.pipeline.verify import VerificationResult, resolve_supplier, verify

LANGUAGE_NAMES = {
    "tr": "Turkish",
    "de": "German",
    "en": "English",
    "ar": "Arabic",
    "ru": "Russian",
}

_UNDERSTAND_SYSTEM = """\
You read instructions a restaurant owner gives to an ordering assistant, as a voice note or text.
Return the verbatim transcript and the structured content.
Rules:
- Never invent products, quantities, units or dates. If something is unclear or inaudible,
  leave it out of the structured fields and describe it in `unclear`.
- Keep product names in the speaker's own words and language.
- Map units: kilo/kg->kg, gram->g, litre->l, adet/tane/Stück->piece, kasa/Kiste->crate,
  koli/Karton->box, paket->pack, şişe->bottle, kutu (can)->can, çuval/torba->bag; else other.
- Resolve relative dates (yarın, öbür gün, Cuma, morgen, tomorrow...) against today's date.
"""

_COMPOSE_SYSTEM = """\
You write short, polite, business-like WhatsApp messages from a restaurant to its supplier.
Rules:
- Write in {language}. Use only the facts given in the JSON. Add nothing else.
- Write every quantity with digits exactly as given (e.g. 2.5 may be written 2,5 in German).
- One line per item: quantity, unit, product. Translate product names naturally; if a glossary
  term is given, use the glossary translation exactly.
- State the delivery date as a calendar date ({date_hint}).
- No emojis, no prices, no assumptions about availability.
"""

_BACK_SYSTEM = """\
You read a message a restaurant sent to its supplier and extract the ordered items and the
delivery date exactly as written. Do not correct or complete anything.
"""

_UNIT_TR = {
    Unit.KG: "kg",
    Unit.G: "g",
    Unit.L: "litre",
    Unit.ML: "ml",
    Unit.PIECE: "adet",
    Unit.CRATE: "kasa",
    Unit.BOX: "koli",
    Unit.PACK: "paket",
    Unit.BOTTLE: "şişe",
    Unit.CAN: "kutu",
    Unit.BAG: "çuval",
    Unit.OTHER: "",
}


@dataclass
class SupplierDraft:
    understood: UnderstoodMessage
    supplier_id: str | None
    outbound_text: str | None
    summary_for_admin: str
    verification: VerificationResult | None
    needs_clarification: list[str] = field(default_factory=list)

    @property
    def ready_for_approval(self) -> bool:
        return (
            self.outbound_text is not None
            and self.verification is not None
            and self.verification.ok
            and not self.needs_clarification
        )


def _fmt_qty(q: float) -> str:
    return f"{q:g}".replace(".", ",")  # Turkish decimal comma


def admin_summary(u: UnderstoodMessage, supplier_label: str | None) -> str:
    """Built by code from structured data — the owner checks facts, not a translation."""
    lines = [f"Tedarikçi: {supplier_label or '?'}"]
    for item in u.items:
        unit = _UNIT_TR[item.unit]
        note = f" ({item.note})" if item.note else ""
        lines.append(f"• {_fmt_qty(item.quantity)} {unit} {item.product}{note}".replace("  ", " "))
    if u.delivery_date:
        lines.append(f"Teslim: {u.delivery_date.strftime('%d.%m.%Y')}")
    if u.free_text:
        lines.append(f"Not: {u.free_text}")
    return "\n".join(lines)


async def draft_supplier_message(
    llm: LLM,
    *,
    today: date,
    suppliers: dict[str, tuple[str, str]],  # id -> (display name, language code)
    text: str | None = None,
    audio: Audio | None = None,
    glossary: dict[str, str] | None = None,  # source term -> term in supplier's language
    max_attempts: int = 2,
) -> SupplierDraft:
    if (text is None) == (audio is None):
        raise ValueError("Provide exactly one of text or audio")

    prompt = f"Today is {today.isoformat()} ({today.strftime('%A')})."
    if text is not None:
        prompt += f"\nOwner's message:\n{text}"
    understood = await llm.structured(
        system=_UNDERSTAND_SYSTEM, prompt=prompt, schema=UnderstoodMessage, audio=audio
    )

    clarify = list(understood.unclear)
    supplier_id = resolve_supplier(
        understood.supplier_name, {sid: name for sid, (name, _) in suppliers.items()}
    )
    if supplier_id is None:
        clarify.append("Hangi tedarikçiye gönderilecek?")
    if understood.intent == Intent.ORDER and not understood.items:
        clarify.append("Sipariş kalemleri anlaşılamadı.")

    label = suppliers[supplier_id][0] if supplier_id else understood.supplier_name
    summary = admin_summary(understood, label)

    if clarify:
        return SupplierDraft(understood, supplier_id, None, summary, None, clarify)

    _, lang = suppliers[supplier_id]
    language = LANGUAGE_NAMES.get(lang, lang)
    facts = understood.model_dump(
        mode="json", include={"intent", "items", "delivery_date", "free_text"}
    )
    compose_prompt = f"JSON:\n{json.dumps(facts, ensure_ascii=False)}"
    if glossary:
        compose_prompt += f"\nGlossary (use exactly):\n{json.dumps(glossary, ensure_ascii=False)}"

    verification: VerificationResult | None = None
    outbound: str | None = None
    for _ in range(max_attempts):
        composed = await llm.structured(
            system=_COMPOSE_SYSTEM.format(language=language, date_hint="e.g. 24.11.2026"),
            prompt=compose_prompt,
            schema=ComposedMessage,
            temperature=0.2,
        )
        back = await llm.structured(
            system=_BACK_SYSTEM,
            prompt=f"Today is {today.isoformat()}.\nMessage:\n{composed.text}",
            schema=BackExtraction,
        )
        verification = verify(understood, composed.text, back)
        outbound = composed.text
        if verification.ok:
            break

    return SupplierDraft(understood, supplier_id, outbound, summary, verification, [])
