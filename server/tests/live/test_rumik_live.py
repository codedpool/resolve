"""Three sentences over one Rumik session, cancelling during the second. Marked live (small cost)."""

import asyncio
import time

import pytest

from app.config import get_settings
from app.voice.tts import RumikTTS

pytestmark = pytest.mark.live

SENTENCES = [
    "Namaste, main aapki shikayat ke baare mein baat kar raha hoon.",
    "Aapka order pandrah November ko hua tha aur paisa abhi tak wapas nahi aaya hai.",
    "Kya aap mujhe refund ki tarikh bata sakte hain?",
]


def test_three_sentences_with_a_cancel_in_the_second():
    settings = get_settings()
    assert settings.rumik_api_key
    tts = RumikTTS(settings.rumik_api_key)

    async def go():
        first_audio = []
        started = time.perf_counter()
        first = [c async for c in tts.speak(SENTENCES[0])]
        first_audio.append(time.perf_counter() - started)
        got = 0
        async for _chunk in tts.speak(SENTENCES[1]):
            got += 1
            if got == 2:
                await tts.cancel()
                break
        third = [c async for c in tts.speak(SENTENCES[2])]
        await tts.close()
        return first, got, third, first_audio

    first, got, third, timing = asyncio.run(go())
    assert len(first) > 3 and got == 2 and len(third) > 3
    print("seconds for the first sentence to finish:", round(timing[0], 2))
