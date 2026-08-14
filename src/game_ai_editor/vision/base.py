from __future__ import annotations

from abc import ABC, abstractmethod

from .models import VisionRequest, VisionResult


class VisionProvider(ABC):
    @abstractmethod
    def analyze(self, request: VisionRequest) -> VisionResult:
        raise NotImplementedError
