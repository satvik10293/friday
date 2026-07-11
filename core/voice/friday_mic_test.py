"""
core/voice/friday_mic_test.py — Friday 3.0
Quick microphone + STT sanity check: record a few seconds, transcribe, time it.
Run it explicitly — importing this module does nothing (the 3.0 version
started recording AT IMPORT, which ambushed anyone who touched the package).

    python -m core.voice.friday_mic_test
"""

SAMPLE_RATE = 16000
DURATION = 5


def main() -> int:
    import time

    import numpy as np
    import sounddevice as sd
    from faster_whisper import WhisperModel

    print("Loading Whisper model...")
    model = WhisperModel("base", device="cpu", compute_type="int8")

    print(f"Recording for {DURATION} seconds...")
    print("Speak now!")
    audio = sd.rec(int(DURATION * SAMPLE_RATE), samplerate=SAMPLE_RATE,
                   channels=1, dtype="float32")
    sd.wait()

    print("Transcribing...")
    start = time.time()
    # faster-whisper takes numpy audio directly — nothing written to disk
    segments, _info = model.transcribe(np.asarray(audio[:, 0]), beam_size=1)
    text = " ".join(segment.text for segment in segments).strip()
    elapsed = time.time() - start

    print("\n----- RESULT -----")
    print("Text:", text or "(silence)")
    print(f"Transcription time: {elapsed:.2f} sec")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
