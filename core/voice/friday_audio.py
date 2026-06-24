from pathlib import Path

TEMP_AUDIO = Path("friday_reply.mp3")


def get_temp_audio_file():
    return str(TEMP_AUDIO)


def audio_exists():
    return TEMP_AUDIO.exists()


def audio_size():
    if TEMP_AUDIO.exists():
        return TEMP_AUDIO.stat().st_size
    return 0


def clear_audio():
    if TEMP_AUDIO.exists():
        TEMP_AUDIO.unlink()


if __name__ == "__main__":
    print("Exists:", audio_exists())
    print("Size:", audio_size(), "bytes")