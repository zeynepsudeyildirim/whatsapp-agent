from datetime import UTC, datetime, timedelta

from conftest import ADMIN, CUSTOMER, SUPPLIER, WORKER_TOKEN, make_event, signed

from waagent.whatsapp.client import is_service_window_open
from waagent.whatsapp.signature import compute_signature, is_valid_signature


def test_signature_roundtrip():
    sig = compute_signature(b"{}", "s")
    assert is_valid_signature(b"{}", sig, "s")
    assert not is_valid_signature(b"{} ", sig, "s")  # one byte changed
    assert not is_valid_signature(b"{}", None, "s")
    assert not is_valid_signature(b"{}", "sha1=abc", "s")


def test_service_window():
    now = datetime.now(UTC)
    assert is_service_window_open(now - timedelta(hours=23), now)
    assert not is_service_window_open(now - timedelta(hours=25), now)
    assert not is_service_window_open(None, now)


async def test_verify_handshake(app_ctx):
    client, _ = app_ctx
    ok = await client.get(
        "/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"}
    )
    assert ok.status_code == 200 and ok.text == "42"
    bad = await client.get(
        "/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"}
    )
    assert bad.status_code == 403


async def test_unsigned_request_rejected(app_ctx):
    client, queue = app_ctx
    body, headers = signed(make_event(CUSTOMER, "wamid.1"))
    headers["X-Hub-Signature-256"] = "sha256=" + "0" * 64
    resp = await client.post("/webhook", content=body, headers=headers)
    assert resp.status_code == 401
    assert queue.items == []


async def test_duplicate_delivery_is_stored_once(app_ctx):
    client, queue = app_ctx
    body, headers = signed(make_event(CUSTOMER, "wamid.dup"))
    first = await client.post("/webhook", content=body, headers=headers)
    second = await client.post("/webhook", content=body, headers=headers)
    assert first.json()["stored"] == 1
    assert second.json()["stored"] == 0
    assert len(queue.items) == 1


async def test_routing_by_role(app_ctx):
    client, queue = app_ctx
    expected = {}
    for sender, wamid, channel in [
        (ADMIN, "wamid.a", "admin"),
        (SUPPLIER, "wamid.s", "supplier"),
        (CUSTOMER, "wamid.c", "customer"),  # unknown number -> customer
    ]:
        body, headers = signed(make_event(sender, wamid))
        await client.post("/webhook", content=body, headers=headers)
        expected[queue.items[-1]] = channel

    for message_id, channel in expected.items():
        resp = await client.post(
            "/tasks/process-message",
            json={"message_id": message_id},
            headers={"X-Worker-Token": WORKER_TOKEN},
        )
        assert resp.json()["channel"] == channel


async def test_worker_requires_token(app_ctx):
    client, _ = app_ctx
    resp = await client.post("/tasks/process-message", json={"message_id": "x"})
    assert resp.status_code == 401
