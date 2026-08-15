from __future__ import annotations

from game_ai_editor.diagnostics import collect_system_diagnostics


def test_system_diagnostics_has_structured_checks(monkeypatch) -> None:
    monkeypatch.setattr("game_ai_editor.diagnostics.shutil.which", lambda name: "tool")
    monkeypatch.setattr(
        "game_ai_editor.diagnostics.subprocess.run",
        lambda *args, **kwargs: type("Result", (), {"returncode": 0, "stdout": "tool 1.0\n", "stderr": ""})(),
    )

    result = collect_system_diagnostics()

    names = {item["name"] for item in result["checks"]}
    assert {"OS", "Python", "FFmpeg", "FFprobe", "RAM", "GPU"}.issubset(names)