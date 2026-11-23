import base64
import json

import httpx
import pytest

from waagent.llm.base import Audio, LLMError
from waagent.llm.gemini import GeminiLLM
from waagent.pipeline.schemas import ComposedMessage


def _llm_with(handler) -> GeminiLLM:
    llm = GeminiLLM("k", "gemini-flash-latest", max_attempts=3, base_delay=0.0)
    llm._http = httpx.AsyncClient(
        base_url="https://x/v1beta", transport=httpx.MockTransport(handler),
        headers={"x-goog-api-key": "k"},
    )
    return llm


async def test_request_shape_and_parsing():
    seen = {}

    def handler(req: httpx.Request):
        seen["path"] = req.url.path
        seen["key"] = req.headers["x-goog-api-key"]
        seen["body"] = json.loads(req.content)
        out = {"candidates": [{"content": {"parts": [{"text": '{"text": "Hallo"}'}]}}]}
        return httpx.Response(200, json=out)

    llm = _llm_with(handler)
    res = await llm.structured(
        system="s", prompt="p", schema=ComposedMessage, audio=Audio(b"abc", "audio/ogg; codecs=opus")
    )
    assert res.text == "Hallo"
    assert seen["path"].endswith("/models/gemini-flash-latest:generateContent")
    assert seen["key"] == "k"
    parts = seen["body"]["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "audio/ogg"
    assert base64.b64decode(parts[0]["inline_data"]["data"]) == b"abc"
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"


async def test_overload_is_retried_then_succeeds():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(503, text="high demand")
        out = {"candidates": [{"content": {"parts": [{"text": '{"text": "ok"}'}]}}]}
        return httpx.Response(200, json=out)

    llm = _llm_with(handler)
    res = await llm.structured(system="s", prompt="p", schema=ComposedMessage)
    assert res.text == "ok" and len(calls) == 3


async def test_persistent_overload_raises_after_max_attempts():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503, text="high demand")

    llm = _llm_with(handler)
    with pytest.raises(LLMError, match="503"):
        await llm.structured(system="s", prompt="p", schema=ComposedMessage)
    assert len(calls) == 3


async def test_client_error_is_not_retried():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(400, text="bad request")

    llm = _llm_with(handler)
    with pytest.raises(LLMError, match="400"):
        await llm.structured(system="s", prompt="p", schema=ComposedMessage)
    assert len(calls) == 1


async def test_schema_mismatch_raises():
    out = {"candidates": [{"content": {"parts": [{"text": '{"nope": 1}'}]}}]}
    llm = _llm_with(lambda req: httpx.Response(200, json=out))
    with pytest.raises(LLMError, match="did not match"):
        await llm.structured(system="s", prompt="p", schema=ComposedMessage)
