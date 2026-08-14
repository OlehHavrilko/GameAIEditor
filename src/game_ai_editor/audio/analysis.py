from __future__ import annotations

import math
import subprocess
import wave
from pathlib import Path

import numpy as np

from game_ai_editor.media.metadata import probe_media


def analyze_audio(path: str | Path, window_seconds: float = 1.0) -> dict:
    input_path = Path(path)
    metadata = probe_media(input_path)
    if not metadata.audio_stream:
        return {"has_audio": False, "average_intensity": 0.0, "peak_intensity": 0.0, "segments": []}

    wav_path = input_path.with_suffix(f"{input_path.suffix}.analysis.wav")
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
        raise RuntimeError(f"ffmpeg audio extraction failed: {result.stderr.strip()}")

    try:
        with wave.open(str(wav_path), "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            frames = wav_file.getnframes()
            chunk_size = max(1, int(sample_rate * window_seconds))

            values: list[float] = []
            for start in range(0, frames, chunk_size):
                chunk = wav_file.readframes(chunk_size)
                if not chunk:
                    break
                if sample_width == 1:
                    samples = np.frombuffer(chunk, dtype=np.uint8).astype(np.float32)
                    samples = (samples - 128.0) / 128.0
                elif sample_width == 2:
                    samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                elif sample_width == 4:
                    samples = np.frombuffer(chunk, dtype=np.int32).astype(np.float32) / 2147483648.0
                else:
                    continue

                if channels > 1:
                    samples = samples.reshape(-1, channels)
                    samples = samples.mean(axis=1)
                rms = float(np.sqrt(np.mean(np.square(samples))))
                values.append(rms)

        segments = []
        for index, intensity in enumerate(values):
            start = index * window_seconds
            end = min(start + window_seconds, metadata.duration or start + window_seconds)
            segments.append({
                "start": round(start, 3),
                "end": round(end, 3),
                "intensity": round(float(intensity), 6),
            })

        average = float(np.mean(values)) if values else 0.0
        peak = float(np.max(values)) if values else 0.0
        return {
            "has_audio": True,
            "average_intensity": round(average, 6),
            "peak_intensity": round(peak, 6),
            "segments": segments,
        }
    finally:
        if wav_path.exists():
            wav_path.unlink(missing_ok=True)
