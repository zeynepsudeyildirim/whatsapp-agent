"""Core data model (Faz 0). Every business table carries tenant_id from day one.

Supplier orders, reservations, menu and glossary tables arrive in Faz 1/2.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class Role(enum.StrEnum):
    ADMIN = "admin"  # owner or authorised staff
    SUPPLIER = "supplier"
    CUSTOMER = "customer"


class Channel(enum.StrEnum):
    SUPPLIER = "supplier"  # admin <-> supplier relay
    CUSTOMER = "customer"  # business <-> customer service
    ADMIN = "admin"  # admin talking to the agent itself


class ConversationMode(enum.StrEnum):
    AGENT = "agent"
    HUMAN = "human"  # handed over: agent stays silent, relays only


class Direction(enum.StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class PendingStatus(enum.StrEnum):
    WAITING = "waiting"
    APPROVED = "approved"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    SENT = "sent"


class Tenant(Base):
    __tablename__ = "tenant"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    phone_number_id: Mapped[str] = mapped_column(String(64), unique=True)  # Meta phone number id
    waba_id: Mapped[str] = mapped_column(String(64))
    admin_language: Mapped[str] = mapped_column(String(8), default="tr")
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Berlin")
    settings: Mapped[dict] = mapped_column(JSON, default=dict)  # capacity rules, budget alert, ...
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Contact(Base):
    __tablename__ = "contact"
    __table_args__ = (UniqueConstraint("tenant_id", "wa_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    wa_id: Mapped[str] = mapped_column(String(32))  # E.164 without '+', as WhatsApp sends it
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False), default=Role.CUSTOMER)
    display_name: Mapped[str | None] = mapped_column(String(200))
    language: Mapped[str | None] = mapped_column(String(8))
    # Opens/extends the 24h customer service window; only inbound messages update it.
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Conversation(Base):
    __tablename__ = "conversation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contact.id"), index=True)
    channel: Mapped[Channel] = mapped_column(Enum(Channel, native_enum=False))
    mode: Mapped[ConversationMode] = mapped_column(
        Enum(ConversationMode, native_enum=False), default=ConversationMode.AGENT
    )
    graph_thread_id: Mapped[str] = mapped_column(String(64), default=_uuid)  # LangGraph thread
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "message"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversation.id"), index=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contact.id"), index=True)
    # WhatsApp message id (wamid). UNIQUE = idempotency: Meta may deliver the same event twice.
    wa_message_id: Mapped[str] = mapped_column(String(128), unique=True)
    direction: Mapped[Direction] = mapped_column(Enum(Direction, native_enum=False))
    type: Mapped[str] = mapped_column(String(32))
    original_text: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text)
    translation: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(8))
    delivery_status: Mapped[str | None] = mapped_column(String(16))
    pricing_category: Mapped[str | None] = mapped_column(String(32))  # from status webhooks
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PendingAction(Base):
    """An outbound message drafted for a supplier, waiting for the admin's approval.

    Nothing reaches a supplier without a row here in status APPROVED.
    """

    __tablename__ = "pending_action"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey("contact.id"))  # admin
    target_contact_id: Mapped[str] = mapped_column(ForeignKey("contact.id"))  # supplier
    structured: Mapped[dict] = mapped_column(JSON)  # items, quantities, units, dates
    outbound_text: Mapped[str] = mapped_column(Text)  # exactly what will be sent
    summary_for_admin: Mapped[str] = mapped_column(Text)  # in the admin's language
    status: Mapped[PendingStatus] = mapped_column(
        Enum(PendingStatus, native_enum=False), default=PendingStatus.WAITING
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), index=True)
    actor: Mapped[str] = mapped_column(String(64))  # contact id or "agent" / "system"
    event: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
