"""Thin async client for the WhatsApp Cloud API (Graph API).

All outbound traffic must go through waagent.outbound (window check, idempotency, cost
logging); this module only knows how to talk HTTP to Meta.
"""

from datetime import UTC, datetime, timedelta

import httpx

SERVICE_WINDOW = timedelta(hours=24)


def is_service_window_open(last_inbound_at: datetime | None, now: datetime | None = None) -> bool:
    """Free-form messages are only allowed within 24h of the contact's last inbound message."""
    if last_inbound_at is None:
        return False
    now = now or datetime.now(UTC)
    if last_inbound_at.tzinfo is None:
        last_inbound_at = last_inbound_at.replace(tzinfo=UTC)
    return now - last_inbound_at < SERVICE_WINDOW


class WhatsAppClient:
    def __init__(self, base_url: str, api_version: str, access_token: str, *, timeout: float = 15.0):
        self._http = httpx.AsyncClient(
            base_url=f"{base_url}/{api_version}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _send(self, phone_number_id: str, payload: dict) -> dict:
        body = {"messaging_product": "whatsapp", "recipient_type": "individual", **payload}
        resp = await self._http.post(f"/{phone_number_id}/messages", json=body)
        resp.raise_for_status()
        return resp.json()

    async def send_text(self, phone_number_id: str, to: str, text: str, *, reply_to: str | None = None) -> dict:
        payload: dict = {"to": to, "type": "text", "text": {"body": text, "preview_url": False}}
        if reply_to:
            payload["context"] = {"message_id": reply_to}
        return await self._send(phone_number_id, payload)

    async def send_buttons(
        self, phone_number_id: str, to: str, body: str, buttons: list[tuple[str, str]]
    ) -> dict:
        """Interactive reply buttons (max 3, title max 20 chars). buttons = [(id, title), ...]."""
        if not 1 <= len(buttons) <= 3:
            raise ValueError("WhatsApp allows 1-3 reply buttons")
        payload = {
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": bid, "title": title[:20]}}
                        for bid, title in buttons
                    ]
                },
            },
        }
        return await self._send(phone_number_id, payload)

    async def send_template(
        self, phone_number_id: str, to: str, name: str, language: str, body_params: list[str]
    ) -> dict:
        payload = {
            "to": to,
            "type": "template",
            "template": {
                "name": name,
                "language": {"code": language},
                "components": [
                    {"type": "body", "parameters": [{"type": "text", "text": p} for p in body_params]}
                ],
            },
        }
        return await self._send(phone_number_id, payload)

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Returns (bytes, mime_type). The media URL expires quickly, so fetch it right away."""
        meta = await self._http.get(f"/{media_id}")
        meta.raise_for_status()
        info = meta.json()
        # The download URL is absolute and needs the same bearer token.
        resp = await self._http.get(info["url"])
        resp.raise_for_status()
        return resp.content, info.get("mime_type", "application/octet-stream")
