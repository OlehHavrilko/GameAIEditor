# Contributing

## Development setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Install PyInstaller only when packaging:

```powershell
python -m pip install pyinstaller
```

## Validation

Before opening a pull request:

```powershell
.venv\Scripts\pytest -q
.venv\Scripts\python.exe -c "from game_ai_editor.desktop.app import MainWindow; print('ui-import-ok')"
.venv\Scripts\python.exe -m game_ai_editor system-status
.venv\Scripts\python.exe -m game_ai_editor runtime-status
```

Tests use synthetic media and mocked Vision providers. They do not require Ollama or internet access. The real Ollama smoke test is manual-only.

## Change boundaries

- Keep `ProductionOrchestrator` as the single production pipeline.
- Keep scoring, selection, timeline planning, rendering, and QC in their existing modules.
- Do not commit media, model files, generated sessions, or local secrets.
- Do not store API keys in JSON artifacts, logs, or queue files.
- Add tests for behavior changes and preserve existing CLI commands.

## Pull requests

Describe the user-visible behavior, affected pipeline stage, validation commands, and any known runtime limitations. Keep unrelated formatting and generated files out of the change.
