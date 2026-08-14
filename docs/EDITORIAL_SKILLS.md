# Editorial Skills

Editorial behavior belongs in game/profile configuration, not in the orchestrator. A profile supplies interesting and ignored event types, scoring weights, narrative signals, and editing rules.

The existing `skills/game-highlight-editor/SKILL.md` defines the default gaming-highlights editorial intent: preserve setup, tension, contact, action, peak, and aftermath while rejecting routine movement.

Future modes such as `kills_only`, `funny_moments`, `competitive`, and `voice_reactions` should be represented as data profiles that alter weights and event preferences, while reusing the same pipeline.