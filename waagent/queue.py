"""Work queue between the webhook (fast path) and the worker (slow path).

The webhook only stores the message and enqueues its id; STT, LLM calls and sending happen
in the worker. Cloud Tasks gives us retries with backoff and a dead-letter policy for free.
"""

import base64
import json
from typing import Protocol

import httpx


class WorkQueue(Protocol):
    async def enqueue(self, message_id: str) -> None: ...


class InMemoryQueue:
    """For tests and local development: collects ids; call the worker endpoint yourself."""

    def __init__(self) -> None:
        self.items: list[str] = []

    async def enqueue(self, message_id: str) -> None:
        self.items.append(message_id)


class CloudTasksQueue:
    """Creates an HTTP task per message via the Cloud Tasks REST API.

    Runs on Cloud Run, so the access token comes from the metadata server.
    The task name is derived from the message id, so a duplicate enqueue is rejected by
    Cloud Tasks itself (ALREADY_EXISTS) — a second idempotency layer after the DB constraint.
    """

    _METADATA_TOKEN_URL = (
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
    )

    def __init__(self, queue_path: str, worker_url: str, worker_auth_token: str) -> None:
        self._queue_path = queue_path
        self._worker_url = worker_url
        self._worker_auth_token = worker_auth_token
        self._http = httpx.AsyncClient(timeout=10.0)

    async def _gcp_token(self) -> str:
        resp = await self._http.get(self._METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"})
        resp.raise_for_status()
        return resp.json()["access_token"]

    async def enqueue(self, message_id: str) -> None:
        task = {
            "name": f"{self._queue_path}/tasks/msg-{message_id}",
            "httpRequest": {
                "httpMethod": "POST",
                "url": self._worker_url,
                "headers": {
                    "Content-Type": "application/json",
                    "X-Worker-Token": self._worker_auth_token,
                },
                "body": base64.b64encode(json.dumps({"message_id": message_id}).encode()).decode(),
            },
        }
        resp = await self._http.post(
            f"https://cloudtasks.googleapis.com/v2/{self._queue_path}/tasks",
            headers={"Authorization": f"Bearer {await self._gcp_token()}"},
            json={"task": task},
        )
        if resp.status_code == 409:  # ALREADY_EXISTS: this message was enqueued before
            return
        resp.raise_for_status()
