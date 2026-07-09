import asyncio
import json
import edge_tts
import pygame
import time
from pathlib import Path

from core.voice.friday_audio import get_temp_audio_file

DEFAULT_VOICE = "en-US-AriaNeural"
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "friday_config.json"


def _config_voice():
    try:
        cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        return (cfg.get("voice") or {}).get("voice_id") or cfg.get("voice_id")
    except (OSError, ValueError):
        return None


class FridayVoice:

    def __init__(self, voice=None):
        self.voice = voice or _config_voice() or DEFAULT_VOICE
        self.temp_file = get_temp_audio_file()

    async def _generate(self, text):
        tts = edge_tts.Communicate(text, self.voice)
        await tts.save(self.temp_file)

    def say(self, text):

        print(f"\n[Friday] {text}")

        asyncio.run(self._generate(text))

        pygame.init()
        pygame.mixer.init()

        pygame.mixer.music.load(self.temp_file)
        pygame.mixer.music.play()

        while pygame.mixer.music.get_busy():
            time.sleep(0.1)

        pygame.mixer.quit()


if __name__ == "__main__":

    voice = FridayVoice()

    voice.say("Hello Satvik. Voice systems are online.")
    voice.say("Phase one brain modules are operational.")