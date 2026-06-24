from faster_whisper import WhisperModel
import os


class FridaySTT:

    def __init__(
        self,
        model_size="base",
        device="cpu",
        compute_type="int8"
    ):
        print("[FridaySTT] Loading Whisper model...")

        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type
        )

        print("[FridaySTT] Ready")

    def transcribe_file(
        self,
        audio_file: str,
        beam_size: int = 1
    ) -> str:

        if not os.path.exists(audio_file):
            raise FileNotFoundError(
                f"Audio file not found: {audio_file}"
            )

        segments, _ = self.model.transcribe(
            audio_file,
            beam_size=beam_size
        )

        text = " ".join(
            segment.text.strip()
            for segment in segments
        )

        return text.strip()


