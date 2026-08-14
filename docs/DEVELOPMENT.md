# Development

Install Python dependencies and PySide6 with `pip install -r requirements.txt`. Keep media, frames, model files, `work/`, caches, previews, and rendered outputs out of Git.

Fast validation:

```powershell
pytest -q
python -m game_ai_editor.cli --help
python -m game_ai_editor.cli desktop --help
```

The synthetic orchestration E2E uses a mock Vision provider. A real Ollama smoke test is a separate, explicit operation and should use a short video only.