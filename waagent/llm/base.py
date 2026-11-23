"""Provider-agnostic interface for LLM calls.

The pipeline only ever asks for "structured output matching this Pydantic model", optionally
with an audio clip attached. Swapping Gemini for Claude or another provider means writing one
new class with this method; nothing else changes.
"""

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Audio:
    data: bytes
    mime_type: str  # WhatsApp voice notes arrive as "audio/ogg; codecs=opus"


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        audio: Audio | None = None,
        temperature: float = 0.0,
    ) -> T: ...
