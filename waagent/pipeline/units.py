"""Unit words -> Unit, decided by code, not by the model.

Small models confuse e.g. 'koli' (box) and 'kasa' (crate). The model reports the word it heard;
this table decides what it means. Unknown words keep the model's guess and the owner still
sees the Turkish summary on the approval card.
"""

from waagent.pipeline.schemas import OrderItem, Unit

_WORDS: dict[Unit, tuple[str, ...]] = {
    Unit.KG: ("kg", "kilo", "kilogram", "kilogramm", "kilos", "kilograms"),
    Unit.G: ("g", "gr", "gram", "gramm", "grams"),
    Unit.L: ("l", "lt", "litre", "litro", "liter", "litres", "liters"),
    Unit.ML: ("ml", "mililitre", "milliliter"),
    Unit.PIECE: ("adet", "tane", "stuck", "stueck", "stk", "piece", "pieces", "pcs"),
    Unit.CRATE: ("kasa", "kiste", "kisten", "crate", "crates"),
    Unit.BOX: ("koli", "karton", "kartons", "box", "boxes", "carton", "cartons", "schachtel"),
    Unit.PACK: ("paket", "packung", "packungen", "pack", "packs", "package", "packet"),
    Unit.BOTTLE: ("sise", "flasche", "flaschen", "bottle", "bottles"),
    Unit.CAN: ("teneke", "dose", "dosen", "can", "cans", "tin", "tins"),
    Unit.BAG: ("cuval", "torba", "sack", "sacke", "bag", "bags", "sack"),
}

_LOOKUP = {word: unit for unit, words in _WORDS.items() for word in words}

_FOLD = str.maketrans("çğıöşüäßÇĞİÖŞÜÄ", "cgiosuasCGIOSUA")


def _fold(word: str) -> str:
    return word.translate(_FOLD).lower().strip(" .")


def unit_for_word(word: str | None) -> Unit | None:
    if not word:
        return None
    w = _fold(word)
    if w in _LOOKUP:
        return _LOOKUP[w]
    # Turkish suffixes: "kasalık", "kiloluk", "koliyi"... -> longest known stem wins
    stems = [k for k in _LOOKUP if len(k) >= 3 and w.startswith(k)]
    return _LOOKUP[max(stems, key=len)] if stems else None


def normalise_units(items: list[OrderItem]) -> list[OrderItem]:
    out = []
    for item in items:
        unit = unit_for_word(item.unit_word)
        out.append(item.model_copy(update={"unit": unit}) if unit and unit != item.unit else item)
    return out
