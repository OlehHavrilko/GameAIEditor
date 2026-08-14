from __future__ import annotations

import math
from pathlib import Path
from typing import Any


def _sample_at_time(samples: list[dict], target_time: float, field_name: str = "score") -> float:
    if not samples:
        return 0.0
    nearest = min(samples, key=lambda item: abs(float(item.get("time", 0.0)) - target_time))
    value = nearest.get(field_name, 0.0)
    return float(value)


def _cluster_segments(samples: list[dict], duration: float, threshold: float) -> list[dict]:
    clusters: list[dict] = []
    active = None
    for sample in samples:
        value = float(sample.get("intensity", 0.0))
        if value >= threshold:
            if active is None:
                active = {"start": float(sample.get("time", 0.0)), "end": float(sample.get("time", 0.0)), "peak": value}
            else:
                active["end"] = float(sample.get("time", 0.0))
                active["peak"] = max(active["peak"], value)
        elif active is not None:
            clusters.append(active)
            active = None

    if active is not None:
        clusters.append(active)

    if not clusters and duration > 0 and samples:
        fallback_peak = max(float(sample.get("intensity", 0.0)) for sample in samples)
        if fallback_peak >= max(0.25, threshold * 0.5):
            fallback_sample = max(samples, key=lambda sample: float(sample.get("intensity", 0.0)))
            time_value = float(fallback_sample.get("time", 0.0))
            clusters.append({"start": time_value, "end": time_value, "peak": float(fallback_sample.get("intensity", 0.0))})

    return clusters


def detect_events(metadata: Any, audio_summary: dict, motion_summary: dict, transcript_summary: dict, profile: Any) -> list[dict]:
    duration = float(metadata.duration or 0.0)
    if duration <= 0:
        return []

    motion_samples = motion_summary.get("samples", [])
    audio_segments = audio_summary.get("segments", [])
    transcript_segments = transcript_summary.get("segments", [])
    ignored = set(profile.ignored_events)
    interesting = set(profile.interesting_events)
    narrative_threshold = float(profile.narrative_signals.get("importance_threshold", 0.45))

    signal_samples = []
    step_size = 0.1
    for step in [index * step_size for index in range(int(math.ceil(duration / step_size)) + 1)]:
        motion_score = _sample_at_time(motion_samples, step, "score")
        motion_peak = float(motion_summary.get("peak_motion", 1.0) or 1.0)
        if motion_peak <= 0:
            motion_norm = 0.0
        else:
            motion_norm = min(1.0, motion_score / max(1.0, motion_peak))
        audio_intensity = _sample_at_time(audio_segments, step, "intensity")
        audio_norm = min(1.0, audio_intensity * 10.0)
        speech_reaction = 0.0
        for segment in transcript_segments:
            start = float(segment.get("start", 0.0))
            end = float(segment.get("end", 0.0))
            text = str(segment.get("text", "")).lower()
            if start <= step <= end or (start <= step + 0.5 and step <= end + 0.5):
                if any(keyword in text for keyword in ["nice", "damn", "oh", "shit", "great", "kill", "wow", "go", "fire"]):
                    speech_reaction = 1.0
                    break
        motion_boost = max(0.0, (motion_norm - 0.55)) * 0.45
        intensity = (0.55 * motion_norm) + (0.25 * audio_norm) + (0.15 * speech_reaction) + motion_boost
        signal_samples.append({"time": round(step, 3), "intensity": round(intensity, 6), "motion": round(motion_norm, 6), "audio": round(audio_norm, 6), "speech": round(speech_reaction, 6)})

    clusters = _cluster_segments(signal_samples, duration, narrative_threshold)
    events: list[dict] = []

    for index, cluster in enumerate(clusters):
        start_time = float(cluster.get("start", 0.0))
        end_time = float(cluster.get("end", 0.0))
        if end_time <= start_time:
            end_time = min(duration, start_time + 1.0)

        max_motion = max(
            _sample_at_time(motion_samples, target, "score") for target in [start_time, (start_time + end_time) / 2, end_time]
        )
        max_audio = max(
            _sample_at_time(audio_segments, target, "intensity") for target in [start_time, (start_time + end_time) / 2, end_time]
        )
        speech_reaction = max(
            _sample_at_time(
                [
                    {"time": float(segment.get("start", 0.0)), "score": 1.0 if any(keyword in str(segment.get("text", "")).lower() for keyword in ["nice", "damn", "oh", "shit", "great", "kill", "wow", "go", "fire"]) else 0.0}
                    for segment in transcript_segments
                ],
                target,
                "score",
            )
            for target in [start_time, (start_time + end_time) / 2, end_time]
        )

        if max_audio > 0.9 and max_motion > 0.7:
            event_type = "explosion"
        elif max_motion > 0.55 and (end_time - start_time) < 2.5:
            event_type = "kill"
        elif max_motion > 0.5 and speech_reaction > 0.5:
            event_type = "radio_communication"
        elif max_motion > 0.45 and (end_time - start_time) > 3.5:
            event_type = "firefight"
        elif max_motion > 0.35:
            event_type = "enemy_contact"
        else:
            event_type = "enemy_contact"

        if event_type in ignored or event_type not in interesting:
            if event_type in ignored:
                continue
            if event_type not in interesting:
                event_type = "firefight"

        intensity = min(1.0, ((max_motion / max(1.0, motion_summary.get("peak_motion", 1.0))) * 0.5) + (max_audio * 0.35) + (speech_reaction * 0.15))
        confidence = round(min(1.0, 0.5 + intensity * 0.5), 3)
        narrative_value = round(min(1.0, intensity * 0.9 + speech_reaction * 0.2), 3)
        event = {
            "id": f"event_{index:03d}",
            "event_type": event_type,
            "start_time": round(start_time, 3),
            "end_time": round(end_time, 3),
            "duration": round(end_time - start_time, 3),
            "confidence": confidence,
            "intensity": round(intensity, 3),
            "audio_intensity": round(min(1.0, max_audio), 3),
            "visual_intensity": round(min(1.0, max_motion / max(1.0, motion_summary.get("peak_motion", 1.0))), 3),
            "speech_reaction": round(speech_reaction, 3),
            "narrative_value": narrative_value,
            "rarity": round(min(1.0, 0.4 + intensity * 0.6), 3),
            "novelty": round(min(1.0, 0.2 + intensity * 0.8), 3),
            "tags": [event_type],
            "kill_count": 1 if event_type in {"kill", "multi_kill", "headshot"} else 0,
            "score": 0.0,
        }
        events.append(event)

    return events
