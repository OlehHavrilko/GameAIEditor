"""PyInstaller entry point; do not import relatively."""

from game_ai_editor.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
