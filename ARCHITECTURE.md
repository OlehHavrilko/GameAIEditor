# Architecture

## 1. Mission

Game AI Editor is a local, CLI-driven engineering project for creating professional highlight reels from long-form gameplay recordings. The system is designed to work with game footage from Arma Reforger first, while keeping the architecture generic enough to support additional titles later.

## 2. Architectural principles

- Context-aware detection wins over raw event templating.
- Events are not isolated data points; they belong to narrative scenes.
- Audio, visual, and speech data are analyzed as independent sensors but fused into a single story model.
- Scene selection is ranking-driven, not purely threshold-driven.
- FFmpeg remains the rendering engine and cutting backbone.
- Configuration is JSON-first so each game can define its own rules without changing the code structure.

## 3. High-level runtime flow

```text
CLI / desktop / batch
  -> ProductionOrchestrator
  -> Media metadata
  -> Fast prefilter (skipped entirely when no VisionProvider is configured)
  -> Audio + motion + transcription, run concurrently; VisionProvider only if enabled
  -> Event normalization and fusion (motion/audio/speech keyword classification is
     already sufficient for narrative event typing; Vision only adds more)
  -> Event Arc
  -> Existing scoring / selection / timeline
  -> Existing FFmpeg renderer (aspect ratio preset + subtitle burn-in optional)
  -> Existing QC
```

## 4. Package responsibilities

### src/game_ai_editor/cli.py

Entry point for the CLI. Handles arguments such as game profile, source input, output path, and dry-run mode during the architecture-first stage.

### src/game_ai_editor/config

Loads JSON game profiles and config contracts. This package owns game metadata, event definitions, scoring weights, ignore lists, and editing rules.

### src/game_ai_editor/media

Media ingestion layer. Handles file validation, FFprobe metadata extraction, video/audio splitting, frame sampling, and work directory generation.

### src/game_ai_editor/orchestration

Owns the single production execution path, canonical event contracts, signal fusion, session artifacts, source identity, resume state, error isolation, and progress callbacks. It depends on `VisionProvider`, never on Ollama directly.

### src/game_ai_editor/analysis

Cross-signal analysis that fuses data from audio, vision, and transcription into a coarse event timeline. This creates early candidate moments before final scoring.

### src/game_ai_editor/transcription

Speech recognition pipeline using faster-whisper. Designed to capture radio chatter, shouting, teammate coordination, and reactions that often add emotional value to a scene.

### src/game_ai_editor/vision

Computer vision and OCR layer. Detects motion, combat frames, muzzle flashes, explosions, map states, UI overlays, damage indicators, and visual intensity changes.

### src/game_ai_editor/events

Defines event candidates and narrative segments. An event may be a kill, explosion, firefight, objective capture, or near-death escape. This package groups nearby events into larger moments.

### src/game_ai_editor/scoring

Scoring engine for each candidate event or scene. Score is based on intensity, kills, rarity, audio intensity, speech reaction, visual intensity, narrative value, novelty, and confidence.

### src/game_ai_editor/selection

Ranks scenes, filters out noise, and chooses the best moments to include in the final cut. This package balances quality, pacing, and variety.

### src/game_ai_editor/timeline

Creates beat order, inserts pre-roll and post-roll, sets cut points, and keeps the final montage coherent and story-driven instead of random.

### src/game_ai_editor/editing

FFmpeg-only editing layer for cuts, transitions, speed ramps, slow motion, punch-ins, audio ducking, and final assembly.

### src/game_ai_editor/audio

Audio normalization, loudness balancing, impact enhancement, ducking, and cleanup for final export.

### src/game_ai_editor/subtitles

Generates SRT captions from the transcript for each rendered clip's own window and re-times them relative to that clip, then burns them in via FFmpeg with a readable, non-intrusive default style.

### src/game_ai_editor/qc

Quality control stage that validates final render constraints: runtime length, audio sync, subtitle readability, and carry-through of event context.

QC also validates that preview and final files are non-empty, decodable, contain valid video streams, codec, dimensions, FPS, duration, and consistent metadata. Missing audio is a warning for video-only sources unless audio is explicitly expected. Publication is atomic: temporary render files are promoted only after QC succeeds.

## 5. Context-aware scene model

A single narrative scene should include the entire chain of related action rather than isolated events.

Example:

- enemy contact
- preparation
- firefight
- first kill
- second enemy
- second kill
- explosion
- player reaction

This chain is treated as one scene with:

- a clear start;
- a clear end;
- an appropriate pre-roll;
- an appropriate post-roll;
- a scored importance;
- emotional evaluation;
- rarity and spectacle evaluation;
- narrative continuity.

## 6. Data model intent

The system should emit structured JSON for each event and scene with fields such as:

- start_time
- end_time
- event_type
- confidence
- intensity
- severity
- narrative_role
- pre_roll_seconds
- post_roll_seconds
- score
- tags
- edit_notes

This gives a deterministic contract between detection, selection, and editor components.

## 7. Game profile system

Each game is represented by a JSON profile in `config/games/`. The profile defines:

- title and metadata;
- interesting events;
- ignored events;
- scoring weights;
- scene semantics;
- transition rules;
- pre/post-roll expectations.

The current profile is `config/games/arma_reforger.json`.

## 8. Editing rules foundation

Game profiles declare per-event `editing_rules` (hard cut by default; punch-in for
kills; slow motion for important kills; speed ramp for multi-kills; shake for
explosions; and so on) as contextual recommendations, not uniform behavior.
This schema exists in `config/games/arma_reforger.json` but is not yet consumed
by the renderer - it is groundwork for future per-event transitions/effects.

What the renderer (`editing/ffmpeg_editor.py`) actually applies today:

- output aspect ratio presets (16:9 / 9:16 / 1:1 - scale-to-cover + center-crop);
- subtitle burn-in from the transcript, timed per rendered clip.

Music tracks and intro/outro are deliberately deferred until there is a proper
asset library feature (pick from a curated set, not auto-mixing arbitrary files).

## 9. Quality gates

Before export, the final result should pass:

- audio normalization;
- cut continuity checks;
- subtitle timing validation;
- narrative pacing checks;
- minimum quality threshold for final highlight count.

## 10. Desktop boundary

`desktop/` is an optional PySide6 frontend. It owns queue widgets, settings, and worker threads. Backend orchestration has no dependency on Qt and can be used from CLI or batch.

## 11. Session artifacts

Each production session stores source identity, stage status, normalized events, arcs, ranking, selection, timeline, output, and QC under `work/sessions/<session_id>/`. Vision windows are independent files so successful windows can be reused during resume. Cached JSON is accepted only when its minimal artifact contract is valid. Public outputs live under `output/<project_id>/`; prior current files may be archived in `runs/`, while `NO_HIGHLIGHTS` leaves no current result.
