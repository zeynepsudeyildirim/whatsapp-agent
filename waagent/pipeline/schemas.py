"""Structured representations the LLM must produce. Numbers live here, not in free text."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class Unit(StrEnum):
    KG = "kg"
    G = "g"
    L = "l"
    ML = "ml"
    PIECE = "piece"  # adet / Stück
    CRATE = "crate"  # kasa / Kiste
    BOX = "box"  # koli / Karton
    PACK = "pack"  # paket / Packung
    BOTTLE = "bottle"
    CAN = "can"
    BAG = "bag"  # çuval, poşet / Sack
    OTHER = "other"


class Intent(StrEnum):
    ORDER = "order"  # new order
    CHANGE = "change"  # change or cancel an earlier order
    QUESTION = "question"  # ask the supplier something (price, availability...)
    OTHER = "other"


class OrderItem(BaseModel):
    product: str = Field(description="Product name exactly as the speaker said it, in their language")
    quantity: float = Field(gt=0)  # float keeps the JSON schema simple for every provider
    unit: Unit
    unit_word: str | None = Field(
        default=None,
        description="The unit word exactly as spoken/written (e.g. 'koli', 'kasa', 'kilo'); null if none",
    )
    note: str | None = Field(default=None, description="e.g. 'yağsız', 'organic'; null if none")


class UnderstoodMessage(BaseModel):
    """Result of reading the admin's voice note or text."""

    transcript: str = Field(description="Verbatim transcript of the audio, or the text as given")
    language: str = Field(description="ISO 639-1 code of the spoken language, e.g. 'tr'")
    intent: Intent
    supplier_name: str | None = Field(description="Supplier the admin named; null if not named")
    items: list[OrderItem] = Field(default_factory=list)
    delivery_date: date | None = Field(
        default=None, description="Absolute date resolved from 'yarın', 'Cuma' etc.; null if none"
    )
    free_text: str | None = Field(
        default=None, description="Anything else the admin wants to tell the supplier"
    )
    unclear: list[str] = Field(
        default_factory=list,
        description="Things that could not be understood with confidence. Empty if all is clear.",
    )


class ComposedMessage(BaseModel):
    text: str = Field(description="The message to send to the supplier, in the target language")


class BackExtraction(BaseModel):
    """What an independent reader finds in the composed message — used for verification."""

    items: list[OrderItem]
    delivery_date: date | None
