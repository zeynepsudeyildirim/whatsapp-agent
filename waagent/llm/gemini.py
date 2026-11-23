"""Gemini via the Generative Language REST API (Google AI Studio key).

FREE TIER WARNING: on the unpaid quota Google may use prompts and responses to improve its
products, and human reviewers may read them. Only synthetic test data may be sent with a
free-tier key. Production (users in the EU) requires the paid tier.
"""

import asyncio
import base64
import json
import random

import httpx
from pydantic import ValidationError

from waagent.llm.base import Audio, LLMError, T

_BASE = "https://generativelanguage.googleapis.com/v1beta"
_RETRYABLE = {429, 500, 502, 503, 504}


class GeminiLLM:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout: float = 60.0,
        max_attempts: int = 5,
        base_delay: float = 2.0,
    ):
        self._model = model
        self._max_attempts = max_attempts
        self._base_delay = base_delay
        self._http = httpx.AsyncClient(
            base_url=_BASE, headers={"x-goog-api-key": api_key}, timeout=timeout
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _post_with_retry(self, path: str, body: dict) -> httpx.Response:
        """Retries transient failures (overload, rate limit, network) with exponential backoff."""
        delay = self._base_delay
        for attempt in range(1, self._max_attempts + 1):
            try:
                resp = await self._http.post(path, json=body)
            except httpx.TransportError as exc:
                if attempt == self._max_attempts:
                    raise LLMError(f"Gemini unreachable: {exc}") from exc
            else:
                if resp.status_code == 200:
                    return resp
                if resp.status_code not in _RETRYABLE or attempt == self._max_attempts:
                    raise LLMError(f"Gemini HTTP {resp.status_code}: {resp.text[:500]}")
            await asyncio.sleep(delay + random.uniform(0, delay / 2))
            delay *= 2
        raise AssertionError("unreachable")

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        audio: Audio | None = None,
        temperature: float = 0.0,
    ) -> T:
        parts: list[dict] = []
        if audio is not None:
            # WhatsApp sends "audio/ogg; codecs=opus"; Gemini wants the bare type.
            mime = audio.mime_type.split(";")[0].strip()
            parts.append(
                {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio.data).decode()}}
            )
        parts.append({"text": prompt})

        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
                "responseJsonSchema": schema.model_json_schema(),
            },
        }
        resp = await self._post_with_retry(f"/models/{self._model}:generateContent", body)

        data = resp.json()
        try:
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError) as exc:
            raise LLMError(f"Unexpected Gemini response: {json.dumps(data)[:500]}") from exc
        try:
            return schema.model_validate_json(text)
        except ValidationError as exc:
            raise LLMError(f"Gemini output did not match {schema.__name__}: {exc}") from exc
