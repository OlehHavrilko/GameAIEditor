from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from urllib import error, request

from pydantic import ValidationError

from .base import VisionProvider
from .models import VisionRequest, VisionResult
from .ollama import OllamaUnavailableError, OllamaVisionError, VisionInvalidJSONError
from .prompts import ARMA_REFORGER_PROMPT


class OpenAICompatibleVisionProvider(VisionProvider):
    """Vision provider for LM Studio, OpenRouter, and compatible chat APIs."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        provider_name: str = "openai-compatible",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.provider_name = provider_name

    def check_available(self) -> None:
        http_request = request.Request(f"{self.base_url}/models", method="GET")
        if self.api_key:
            http_request.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (error.URLError, TimeoutError, OSError) as exc:
            raise OllamaUnavailableError(f"Provider is unavailable at {self.base_url}: {exc}") from exc
        models = {str(item.get("id", "")) for item in payload.get("data", []) if isinstance(item, dict)}
        if models and self.model not in models:
            raise OllamaVisionError(f"Model '{self.model}' is not available. Available models: {sorted(models)}")

    def analyze(self, request_data: VisionRequest) -> VisionResult:
        if not request_data.frame_paths:
            raise ValueError("VisionRequest must contain at least one frame.")
        content: list[dict[str, object]] = [{"type": "text", "text": request_data.prompt or ARMA_REFORGER_PROMPT}]
        for frame_path in request_data.frame_paths:
            path = Path(frame_path)
            if not path.exists():
                raise FileNotFoundError(f"Vision frame not found: {path}")
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}})
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "user", "content": content}],
        }
        http_request = request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if self.api_key:
            http_request.add_header("Authorization", f"Bearer {self.api_key}")
        started = time.perf_counter()
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                raw_response = response.read()
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise OllamaVisionError(f"Provider HTTP error ({exc.code}): {body}") from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise OllamaUnavailableError(f"Provider is unavailable at {self.base_url}: {exc}") from exc
        try:
            response_payload = json.loads(raw_response.decode("utf-8"))
            content_text = response_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VisionInvalidJSONError("OpenAI-compatible provider returned an invalid response.") from exc
        try:
            model_payload = json.loads(str(content_text).strip().removeprefix("```json").removesuffix("```").strip())
            return VisionResult.from_model_payload(
                model_payload,
                request_data,
                provider=self.provider_name,
                model=self.model,
                frame_dimensions=[{"width": 0, "height": 0} for _ in request_data.frame_paths],
                extraction_time_seconds=0.0,
                inference_time_seconds=round(time.perf_counter() - started, 4),
                total_time_seconds=round(time.perf_counter() - started, 4),
                response_size_bytes=len(raw_response),
            )
        except (json.JSONDecodeError, ValidationError) as exc:
            raise VisionInvalidJSONError("Provider response does not match the required JSON schema.") from exc