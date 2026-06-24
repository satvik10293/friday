import sounddevice as sd
import soundfile as sf
from faster_whisper import WhisperModel
import time

SAMPLE_RATE = 16000
DURATION = 5

print("Loading Whisper model...")

model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8"
)

print(f"Recording for {DURATION} seconds...")
print("Speak now!")

audio = sd.rec(
    int(DURATION * SAMPLE_RATE),
    samplerate=SAMPLE_RATE,
    channels=1,
    dtype="float32"
)

sd.wait()

sf.write("test.wav", audio, SAMPLE_RATE)

print("Transcribing...")

start = time.time()

segments, info = model.transcribe(
    "test.wav",
    beam_size=1
)

text = " ".join(segment.text for segment in segments)

elapsed = time.time() - start

print("\n----- RESULT -----")
print("Text:", text)
print(f"Transcription time: {elapsed:.2f} sec")