from __future__ import annotations

import sys


def get_python_executable() -> str:
    """Return the interpreter running the current Game AI Editor process."""
    return sys.executable
