from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from game_ai_editor.media.metadata import probe_media

try:
    from faster_whisper import WhisperModel  # type: ignore
except ImportError:  # pragma: no cover
    WhisperModel = None


def transcribe_audio(path: str | Path) -> dict[str, Any]:
    input_path = Path(path)
    metadata = probe_media(input_path)
    if not metadata.audio_stream:
        return {
            "has_audio": False,
            "fallback": True,
            "segments": [],
            "text": "",
            "speech_reaction": 0.0,
        }

    wav_path = input_path.with_suffix(f"{input_path.suffix}.transcript.wav")
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        str(wav_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg transcript extraction failed: {result.stderr.strip()}")

    try:
        if WhisperModel is None:
            return {
                "has_audio": True,
                "fallback": True,
                "segments": [],
                "text": "",
                "speech_reaction": 0.0,
            }

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(wav_path), vad_filter=True, word_timestamps=False)
        transcript_segments = [
            {
                "start": round(float(segment.start), 3),
                "end": round(float(segment.end), 3),
                "text": segment.text.strip(),
                "confidence": round(float(segment.avg_logprob if hasattr(segment, "avg_logprob") else 0.0), 3),
            }
            for segment in segments
        ]
        transcript_text = " ".join(item["text"] for item in transcript_segments if item["text"]).strip()
        keywords = ["nice", "good", "damn", "oh", "shit", "grenade", "kill", "great", "wow", "yeah", "go", "fire"]
        speech_reaction = 1.0 if any(keyword in transcript_text.lower() for keyword in keywords) else 0.0
        return {
            "has_audio": True,
            "fallback": False,
            "segments": transcript_segments,
            "text": transcript_text,
            "speech_reaction": round(float(speech_reaction), 3),
        }
    finally:
        if wav_path.exists():
            wav_path.unlink(missing_ok=True)
