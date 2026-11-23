"""Try the supplier pipeline on your own voice notes or text, with your Gemini key.

ONLY USE SYNTHETIC TEST DATA with a free-tier key (Google may use it; humans may read it).

Usage:
    python scripts/try_order.py --text "Metro'ya yarın 20 kilo kıyma, 10 kasa domates"
    python scripts/try_order.py --audio test_audio/siparis1.ogg
    python scripts/try_order.py --dir test_audio           # every audio file in the folder

Reads GEMINI_API_KEY (and optionally GEMINI_MODEL) from the environment or from .env.
"""

import argparse
import asyncio
import mimetypes
import os
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from waagent.llm.base import Audio, LLMError  # noqa: E402
from waagent.llm.gemini import GeminiLLM  # noqa: E402
from waagent.pipeline.supplier_order import draft_supplier_message  # noqa: E402

# The pilot's two suppliers (names are placeholders — edit freely).
SUPPLIERS = {
    "s-de": ("Metro", "de"),
    "s-en": ("Fresh Farms", "en"),
}
AUDIO_TYPES = {
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".mp3": "audio/mp3",
    ".wav": "audio/wav",
    ".m4a": "audio/aac",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
}


def load_env() -> None:
    env = Path(__file__).resolve().parents[1] / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


async def run_one(llm: GeminiLLM, *, text: str | None = None, path: Path | None = None) -> None:
    audio = None
    if path is not None:
        mime = AUDIO_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path)[0]
        audio = Audio(path.read_bytes(), mime or "application/octet-stream")
        print(f"\n=== {path.name} ===")
    else:
        print("\n=== text ===")

    t0 = time.perf_counter()
    try:
        d = await draft_supplier_message(
            llm, today=date.today(), suppliers=SUPPLIERS, text=text, audio=audio
        )
    except LLMError as exc:
        print(f"HATA: {exc}")
        return
    secs = time.perf_counter() - t0

    print(f"Transkript ({d.understood.language}): {d.understood.transcript}")
    print("\n--- Sahibe gidecek onay kartı ---")
    print(d.summary_for_admin)
    if d.needs_clarification:
        print("\n--- Agent soracak ---")
        for q in d.needs_clarification:
            print(f"? {q}")
    if d.outbound_text:
        print("\n--- Tedarikçiye gidecek metin ---")
        print(d.outbound_text)
    if d.verification:
        status = "GEÇTİ" if d.verification.ok else "KALDI"
        print(f"\nDoğrulama: {status}")
        for p in d.verification.problems:
            print(f"  - {p}")
    print(f"Süre: {secs:.1f} sn | onaya hazır: {d.ready_for_approval}")


async def main() -> None:
    load_env()
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY yok. .env dosyasına GEMINI_API_KEY=... satırını ekle.")
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--text")
    g.add_argument("--audio", type=Path)
    g.add_argument("--dir", type=Path)
    args = p.parse_args()

    llm = GeminiLLM(key, model)
    print(f"Model: {model}")
    try:
        if args.text:
            await run_one(llm, text=args.text)
        elif args.audio:
            await run_one(llm, path=args.audio)
        else:
            files = sorted(f for f in args.dir.iterdir() if f.suffix.lower() in AUDIO_TYPES)
            for f in files:
                await run_one(llm, path=f)
    finally:
        await llm.aclose()


if __name__ == "__main__":
    asyncio.run(main())
