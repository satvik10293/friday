"""
core/voice/friday_tts.py — Friday 3.0
Bare TTS-to-file helper (edge-tts). Output defaults to the per-process temp
audio path — never the CWD, which may be a read-only install directory.
"""

import asyncio

from core.voice.friday_audio import get_temp_audio_file

VOICE = "en-US-AriaNeural"


async def speak_to_file(text: str, output_file: str = ""):
    import edge_tts
    output_file = output_file or get_temp_audio_file()
    tts = edge_tts.Communicate(text, VOICE)
    await tts.save(output_file)
    return output_file


def speak(text: str) -> str:
    return asyncio.run(speak_to_file(text))


if __name__ == "__main__":
    print("[friday_tts] Running self-test...")
    path = speak("Hello Satvik. Voice systems are online.")
    print(f"Audio generated: {path}")
