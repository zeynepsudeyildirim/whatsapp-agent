"""Typed views over the WhatsApp Cloud API webhook payload.

Only the fields we use are modelled; everything else is kept (extra="allow") so the raw
event can be stored and re-processed later without losing data.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class Text(_Loose):
    body: str


class Media(_Loose):
    id: str
    mime_type: str | None = None


class ButtonReply(_Loose):
    id: str
    title: str


class Interactive(_Loose):
    type: str
    button_reply: ButtonReply | None = None


class Context(_Loose):
    """Present when the user replied to (quoted) one of our messages."""

    id: str | None = None


class InboundMessage(_Loose):
    id: str  # wamid — globally unique, our idempotency key
    from_: str = Field(alias="from")
    timestamp: str
    type: str
    text: Text | None = None
    audio: Media | None = None
    image: Media | None = None
    interactive: Interactive | None = None
    context: Context | None = None


class Status(_Loose):
    id: str
    status: Literal["sent", "delivered", "read", "failed"] | str
    recipient_id: str | None = None


class Metadata(_Loose):
    display_phone_number: str
    phone_number_id: str


class Value(_Loose):
    messaging_product: str
    metadata: Metadata
    messages: list[InboundMessage] = []
    statuses: list[Status] = []


class Change(_Loose):
    field: str
    value: Value


class Entry(_Loose):
    id: str  # WABA id
    changes: list[Change]


class WebhookEvent(_Loose):
    object: str
    entry: list[Entry]

    def iter_messages(self):
        """Yield (phone_number_id, message) for every inbound message in the event."""
        for entry in self.entry:
            for change in entry.changes:
                if change.field != "messages":
                    continue
                for msg in change.value.messages:
                    yield change.value.metadata.phone_number_id, msg

    def iter_statuses(self):
        for entry in self.entry:
            for change in entry.changes:
                if change.field != "messages":
                    continue
                for st in change.value.statuses:
                    yield change.value.metadata.phone_number_id, st
