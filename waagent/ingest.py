"""Webhook fast path: store inbound messages idempotently and enqueue them for the worker."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from waagent.db.models import Contact, Direction, Message, Role, Tenant
from waagent.queue import WorkQueue
from waagent.whatsapp.payloads import InboundMessage, WebhookEvent

log = logging.getLogger(__name__)


def _message_text(msg: InboundMessage) -> str | None:
    if msg.text:
        return msg.text.body
    if msg.interactive and msg.interactive.button_reply:
        return msg.interactive.button_reply.id  # button ids carry the action, e.g. "approve:<id>"
    return None


async def _get_or_create_contact(session: AsyncSession, tenant: Tenant, wa_id: str) -> Contact:
    contact = await session.scalar(
        select(Contact).where(Contact.tenant_id == tenant.id, Contact.wa_id == wa_id)
    )
    if contact is None:
        # Unknown numbers are always treated as customers (security boundary).
        contact = Contact(tenant_id=tenant.id, wa_id=wa_id, role=Role.CUSTOMER)
        session.add(contact)
        await session.flush()
    return contact


async def ingest_event(session: AsyncSession, event: WebhookEvent, queue: WorkQueue) -> list[str]:
    """Returns the ids of newly stored (and enqueued) messages. Duplicates are skipped."""
    new_ids: list[str] = []

    for phone_number_id, msg in event.iter_messages():
        tenant = await session.scalar(select(Tenant).where(Tenant.phone_number_id == phone_number_id))
        if tenant is None:
            log.warning("Message for unknown phone_number_id=%s ignored", phone_number_id)
            continue

        contact = await _get_or_create_contact(session, tenant, msg.from_)
        sent_at = datetime.fromtimestamp(int(msg.timestamp), tz=UTC)

        row = Message(
            tenant_id=tenant.id,
            contact_id=contact.id,
            wa_message_id=msg.id,
            direction=Direction.INBOUND,
            type=msg.type,
            original_text=_message_text(msg),
            raw=msg.model_dump(by_alias=True),
        )
        try:
            async with session.begin_nested():
                session.add(row)
        except IntegrityError:
            log.info("Duplicate delivery of %s skipped", msg.id)
            continue

        last = contact.last_inbound_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if last is None or sent_at > last:
            contact.last_inbound_at = sent_at
        new_ids.append(row.id)

    for _, st in event.iter_statuses():
        pricing = (st.model_extra or {}).get("pricing") or {}
        await session.execute(
            update(Message)
            .where(Message.wa_message_id == st.id)
            .values(delivery_status=st.status, pricing_category=pricing.get("category"))
        )

    # Commit before enqueueing so the worker always finds the row.
    await session.commit()
    for message_id in new_ids:
        await queue.enqueue(message_id)
    return new_ids
