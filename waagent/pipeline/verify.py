"""Deterministic checks that the outgoing message says the same thing as the approved order.

The LLM writes the text; code decides whether it may be sent. Two independent checks:
1. Every quantity appears literally in the text (as 2.5 or 2,5 — German uses a decimal comma).
2. An independent re-reading of the text (back-extraction) yields the same items, units and date.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from waagent.pipeline.schemas import BackExtraction, OrderItem, UnderstoodMessage

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_DATES = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b")


def _numbers_in(text: str) -> list[float]:
    text = _DATES.sub(" ", text)  # "24.11.2026" must not be read as the quantity 24.11
    return [float(m.replace(",", ".")) for m in _NUMBER.findall(text)]


def _key(item: OrderItem) -> tuple[float, str]:
    return (round(item.quantity, 3), item.unit.value)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


@dataclass
class VerificationResult:
    ok: bool
    problems: list[str] = field(default_factory=list)


def verify(source: UnderstoodMessage, text: str, back: BackExtraction) -> VerificationResult:
    problems: list[str] = []

    # 1. Literal presence of every quantity (multiset: two items of "10" need two 10s).
    available = _numbers_in(text)
    for item in source.items:
        q = round(item.quantity, 3)
        match = next((n for n in available if round(n, 3) == q), None)
        if match is None:
            problems.append(f"Miktar metinde yok: {item.quantity:g} ({item.product})")
        else:
            available.remove(match)

    # 2. Back-extraction must yield the same (quantity, unit) multiset.
    src = sorted(_key(i) for i in source.items)
    got = sorted(_key(i) for i in back.items)
    if src != got:
        problems.append(f"Ürün/miktar/birim uyuşmuyor: beklenen {src}, metinde okunan {got}")

    # 3. Same delivery date.
    if source.delivery_date != back.delivery_date:
        problems.append(
            f"Teslim tarihi uyuşmuyor: beklenen {source.delivery_date}, metinde {back.delivery_date}"
        )

    return VerificationResult(ok=not problems, problems=problems)


def resolve_supplier(name: str | None, suppliers: dict[str, str]) -> str | None:
    """Match a spoken supplier name to a known supplier id. suppliers = {id: display name}.

    Exact (normalised) match or unique substring match; anything ambiguous returns None so the
    agent asks instead of guessing.
    """
    if not name:
        return None
    wanted = _norm(name)
    if not wanted:
        return None
    exact = [sid for sid, disp in suppliers.items() if _norm(disp) == wanted]
    if len(exact) == 1:
        return exact[0]
    partial = [
        sid for sid, disp in suppliers.items() if wanted in _norm(disp) or _norm(disp) in wanted
    ]
    return partial[0] if len(partial) == 1 else None
