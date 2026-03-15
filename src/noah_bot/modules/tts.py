from elevenlabs.client import ElevenLabs
from elevenlabs.play import play
from typing import Iterator

NOAH_VOICE_ID = "9EU0h6CVtEDS6vriwwq5"

def text_to_speech(text: str) -> bytes:
    elevenlabs = ElevenLabs()

    response: Iterator[bytes] = elevenlabs.text_to_speech.stream(
        text=text,
        voice_id=NOAH_VOICE_ID,
        model_id="eleven_v3",
        output_format="mp3_44100_128",
    )

    return response


if __name__ == "__main__":
    streaming = text_to_speech("Hola, soy Noah")
    play(streaming)
