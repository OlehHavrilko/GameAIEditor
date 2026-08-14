from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from urllib import error, request

from pydantic import ValidationError

from .base import VisionProvider
from .models import VisionRequest, VisionResult
from .prompts import ARMA_REFORGER_PROMPT


class OllamaVisionError(RuntimeError):
    pass


class OllamaUnavailableError(OllamaVisionError):
    pass


class OllamaModelError(OllamaVisionError):
    pass


class VisionInvalidJSONError(OllamaVisionError):
    pass


class OllamaVisionProvider(VisionProvider):
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen3-vl:8b-instruct",
        timeout_seconds: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def check_available(self) -> None:
        http_request = request.Request(f"{self.base_url}/api/tags", method="GET")
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (error.URLError, TimeoutError, OSError) as exc:
            raise OllamaUnavailableError(
                f"Ollama is unavailable at {self.base_url}: {exc}"
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OllamaVisionError("Ollama returned an invalid /api/tags response.") from exc

        models = {
            str(item.get("name", ""))
            for item in payload.get("models", [])
            if isinstance(item, dict)
        }
        if self.model not in models:
            raise OllamaModelError(
                f"Ollama model '{self.model}' is not available. "
                f"Available models: {sorted(models)}"
            )

    def analyze(self, request_data: VisionRequest) -> VisionResult:
        if not request_data.frame_paths:
            raise ValueError("VisionRequest must contain at least one frame.")

        images = []
        for frame_path in request_data.frame_paths:
            path = Path(frame_path)
            if not path.exists():
                raise FileNotFoundError(f"Vision frame not found: {path}")
            images.append(base64.b64encode(path.read_bytes()).decode("ascii"))

        payload = {
            "model": self.model,
            "stream": False,
            "messages": [{
                "role": "user",
                "content": request_data.prompt or ARMA_REFORGER_PROMPT,
                "images": images,
            }],
        }
        http_request = request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                raw_response = response.read()
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 404 or "model" in body.lower():
                raise OllamaModelError(f"Ollama model/API error ({exc.code}): {body}") from exc
            raise OllamaVisionError(f"Ollama HTTP error ({exc.code}): {body}") from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise OllamaUnavailableError(f"Ollama is unavailable at {self.base_url}: {exc}") from exc

        inference_time = time.perf_counter() - started
        try:
            response_payload = json.loads(raw_response.decode("utf-8"))
            content = response_payload["message"]["content"]
        except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VisionInvalidJSONError("Ollama returned an invalid API response.") from exc

        model_payload = _parse_model_json(content)
        try:
            return VisionResult.from_model_payload(
                model_payload,
                request_data,
                provider="ollama",
                model=self.model,
                frame_dimensions=[{"width": 0, "height": 0} for _ in request_data.frame_paths],
                extraction_time_seconds=0.0,
                inference_time_seconds=round(inference_time, 4),
                total_time_seconds=round(inference_time, 4),
                response_size_bytes=len(raw_response),
            )
        except ValidationError as exc:
            raise VisionInvalidJSONError(
                f"Qwen3-VL response does not match the required JSON schema: {exc}"
            ) from exc


def _parse_model_json(content: str) -> dict:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise VisionInvalidJSONError(f"Qwen3-VL returned invalid JSON: {content[:300]}") from exc
    if not isinstance(payload, dict):
        raise VisionInvalidJSONError("Qwen3-VL JSON response must be an object.")
    return payload
