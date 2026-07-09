import asyncio
import edge_tts

VOICE = "en-US-AriaNeural"


async def speak_to_file(text: str, output_file: str = "friday_reply.mp3"):
    tts = edge_tts.Communicate(text, VOICE)
    await tts.save(output_file)
    return output_file


def speak(text: str):
    asyncio.run(speak_to_file(text))


if __name__ == "__main__":
    print("[friday_tts] Running self-test...")
    speak("Hello Satvik. Voice systems are online.")
    print("Audio generated: friday_reply.mp3")