"""Gemini via the Generative Language REST API (Google AI Studio key).

FREE TIER WARNING: on the unpaid quota Google may use prompts and responses to improve its
products, and human reviewers may read them. Only synthetic test data may be sent with a
free-tier key. Production (users in the EU) requires the paid tier.
"""

import base64
import json

import httpx
from pydantic import ValidationError

from waagent.llm.base import Audio, LLMError, T

_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiLLM:
    def __init__(self, api_key: str, model: str, *, timeout: float = 60.0):
        self._model = model
        self._http = httpx.AsyncClient(
            base_url=_BASE, headers={"x-goog-api-key": api_key}, timeout=timeout
        )

    async def aclose(self) -> None:
        await self._http.aclose()

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
        resp = await self._http.post(f"/models/{self._model}:generateContent", json=body)
        if resp.status_code != 200:
            raise LLMError(f"Gemini HTTP {resp.status_code}: {resp.text[:500]}")

        data = resp.json()
        try:
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError) as exc:
            raise LLMError(f"Unexpected Gemini response: {json.dumps(data)[:500]}") from exc
        try:
            return schema.model_validate_json(text)
        except ValidationError as exc:
            raise LLMError(f"Gemini output did not match {schema.__name__}: {exc}") from exc
