from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .state import stage_status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    job_id: str
    job_type: str = "analysis"
    status: str = "QUEUED"
    current_stage: str | None = None
    stage_progress: float = 0.0
    overall_progress: float = 0.0
    priority: int = 0
    error_code: str | None = None
    error_message: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


@dataclass
class AnalysisSession:
    session_id: str
    source_path: str
    session_dir: str
    profile_path: str
    profile_id: str
    provider: str
    model: str
    source_identity: dict[str, Any] = field(default_factory=dict)
    configuration_fingerprint: str | None = None
    status: str = "QUEUED"
    current_stage: str | None = None
    overall_progress: float = 0.0
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    errors: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    job: Job | None = None

    def refresh(self) -> "AnalysisSession":
        root = Path(self.session_dir)
        self.outputs = {}
        statuses = stage_status(root)
        complete = sum(value in {"COMPLETE", "SKIPPED"} for value in statuses.values())
        self.overall_progress = round(100.0 * complete / max(1, len(statuses)), 1)
        self.current_stage = next((name for name, value in statuses.items() if value in {"RUNNING", "PARTIAL"}), None)
        status_path = root / "status.json"
        if status_path.exists():
            try:
                payload = json.loads(status_path.read_text(encoding="utf-8"))
                self.status = str(payload.get("status", self.status))
                self.current_stage = payload.get("current_stage", self.current_stage)
                if payload.get("error_code"):
                    self.errors = [{
                        "code": payload.get("error_code"),
                        "message": payload.get("error_message", ""),
                    }]
            except (OSError, json.JSONDecodeError):
                pass
        self.updated_at = _now()
        self.artifacts = {
            stage: str(path)
            for stage, path in {
                "metadata": root / "metadata.json",
                "prefilter": root / "prefilter" / "candidates.json",
                "events": root / "events.json",
                "arcs": root / "arcs.json",
                "ranking": root / "ranking.json",
                "selection": root / "selection.json",
                "timeline": root / "timeline.json",
                "qc": root / "output" / "qc.json",
            }.items()
            if path.exists()
        }
        status_path = root / "status.json"
        public_final = None
        if status_path.exists():
            try:
                payload = json.loads(status_path.read_text(encoding="utf-8"))
                public_final = payload.get("final_output_path") or payload.get("final_path")
                public_preview = payload.get("preview_output_path") or payload.get("preview_path")
                if public_preview:
                    self.outputs["preview"] = str(public_preview)
                if public_final:
                    self.outputs["final"] = str(public_final)
                    self.outputs["montage"] = str(public_final)
            except (OSError, json.JSONDecodeError):
                pass
        return self


@dataclass
class Project:
    project_id: str
    name: str
    root_dir: str
    created_at: str = field(default_factory=_now)
    sessions: list[AnalysisSession] = field(default_factory=list)


