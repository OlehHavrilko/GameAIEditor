# Development Guide

## Project status

The repository contains the first working production MVP: CLI, batch, Vision providers, unified orchestration, FFmpeg rendering, QC, and an optional PySide6 desktop frontend.

## Local environment

### Requirements

- Windows 11
- Python 3.11+
- FFmpeg and FFprobe installed and available in PATH
- Git for versioning
- A local working directory for temporary media and generated exports

### Setup

```powershell
cd D:\vids\Arma Reforger\GameAIEditor
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Tooling

- Python: primary logic and CLI
- FFmpeg: final media assembly and cuts
- FFprobe: metadata and time extraction
- faster-whisper: transcription
- OpenCV: frame-level analysis
- OCR / vision model: UI detection and scene understanding
- Pydantic: validation and config structures
- PySide6: desktop frontend and background worker

## Directory responsibilities

- `input/`: source gameplay recordings
- `output/`: finished highlight videos
- `work/`: intermediate files and temporary renders
- `config/games/`: per-game profiles
- `skills/game-highlight-editor/`: editorial AI behavior and output rules
- `src/game_ai_editor/`: implementation modules
- `tests/`: unit and integration tests as development proceeds

## Implementation phases

### Current production MVP

The shared execution path is `ProductionOrchestrator.run()`. It writes resumable per-video sessions and accepts an injected `VisionProvider`. `batch.py` owns discovery, manifests, and isolation; it does not own scoring or rendering decisions.

### Phase 1: architecture and contracts

Complete:

- project skeleton
- JSON game profile
- professional game editor skill definition
- architecture and development docs

### Phase 2: media ingestion

Focus on:

- file validation;
- FFprobe metadata extraction;
- frame sampling;
- audio extraction;
- work folder generation.

### Phase 3: transcription and audio analysis

Focus on:

- faster-whisper transcriptions;
- speech events and radio chatter;
- loudness and impact detection;
- emotion cues tied to player speech.

### Phase 4: vision and object detection

Focus on:

- visual intensity;
- muzzle flash and explosions;
- motion spikes;
- UI overlays and objective states;
- scene understanding with OCR/vision model.

### Phase 5: event and scene synthesis

Focus on:

- connecting nearby events into a narrative scene;
- scoring based on intensity, rarity, narrative value, and confidence;
- filtering out routine non-events.

### Phase 6: timeline and editing

Focus on:

- selecting top highlights;
- planning cut points and context duration;
- applying FFmpeg-based transitions and effects;
- controlling pacing according to scene importance.

### Phase 7: subtitles and QC

Focus on:

- subtitle timing and readability;
- audio normalization;
- final quality checks;
- MP4 export with a polished final polish.

## Coding conventions

- Keep modules small, testable, and config-driven.
- Prefer Pydantic models for structured data.
- Prefer JSON profiles over hardcoded game logic.
- Keep FFmpeg operations in dedicated editing utilities.
- Preserve separation between detection, scoring, selection, and rendering.

## Safe validation

Run the fast suite with `pytest -q`. The orchestration test uses a short synthetic video, a mock Vision provider, real FFmpeg assembly, and QC; it never contacts Ollama. Do not run `all`, non-dry `batch`, or real long-video analysis without an explicit smoke-test decision.
