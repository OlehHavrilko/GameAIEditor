"""Manual-only smoke test; run directly when a local Ollama instance is available."""

import pytest

pytestmark = pytest.mark.skip(reason="manual-only: requires a real local Ollama runtime")


def test_real_ollama_smoke() -> None:
    pytest.fail("Run this test explicitly after removing the skip marker locally.")
