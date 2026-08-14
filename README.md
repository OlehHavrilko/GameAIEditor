# Game AI Editor

Local-first AI editor for building cinematic highlight reels from long gameplay footage, with Arma Reforger as the first supported title.

Status: architecture-first scaffold only. Full automation pipeline will be implemented in subsequent phases.

## Goal

Given a long gameplay recording, the system should:

- analyze video and audio;
- recognize spoken commentary;
- detect firefights, kills, explosions, vehicle destruction, and unusual battlefield events;
- group related moments into narrative scenes;
- score highlights by cinematic value;
- select the best moments;
- add context before and after events;
- assemble a final sequence;
- render a final MP4 using FFmpeg as the primary editing engine.

## Core stack

- Python 3.11+
- FFmpeg + FFprobe
- faster-whisper
- OpenCV
- OCR / visual recognition layer
- Pydantic
- JSON-driven configuration
- CLI-first workflow

## Project structure

```text
GameAIEditor/
├── .github/
├── .gitignore
├── README.md
├── ARCHITECTURE.md
├── DEVELOPMENT.md
├── requirements.txt
├── pyproject.toml
├── config/
│   └── games/
│       └── arma_reforger.json
├── skills/
│   └── game-highlight-editor/
│       └── SKILL.md
├── src/
│   └── game_ai_editor/
│       ├── cli.py
│       ├── config/
│       ├── media/
│       ├── analysis/
│       ├── transcription/
│       ├── vision/
│       ├── events/
│       ├── scoring/
│       ├── selection/
│       ├── timeline/
│       ├── editing/
│       ├── audio/
│       ├── subtitles/
│       └── qc/
├── input/
├── output/
├── work/
└── tests/
```

## Design principles

1. Architecture before full automation.
2. Local-first processing and deterministic configuration.
3. Event detection must be contextual, not purely frame-based.
4. Narrative scenes matter more than isolated kills.
5. FFmpeg is the primary render and assembly engine.
6. Quality checks must happen before final export.

## Roadmap

- Phase 1: architecture and game profile definition
- Phase 2: media ingestion and metadata extraction
- Phase 3: audio transcription and speech analysis
- Phase 4: event detection and contextual scene grouping
- Phase 5: scoring, preselection, and timeline planning
- Phase 6: FFmpeg-based editing and export
- Phase 7: subtitle generation and final QC

This project intentionally starts with the design layer so the later automation logic has a strong contract and a clear, modular foundation.
