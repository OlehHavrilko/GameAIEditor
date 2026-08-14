# Production Pipeline

`ProductionOrchestrator` is the only production execution path for `all` and `batch`.

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
  -> FFmpeg render
  -> QC
```

Vision windows are stored independently as `vision/window_*.json`. A successful window is reused during resume. A source fingerprint prevents stale sessions from being reused after a file replacement.

If no candidate survives selection, the session is marked `NO_HIGHLIGHTS` and no fake montage is rendered.