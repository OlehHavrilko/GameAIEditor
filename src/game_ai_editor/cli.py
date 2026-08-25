from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from game_ai_editor.batch import run_batch
from game_ai_editor.diagnostics import collect_system_diagnostics
from game_ai_editor.editing.ffmpeg_editor import ASPECT_RATIO_PRESETS
from game_ai_editor.events.vision_adapter import run_event_test
from game_ai_editor.runtime import OllamaRuntimeManager
from game_ai_editor.vision.poc import run_vision_test
from game_ai_editor.vision.prefilter import run_prefilter
from game_ai_editor.vision.scan import run_vision_scan
from game_ai_editor.workflow import (
    analyze_video,
    benchmark_motion_video,
    detect_candidates,
    edit_session,
    qc_session,
    render_session,
    run_all_pipeline,
    select_highlights_for_session,
)

LOGGER = logging.getLogger("game_ai_editor")
DEFAULT_PROFILE = Path("config/games/arma_reforger.json")


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Game AI Editor MVP")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser("analyze", help="Analyze a video and create a session")
    analyze_parser.add_argument("source", help="Path to the input video")
    analyze_parser.add_argument("--profile", default=str(DEFAULT_PROFILE), help="Path to a custom game profile")

    detect_parser = subparsers.add_parser("detect", help="Detect candidates from a session directory")
    detect_parser.add_argument("session", help="Path to a session directory created by analyze")
    detect_parser.add_argument("--profile", default=str(DEFAULT_PROFILE), help="Path to a custom game profile")

    select_parser = subparsers.add_parser("select", help="Select the best highlights from candidates")
    select_parser.add_argument("session", help="Path to a session directory")
    select_parser.add_argument("--profile", default=str(DEFAULT_PROFILE), help="Path to a custom game profile")

    edit_parser = subparsers.add_parser("edit", help="Create preview output from a selected timeline")
    edit_parser.add_argument("session", help="Path to a session directory")
    edit_parser.add_argument(
        "--aspect", choices=sorted(ASPECT_RATIO_PRESETS), default=None, help="Output aspect ratio preset (default: source aspect)"
    )
    edit_parser.add_argument("--subtitles", action="store_true", help="Burn in subtitles generated from the speech transcript")

    render_parser = subparsers.add_parser("render", help="Render the final MP4 from preview output")
    render_parser.add_argument("session", help="Path to a session directory")

    qc_parser = subparsers.add_parser("qc", help="Run QC on preview/final outputs")
    qc_parser.add_argument("session", help="Path to a session directory")

    benchmark_parser = subparsers.add_parser("benchmark-motion", help="Benchmark sampled motion analysis on a source video")
    benchmark_parser.add_argument("source", help="Path to the input video")
    benchmark_parser.add_argument("--sample-fps", type=float, default=2.0, help="Target FPS for motion sampling. Default: 2 FPS")
    benchmark_parser.add_argument("--motion-threshold", type=float, default=8.0, help="Threshold for motion spike detection")

    vision_parser = subparsers.add_parser("vision-test", help="Run an isolated Ollama Vision PoC on one short scene")
    vision_parser.add_argument("source", help="Path to the input video")
    vision_parser.add_argument("--start", "--start-time", dest="start_time", type=float, default=30.0, help="Scene start time in seconds")
    vision_parser.add_argument("--end", "--end-time", dest="end_time", type=float, default=40.0, help="Scene end time in seconds")
    vision_parser.add_argument("--frames", type=int, default=5, help="Maximum frames to extract")
    vision_parser.add_argument("--width", type=int, default=512, help="Extracted frame width")
    vision_parser.add_argument("--height", type=int, default=288, help="Extracted frame height")
    vision_parser.add_argument("--output-dir", default="work/vision_test", help="Directory for frames and result.json")
    vision_parser.add_argument("--timeout", type=float, default=120.0, help="Ollama request timeout in seconds")

    scan_parser = subparsers.add_parser("vision-scan", help="Run a sequential coarse Ollama Vision scan")
    scan_parser.add_argument("source", help="Path to the input video")
    scan_parser.add_argument("--window", type=float, default=15.0, help="Window size in seconds")
    scan_parser.add_argument("--frames", type=int, default=5, help="Maximum frames per window")
    scan_parser.add_argument("--width", type=int, default=512, help="Extracted frame width")
    scan_parser.add_argument("--height", type=int, default=288, help="Extracted frame height")
    scan_parser.add_argument("--max-windows", type=int, default=None, help="Limit scan to the first N windows")
    scan_parser.add_argument("--prefilter", action="store_true", help="Run cheap candidate prefilter before Ollama")
    scan_parser.add_argument("--threshold", type=float, default=0.4, help="Prefilter candidate threshold")
    scan_parser.add_argument("--output-dir", default=None, help="Directory for scan.json and extracted frames")
    scan_parser.add_argument("--timeout", type=float, default=120.0, help="Ollama request timeout in seconds")

    all_parser = subparsers.add_parser("all", help="Run the full pipeline for a source video")
    all_parser.add_argument("source", help="Path to the input video")
    all_parser.add_argument("--profile", default=str(DEFAULT_PROFILE), help="Path to a custom game profile")
    all_parser.add_argument(
        "--aspect", choices=sorted(ASPECT_RATIO_PRESETS), default=None, help="Output aspect ratio preset (default: source aspect)"
    )
    all_parser.add_argument("--subtitles", action="store_true", help="Burn in subtitles generated from the speech transcript")

    prefilter_parser = subparsers.add_parser("prefilter", help="Run cheap visual/audio candidate prefilter")
    prefilter_parser.add_argument("source", help="Path to the input video")
    prefilter_parser.add_argument("--window", type=float, default=15.0, help="Window size in seconds")
    prefilter_parser.add_argument("--threshold", type=float, default=0.4, help="Candidate score threshold")
    prefilter_parser.add_argument("--max-windows", type=int, default=None, help="Limit prefilter to the first N windows")

    batch_parser = subparsers.add_parser("batch", help="Plan or execute a batch of gameplay videos")
    batch_parser.add_argument("input_directory", help="Directory containing gameplay videos")
    batch_parser.add_argument("--dry-run", action="store_true", help="Discover videos and create a manifest without processing")
    batch_parser.add_argument("--clips", type=int, default=10, help="Maximum selected clips")
    batch_parser.add_argument("--window", type=float, default=15.0, help="Prefilter window size in seconds")
    batch_parser.add_argument("--prefilter-threshold", type=float, default=0.4, help="Prefilter threshold")
    batch_parser.add_argument("--style", choices=["cinematic", "tactical", "fast"], default="tactical")
    batch_parser.add_argument("--max-videos", type=int, default=None, help="Limit the number of videos processed")
    batch_parser.add_argument("--resume", action="store_true", default=True, help="Reuse completed artifacts")
    batch_parser.add_argument("--final-dir", default="output", help="Legacy compatibility directory for finished montages; canonical production output is output/<project_id>/final.mp4")
    batch_parser.add_argument("--profile", default=str(DEFAULT_PROFILE), help="Path to a custom game profile")
    batch_parser.add_argument(
        "--aspect", choices=sorted(ASPECT_RATIO_PRESETS), default=None, help="Output aspect ratio preset (default: source aspect)"
    )
    batch_parser.add_argument("--subtitles", action="store_true", help="Burn in subtitles generated from the speech transcript")

    event_parser = subparsers.add_parser("event-test", help="Convert one Vision result into Event Arcs")
    event_parser.add_argument("vision_result", help="Path to a Vision result.json")

    runtime_parser = subparsers.add_parser("runtime-status", help="Inspect the configured local Ollama runtime")
    runtime_parser.add_argument("--base-url", default="http://localhost:11434", help="Ollama base URL")
    runtime_parser.add_argument("--model", default="qwen3-vl:8b-instruct", help="Vision model to validate")

    subparsers.add_parser("system-status", help="Inspect local system and media tool readiness")

    subparsers.add_parser("desktop", help="Launch the PySide6 desktop application")

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "analyze":
            result = analyze_video(args.source, profile_path=args.profile)
            LOGGER.info("Session created: %s", result["session_dir"])
            return 0

        if args.command == "detect":
            candidates = detect_candidates(args.session, profile_path=args.profile)
            LOGGER.info("Detected %d candidates in %s", len(candidates), args.session)
            return 0

        if args.command == "select":
            selected = select_highlights_for_session(args.session, profile_path=args.profile)
            LOGGER.info("Selected %d highlights in %s", len(selected), args.session)
            return 0

        if args.command == "edit":
            result = edit_session(args.session, aspect_ratio=args.aspect, burn_subtitles=args.subtitles)
            LOGGER.info("Preview written: %s", result["preview"])
            return 0

        if args.command == "render":
            final_path = render_session(args.session)
            LOGGER.info("Final MP4 rendered: %s", final_path)
            return 0

        if args.command == "qc":
            qc = qc_session(args.session)
            LOGGER.info("QC passed: %s", qc["passed"])
            return 0

        if args.command == "benchmark-motion":
            result = benchmark_motion_video(args.source, sample_fps=args.sample_fps, motion_threshold=args.motion_threshold)
            print(json.dumps(result, indent=2))
            LOGGER.info(
                "Benchmark complete: source_fps=%.2f sampled_fps=%.2f processed_frames=%d elapsed=%.3fs effective_fps=%.2f",
                result["source_fps"],
                result["sampled_fps"],
                result["sampled_frame_count"],
                result["processing_time_seconds"],
                result["effective_processing_fps"],
            )
            return 0

        if args.command == "vision-test":
            result = run_vision_test(
                args.source,
                start_time=args.start_time,
                end_time=args.end_time,
                output_dir=args.output_dir,
                timeout_seconds=args.timeout,
                max_frames=args.frames,
                width=args.width,
                height=args.height,
            )
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "vision-scan":
            result = run_vision_scan(
                args.source,
                window_size=args.window,
                max_frames=args.frames,
                width=args.width,
                height=args.height,
                max_windows=args.max_windows,
                output_dir=args.output_dir,
                timeout_seconds=args.timeout,
                use_prefilter=args.prefilter,
                prefilter_threshold=args.threshold,
            )
            LOGGER.info(
                "Vision scan complete: windows=%d candidates=%d total=%.2fs avg/window=%.2fs",
                result["total_windows"],
                len(result["candidates"]),
                result["total_processing_time_seconds"],
                result["average_time_per_window_seconds"],
            )
            print(json.dumps({
                "scan_path": result["scan_path"],
                "session_dir": result["session_dir"],
                "total_windows": result["total_windows"],
                "total_processing_time_seconds": result["total_processing_time_seconds"],
                "average_time_per_window_seconds": result["average_time_per_window_seconds"],
                "candidate_count": len(result["candidates"]),
                "top_10_candidates": result["candidates"][:10],
            }, indent=2))
            return 0

        if args.command == "prefilter":
            result = run_prefilter(
                args.source,
                window_size=args.window,
                threshold=args.threshold,
                max_windows=args.max_windows,
            )
            print(json.dumps({
                "result_path": result["result_path"],
                "session_dir": result["session_dir"],
                "total_windows": result["total_windows"],
                "candidate_count": len(result["candidates"]),
                "processing_time_seconds": result["processing_time_seconds"],
                "ffmpeg_diagnostics": result["ffmpeg_diagnostics"],
                "window_diagnostics": result["window_diagnostics"],
                "top_candidates": result["candidates"][:10],
            }, indent=2))
            return 0

        if args.command == "all":
            result = run_all_pipeline(args.source, profile_path=args.profile, aspect_ratio=args.aspect, burn_subtitles=args.subtitles)
            if result.get("status") == "NO_HIGHLIGHTS":
                LOGGER.info("No significant highlights found. Session: %s", result["session_dir"])
            else:
                LOGGER.info("Pipeline completed: %s", result.get("final_path"))
            return 0 if result.get("status") in {"SUCCESS", "NO_HIGHLIGHTS"} else 1

        if args.command == "batch":
            result = run_batch(
                args.input_directory,
                dry_run=args.dry_run,
                clips=args.clips,
                window_size=args.window,
                prefilter_threshold=args.prefilter_threshold,
                style=args.style,
                max_videos=args.max_videos,
                resume=args.resume,
                final_dir=args.final_dir,
                profile_path=args.profile,
                aspect_ratio=args.aspect,
                burn_subtitles=args.subtitles,
            )
            print(f"Found videos: {result['video_count']}")
            print(f"Total duration: {result['total_duration']:.3f}s")
            print(f"Batch manifest: {result['manifest_path']}")
            if not args.dry_run:
                summary = result.get("production_summary", {})
                print(f"Selected clips: {summary.get('selected_clips', 0)}")
                print(f"Montage: {result.get('montage_path')}")
                print(f"QC passed: {result.get('qc', {}).get('passed')}")
            for index, video in enumerate(result["videos"], start=1):
                print(f"[{index}/{result['video_count']}] {video['filename']} duration={video['duration']:.3f}s")
            return 0

        if args.command == "event-test":
            result = run_event_test(args.vision_result)
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "runtime-status":
            snapshot = OllamaRuntimeManager(base_url=args.base_url, model=args.model).detect()
            print(json.dumps(snapshot.as_dict(), indent=2))
            return 0 if snapshot.state not in {"ERROR", "NOT_INSTALLED"} else 1

        if args.command == "system-status":
            result = collect_system_diagnostics()
            print(json.dumps(result, indent=2))
            return 0 if result["ready"] else 1

        if args.command == "desktop":
            from game_ai_editor.desktop.app import run_desktop_app

            return run_desktop_app()

        parser.error(f"Unsupported command: {args.command}")
        return 2
    except Exception as exc:  # pragma: no cover - CLI error path
        LOGGER.exception("Game AI Editor failed")
        print(f"ERROR: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
