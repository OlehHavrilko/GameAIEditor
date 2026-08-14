from __future__ import annotations

import json
from pathlib import Path

from .models import GameProfile


def load_game_profile(path: str | Path) -> GameProfile:
    profile_path = Path(path)
    if not profile_path.exists():
        raise FileNotFoundError(f"Game profile not found: {profile_path}")

    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    return GameProfile.model_validate(payload)
