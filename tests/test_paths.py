from __future__ import annotations

import sys
from pathlib import Path

from game_ai_editor import paths


def test_data_root_defaults_to_repo_root_when_not_frozen(monkeypatch) -> None:
    monkeypatch.setattr(paths, "_override", None)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert paths.data_root() == paths._REPO_ROOT


def test_data_root_uses_executable_parent_when_frozen(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(paths, "_override", None)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    fake_exe = tmp_path / "game_ai_editor.exe"
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    assert paths.data_root() == tmp_path.resolve()


def test_set_data_root_overrides_default(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(paths, "_override", None)
    custom = tmp_path / "custom-data"
    paths.set_data_root(custom)
    try:
        assert paths.data_root() == custom.resolve()
    finally:
        paths.set_data_root(None)


def test_set_data_root_none_clears_override(monkeypatch, tmp_path: Path) -> None:
    paths.set_data_root(tmp_path / "custom-data")
    paths.set_data_root(None)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert paths.data_root() == paths._REPO_ROOT
