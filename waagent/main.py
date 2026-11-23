"""HTTP entrypoints.

- GET  /webhook                Meta's verification handshake
- POST /webhook                inbound messages + status updates (fast path, returns 200 quickly)
- POST /tasks/process-message  worker endpoint, called by Cloud Tasks (slow path)
- GET  /healthz                liveness
"""

import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from waagent.config import Settings, get_settings
from waagent.db import session as db
from waagent.db.models import Contact, Message
from waagent.ingest import ingest_event
from waagent.queue import CloudTasksQueue, InMemoryQueue, WorkQueue
from waagent.routing import channel_for
from waagent.whatsapp.payloads import WebhookEvent
from waagent.whatsapp.signature import is_valid_signature

log = logging.getLogger(__name__)


def build_queue(settings: Settings) -> WorkQueue:
    if settings.queue_backend == "cloud_tasks":
        return CloudTasksQueue(
            settings.cloud_tasks_queue,
            settings.worker_url,
            settings.worker_auth_token.get_secret_value(),
        )
    return InMemoryQueue()


def create_app(settings: Settings | None = None, queue: WorkQueue | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if db._engine is None:
            db.init_engine(settings.database_url)
        yield

    app = FastAPI(title="wa-agent", lifespan=lifespan)
    app.state.settings = settings
    app.state.queue = queue or build_queue(settings)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True}

    @app.get("/webhook")
    async def verify(
        mode: str = Query(alias="hub.mode"),
        token: str = Query(alias="hub.verify_token"),
        challenge: str = Query(alias="hub.challenge"),
    ) -> Response:
        expected = settings.verify_token.get_secret_value()
        if mode == "subscribe" and hmac.compare_digest(token, expected):
            return Response(content=challenge, media_type="text/plain")
        raise HTTPException(status_code=403)

    @app.post("/webhook")
    async def receive(
        request: Request,
        session: AsyncSession = Depends(db.get_session),
        x_hub_signature_256: str | None = Header(default=None),
    ) -> dict:
        body = await request.body()
        if not is_valid_signature(body, x_hub_signature_256, settings.app_secret.get_secret_value()):
            raise HTTPException(status_code=401, detail="invalid signature")
        try:
            event = WebhookEvent.model_validate_json(body)
        except ValidationError:
            # Signed by Meta but a shape we don't model (another webhook field): acknowledge.
            log.info("Unhandled webhook shape acknowledged")
            return {"ok": True}
        # DB errors propagate as 500 on purpose: Meta then retries the delivery.
        new_ids = await ingest_event(session, event, request.app.state.queue)
        return {"ok": True, "stored": len(new_ids)}

    class Task(BaseModel):
        message_id: str

    @app.post("/tasks/process-message")
    async def process_message(
        task: Task,
        session: AsyncSession = Depends(db.get_session),
        x_worker_token: str | None = Header(default=None),
    ) -> dict:
        expected = settings.worker_auth_token.get_secret_value()
        if not expected or not x_worker_token or not hmac.compare_digest(x_worker_token, expected):
            raise HTTPException(status_code=401)

        msg = await session.get(Message, task.message_id)
        if msg is None:
            return {"ok": True, "skipped": "unknown message"}
        contact = await session.scalar(select(Contact).where(Contact.id == msg.contact_id))
        channel = channel_for(contact.role)
        # Faz 1/2: hand over to the LangGraph agent for this channel.
        log.info("message %s routed to %s channel", msg.id, channel)
        return {"ok": True, "channel": channel.value}

    return app
