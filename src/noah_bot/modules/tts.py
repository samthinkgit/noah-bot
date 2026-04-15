import json
import os
from typing import Any
from typing import Iterator

from elevenlabs.client import ElevenLabs
from elevenlabs.play import play


DEFAULT_VOICE_NAME = "noah"
DEFAULT_VOICE_ID = "9EU0h6CVtEDS6vriwwq5"


def _normalize_voice_name(name: str) -> str:
    return name.strip().lower()


class TTSVoiceStore:
    def __init__(self, json_path: str = "tts_voices.json") -> None:
        self.json_path = json_path
        self._state: dict[str, Any] = {
            "active_voice": DEFAULT_VOICE_NAME,
            "voices": {
                DEFAULT_VOICE_NAME: {
                    "name": DEFAULT_VOICE_NAME,
                    "voice_id": DEFAULT_VOICE_ID,
                }
            },
        }
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.json_path):
            self._save()
            return

        with open(self.json_path, "r", encoding="utf-8") as file:
            self._state = json.load(file)

        self._normalize_loaded_state()
        self._save()

    def _normalize_loaded_state(self) -> None:
        raw_voices = self._state.get("voices", {})
        normalized_voices: dict[str, dict[str, str]] = {}

        if isinstance(raw_voices, dict):
            for key, payload in raw_voices.items():
                normalized_name = _normalize_voice_name(str(key))
                if not normalized_name:
                    continue

                if isinstance(payload, dict):
                    voice_id = str(payload.get("voice_id", "")).strip()
                    display_name = str(payload.get("name", normalized_name)).strip()
                else:
                    voice_id = str(payload).strip()
                    display_name = normalized_name

                if not voice_id:
                    continue

                normalized_voices[normalized_name] = {
                    "name": display_name or normalized_name,
                    "voice_id": voice_id,
                }

        if DEFAULT_VOICE_NAME not in normalized_voices:
            normalized_voices[DEFAULT_VOICE_NAME] = {
                "name": DEFAULT_VOICE_NAME,
                "voice_id": DEFAULT_VOICE_ID,
            }

        active_voice = _normalize_voice_name(str(self._state.get("active_voice", "")))
        if active_voice not in normalized_voices:
            active_voice = DEFAULT_VOICE_NAME

        self._state = {
            "active_voice": active_voice,
            "voices": normalized_voices,
        }

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.json_path) or ".", exist_ok=True)
        with open(self.json_path, "w", encoding="utf-8") as file:
            json.dump(self._state, file, indent=2, ensure_ascii=False)

    def list_voices(self) -> list[dict[str, str | bool]]:
        active_voice = self._state["active_voice"]
        voices = self._state["voices"]
        rows: list[dict[str, str | bool]] = []

        for key in sorted(voices.keys()):
            payload = voices[key]
            rows.append(
                {
                    "name": payload["name"],
                    "voice_id": payload["voice_id"],
                    "active": key == active_voice,
                }
            )

        return rows

    def add_voice(self, voice_id: str, name: str) -> bool:
        normalized_name = _normalize_voice_name(name)
        cleaned_voice_id = voice_id.strip()

        if not normalized_name or not cleaned_voice_id:
            return False

        self._state["voices"][normalized_name] = {
            "name": name.strip() or normalized_name,
            "voice_id": cleaned_voice_id,
        }
        self._save()
        return True

    def delete_voice(self, name: str) -> bool:
        normalized_name = _normalize_voice_name(name)
        if normalized_name not in self._state["voices"]:
            return False

        if normalized_name == DEFAULT_VOICE_NAME:
            return False

        del self._state["voices"][normalized_name]

        if self._state["active_voice"] == normalized_name:
            self._state["active_voice"] = DEFAULT_VOICE_NAME

        self._save()
        return True

    def set_active_voice(self, name: str) -> bool:
        normalized_name = _normalize_voice_name(name)
        if normalized_name not in self._state["voices"]:
            return False

        self._state["active_voice"] = normalized_name
        self._save()
        return True

    def get_active_voice(self) -> dict[str, str]:
        active_key = self._state["active_voice"]
        payload = self._state["voices"][active_key]
        return {
            "name": payload["name"],
            "voice_id": payload["voice_id"],
        }


def text_to_speech(text: str, voice_id: str) -> Iterator[bytes]:
    elevenlabs = ElevenLabs()

    response: Iterator[bytes] = elevenlabs.text_to_speech.stream(
        text=text,
        voice_id=voice_id,
        model_id="eleven_v3",
        output_format="mp3_44100_128",
    )

    return response


if __name__ == "__main__":
    streaming = text_to_speech("Hola, soy Noah", DEFAULT_VOICE_ID)
    play(streaming)
