# Production Pipeline

`ProductionOrchestrator` is the only production execution path for `all` and `batch`.

## Canonical media storage contract

```text
input/                  # source user video files
work/                   # intermediate artifacts and session state
output/<project_id>/    # production outputs for the user
```

For each analysis session:

```text
work/sessions/<session_id>/
  metadata.json
  prefilter/
  signals/
  vision/
  events.json
  arcs.json
  ranking.json
  selection.json
  timeline.json
  evaluation/
  status.json
```

All final user-facing outputs are stored only under:

```text
output/<project_id>/final.mp4
output/<project_id>/preview.mp4
```

Production sessions always use `work/sessions/<session_id>/`; the session ID is stable for a source identity. Batch and desktop queue entries point to the same layout.

The current public result is represented only by the two files above. Previous successful files are archived under `output/<project_id>/runs/<session_id>/` when a new run invalidates them. A `NO_HIGHLIGHTS` result archives and removes the current files, and returns null output paths so the UI cannot display a stale montage.

The backend must return final output paths via `final_output_path` and `preview_output_path`. The UI consumes exactly those values and must not re-derive a result path.

Legacy `finalvids/` remains deprecated and is retained only as compatibility storage; new production paths always go to `output/<project_id>/`.

```text
metadata
  -> prefilter
  -> audio / motion / transcription / VisionProvider
  -> normalized events
  -> fused events
  -> EventArc
  -> scoring
  -> selection
  -> timeline
  -> FFmpeg render -> output/<project_id>/final.mp4
  -> QC
```

Vision windows are stored independently as `vision/window_*.json`. A successful window is reused during resume. A source fingerprint prevents stale sessions from being reused after a file replacement. Fast identity uses normalized path, size, and `mtime_ns`; an optional SHA-256 strong identity is available for explicit or ambiguous validation and is not computed for every stage.

If no candidate survives selection, the session is marked `NO_HIGHLIGHTS` and no fake montage is rendered.

Long-running desktop operations are cancellable between pipeline stages and Vision windows. Model download runs in a worker thread and terminates the owned `ollama pull` process on cancellation. A queue session left in `RUNNING` after a crash is recovered as `RECOVERABLE` on the next application start. Render output is written to temporary files, checked with FFprobe/QC, and atomically published only after QC passes.