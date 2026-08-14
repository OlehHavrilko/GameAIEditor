from __future__ import annotations

ARMA_REFORGER_PROMPT = """You are analyzing a short Arma Reforger gameplay scene.

All supplied images are chronological frames from one scene. Use the complete sequence,
not a single frame. Return ONLY valid JSON, with no Markdown fences and no additional text.

Use exactly this JSON shape:
{
  "scene_type": "firefight|enemy_contact|explosion|vehicle|movement|objective|other",
  "highlight": true,
  "highlight_score": 0,
  "confidence": 0.0,
  "player_visible": true,
  "enemy_visible": true,
  "weapon_visible": true,
  "muzzle_flash": false,
  "explosion_visible": false,
  "multiple_enemies": false,
  "vehicle_visible": false,
  "events": [
    {
      "event_type": "firefight|enemy_contact|shooting|kill|hit|suppression|ambush|explosion|grenade|vehicle_explosion|vehicle|vehicle_combat|injury|death|capture|objective|unusual_event|intense_action|other",
      "confidence": 0.0,
      "intensity": 0.0,
      "description": "short evidence-based description"
    }
  ],
  "entities": ["player", "enemy infantry", "rifle"],
  "description": "short scene summary"
}

Rules:
- highlight_score is a number from 0 to 100.
- Score 0-20 for ordinary walking, waiting, or calm scenes.
- Score 21-40 for an interesting environment without active action.
- Score 41-60 for enemy contact or preparation for combat.
- Score 61-80 for active firefight or intense action.
- Score 81-100 for a visually supported kill, multiple kills, explosion, or exceptional event.
- confidence and every event confidence/intensity must be from 0 to 1.
- Do not claim a kill, muzzle flash, injury, or explosion without visual evidence.
- Normal walking, empty views, inventory, maps, and routine driving should normally be low-score.
- Frames are chronological observations of one scene. Explain meaningful changes across
  frame 1 through frame 5; do not treat them as five independent scenes.
- Describe uncertainty instead of inventing details.
"""

COARSE_SCAN_PROMPT = """You are performing a coarse highlight scan of one Arma Reforger
gameplay window. The supplied images are chronological frames from the same window:
frame 1 -> frame 2 -> frame 3 -> frame 4 -> frame 5. Analyze changes across the
sequence, not five independent images.

Return ONLY one valid JSON object. Do not use Markdown fences and do not add fields.
Use exactly this shape:
{
  "scene_type": "firefight|enemy_contact|explosion|vehicle|movement|objective|other",
  "highlight": false,
  "highlight_score": 0,
  "confidence": 0.0,
  "player_visible": false,
  "enemy_visible": false,
  "weapon_visible": false,
  "muzzle_flash": false,
  "explosion_visible": false,
  "multiple_enemies": false,
  "vehicle_visible": false,
  "events": [
    {
      "event_type": "firefight|enemy_contact|shooting|kill|hit|suppression|ambush|explosion|grenade|vehicle_explosion|vehicle|vehicle_combat|injury|death|capture|objective|unusual_event|intense_action|other",
      "confidence": 0.0,
      "intensity": 0.0,
      "description": "brief evidence-based description"
    }
  ],
  "entities": [],
  "description": "brief description of the complete window"
}

Use this score scale:
- 0-20: ordinary walking, running, waiting, map/inventory, or calm movement.
- 21-40: interesting environment or preparation without active combat.
- 41-60: enemy contact, detection, or preparation for combat.
- 61-80: active firefight, shooting, suppression, or intense action.
- 81-100: visually supported kill, multiple enemies/kills, explosion, vehicle combat,
  or an unusually intense event.

Only report visually supported events. Calm movement must not receive a high score.
"""
