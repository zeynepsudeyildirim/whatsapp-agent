import json
import time

import pytest
from httpx import ASGITransport, AsyncClient

from waagent.config import Settings
from waagent.db import session as db
from waagent.db.models import Base, Contact, Role, Tenant
from waagent.main import create_app
from waagent.queue import InMemoryQueue
from waagent.whatsapp.signature import compute_signature

APP_SECRET = "test-app-secret"
WORKER_TOKEN = "test-worker-token"
PHONE_NUMBER_ID = "111111111111111"
ADMIN = "4917000000001"
SUPPLIER = "4917000000002"
CUSTOMER = "4917000000003"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_secret=APP_SECRET,
        verify_token="verify-me",
        access_token="unused",
        database_url="sqlite+aiosqlite:///:memory:",
        worker_auth_token=WORKER_TOKEN,
    )


@pytest.fixture
async def app_ctx(settings):
    engine = db.init_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with db._sessionmaker() as s:
        tenant = Tenant(name="Pilot Restaurant", phone_number_id=PHONE_NUMBER_ID, waba_id="222")
        s.add(tenant)
        await s.flush()
        s.add_all(
            [
                Contact(tenant_id=tenant.id, wa_id=ADMIN, role=Role.ADMIN, language="tr"),
                Contact(tenant_id=tenant.id, wa_id=SUPPLIER, role=Role.SUPPLIER, language="de"),
            ]
        )
        await s.commit()

    queue = InMemoryQueue()
    app = create_app(settings, queue)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, queue
    await engine.dispose()
    db._engine = None
    db._sessionmaker = None


def make_event(sender: str, wamid: str, text: str = "Merhaba") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "222",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "49891234567",
                                "phone_number_id": PHONE_NUMBER_ID,
                            },
                            "messages": [
                                {
                                    "id": wamid,
                                    "from": sender,
                                    "timestamp": str(int(time.time())),
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def signed(payload: dict) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    return body, {
        "X-Hub-Signature-256": compute_signature(body, APP_SECRET),
        "Content-Type": "application/json",
    }
