from __future__ import annotations

from game_ai_editor.runtime import OllamaRuntimeManager, RuntimeState


def test_runtime_detects_not_installed(monkeypatch) -> None:
    manager = OllamaRuntimeManager(model="qwen3-vl:8b-instruct")
    monkeypatch.setattr("game_ai_editor.runtime.shutil.which", lambda name: None)
    monkeypatch.setattr("game_ai_editor.runtime._http_json", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))

    snapshot = manager.detect()

    assert snapshot.state == RuntimeState.NOT_INSTALLED
    assert snapshot.installed is False
    assert snapshot.healthy is False


def test_runtime_detects_external_instance_with_model(monkeypatch) -> None:
    manager = OllamaRuntimeManager(model="qwen3-vl:8b-instruct")
    monkeypatch.setattr("game_ai_editor.runtime.shutil.which", lambda name: "/usr/bin/ollama")
    monkeypatch.setattr(
        "game_ai_editor.runtime._http_json",
        lambda *args, **kwargs: {"models": [{"name": "qwen3-vl:8b-instruct"}]},
    )

    snapshot = manager.detect()

    assert snapshot.state == RuntimeState.EXTERNAL_INSTANCE
    assert snapshot.externally_managed is True
    assert snapshot.model_available is True


def test_runtime_detects_missing_model_on_running_instance(monkeypatch) -> None:
    manager = OllamaRuntimeManager(model="missing-model")
    monkeypatch.setattr("game_ai_editor.runtime.shutil.which", lambda name: "/usr/bin/ollama")
    monkeypatch.setattr(
        "game_ai_editor.runtime._http_json",
        lambda *args, **kwargs: {"models": [{"name": "qwen3-vl:8b-instruct"}]},
    )

    snapshot = manager.detect()

    assert snapshot.state == RuntimeState.MODEL_MISSING
    assert snapshot.healthy is True
    assert snapshot.model_available is False