class AnalysisQueue:
    """Persistent queue shared by the desktop app and batch execution."""

    def __init__(self, project_dir: str | Path) -> None:
        self.project_dir = Path(project_dir)
        self.queue_path = self.project_dir / "queue.json"
        self.project = Project(
            project_id=self.project_dir.name,
            name=self.project_dir.name,
            root_dir=str(self.project_dir),
        )

    @property
    def sessions(self) -> list[AnalysisSession]:
        return self.project.sessions

    def load(self) -> list[AnalysisSession]:
        if not self.queue_path.exists():
            return self.sessions
        try:
            payload = json.loads(self.queue_path.read_text(encoding="utf-8"))
            project_payload = payload.get("project", payload)
            self.project = Project(
                project_id=str(project_payload.get("project_id", self.project.project_id)),
                name=str(project_payload.get("name", self.project.name)),
                root_dir=str(project_payload.get("root_dir", self.project.root_dir)),
                created_at=str(project_payload.get("created_at", _now())),
                sessions=[self._session_from_dict(item) for item in project_payload.get("sessions", [])],
            )
        except (OSError, json.JSONDecodeError, TypeError, KeyError):
            self.project.sessions = []
        for session in self.sessions:
            session.refresh()
        self.recover_stale_sessions()
        return self.sessions

    def recover_stale_sessions(self) -> int:
        recovered = 0
        for session in self.sessions:
            if session.status == "RUNNING" or (session.job and session.job.status == "RUNNING"):
                session.status = "RECOVERABLE"
                session.current_stage = session.current_stage or (session.job.current_stage if session.job else None)
                if session.job:
                    session.job.status = "RECOVERABLE"
                recovered += 1
        if recovered:
            self.save()
        return recovered

    def save(self) -> None:
        self.project_dir.mkdir(parents=True, exist_ok=True)
        for session in self.sessions:
            session.refresh()
        payload = {"version": 1, "project": asdict(self.project), "updated_at": _now()}
        temporary = self.queue_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        temporary.replace(self.queue_path)

    def add(
        self,
        video_path: str | Path,
        session_dir: str | Path,
        *,
        profile_path: str | Path = "config/games/arma_reforger.json",
        profile_id: str = "arma_reforger",
        provider: str = "ollama",
        model: str = "qwen3-vl:8b-instruct",
        priority: int = 0,
    ) -> AnalysisSession:
        source = Path(video_path).resolve()
        directory = Path(session_dir)
        existing = next((item for item in self.sessions if item.source_path == str(source)), None)
        if existing:
            return existing
        session = AnalysisSession(
            session_id=f"{source.stem}_{uuid.uuid4().hex[:8]}",
            source_path=str(source),
            session_dir=str(directory),
            profile_path=str(profile_path),
            profile_id=profile_id,
            provider=provider,
            model=model,
            job=Job(job_id=uuid.uuid4().hex, priority=priority),
        )
        self.sessions.append(session)
        self.save()
        return session

    def get(self, session_id: str) -> AnalysisSession | None:
        return next((item for item in self.sessions if item.session_id == session_id), None)

    def mark_running(self, session_id: str, stage: str | None = None) -> None:
        session = self._require(session_id)
        session.status = "RUNNING"
        session.current_stage = stage
        if session.job:
            session.job.status = "RUNNING"
            session.job.current_stage = stage
            session.job.updated_at = _now()
        self.save()

    def mark_completed(self, session_id: str, status: str = "SUCCESS") -> None:
        session = self._require(session_id)
        session.status = status
        if session.job:
            session.job.status = "COMPLETED" if status in {"SUCCESS", "NO_HIGHLIGHTS"} else status
            session.job.updated_at = _now()
        self.save()

    def mark_failed(self, session_id: str, error_code: str, error_message: str) -> None:
        session = self._require(session_id)
        session.status = "FAILED"
        session.errors.append({"code": error_code, "message": error_message})
        if session.job:
            session.job.status = "FAILED"
            session.job.error_code = error_code
            session.job.error_message = error_message
            session.job.updated_at = _now()
        self.save()

    def pause(self, session_id: str) -> None:
        session = self._require(session_id)
        session.status = "PAUSED"
        if session.job:
            session.job.status = "PAUSED"
        self.save()

    def resume(self, session_id: str) -> None:
        session = self._require(session_id)
        session.status = "QUEUED"
        if session.job:
            session.job.status = "QUEUED"
            session.job.error_code = None
            session.job.error_message = None
        self.save()

    def cancel(self, session_id: str) -> None:
        session = self._require(session_id)
        session.status = "CANCELLED"
        if session.job:
            session.job.status = "CANCELLED"
        self.save()

    def retry(self, session_id: str) -> None:
        session = self._require(session_id)
        session.status = "QUEUED"
        session.errors.clear()
        if session.job:
            session.job.status = "QUEUED"
            session.job.error_code = None
            session.job.error_message = None
        self.save()

    def _require(self, session_id: str) -> AnalysisSession:
        session = self.get(session_id)
        if session is None:
            raise KeyError(f"Unknown analysis session: {session_id}")
        return session

    @staticmethod
    def _session_from_dict(payload: dict[str, Any]) -> AnalysisSession:
        job_payload = payload.pop("job", None)
        job = Job(**job_payload) if isinstance(job_payload, dict) else None
        return AnalysisSession(**{key: value for key, value in payload.items() if key in AnalysisSession.__dataclass_fields__}, job=job)