"""Resolution of the root directory GameAIEditor stores input/work/output under.

Defaults to the repo root when running from source, or the directory
containing the executable when running as a PyInstaller build (`__file__`
does not point at a real on-disk location once frozen, unlike in dev).
The desktop app can override this at startup with `set_data_root()` so users
can choose where their video data lives.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_override: Path | None = None


def _default_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _REPO_ROOT


def data_root() -> Path:
    return _override if _override is not None else _default_root()


def set_data_root(path: str | Path | None) -> None:
    global _override
    _override = Path(path).resolve() if path is not None else None
