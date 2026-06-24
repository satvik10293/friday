import asyncio
import edge_tts
import pygame
import time

from core.voice.friday_audio import get_temp_audio_file


class FridayVoice:

    def __init__(self, voice="en-US-GuyNeural"):
        self.voice = voice
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