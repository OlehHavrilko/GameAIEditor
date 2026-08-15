# Desktop packaging

The first packaging target is PyInstaller. Install it in the project environment before building:

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
.venv\Scripts\python.exe -m PyInstaller packaging\game_ai_editor.spec
```

The spec produces a one-directory bundle under `dist/game_ai_editor/`. The dedicated entry point `packaging/entrypoint.py` avoids relative-import issues in the frozen executable.

After a successful build, validate the executable with:

```powershell
dist\game_ai_editor\game_ai_editor.exe system-status
dist\game_ai_editor\game_ai_editor.exe runtime-status
```

Expected size is roughly 900 MB–1 GB because of torch, faster-whisper, opencv and PySide6. The spec already excludes pytest, test internals, unused torchvision datasets/models and several dev-only packages; post-build cleanup removes debug symbols.

For a final GUI-only release change `console=True` to `console=False` in `packaging/game_ai_editor.spec` and rebuild; this hides the console window when the desktop app starts, but CLI output may not be visible.

Known hidden-import candidates to add if the build fails at runtime: `PySide6.QtCore`, `PySide6.QtGui`, `PySide6.QtWidgets`, `game_ai_editor.desktop.app`, `game_ai_editor.desktop.errors`, `game_ai_editor.diagnostics`, `game_ai_editor.orchestration.session`, `game_ai_editor.orchestration.orchestrator`.

FFmpeg and FFprobe are external runtime dependencies. Distribute compatible binaries beside the packaged executable or document their installation and ensure they are available on `PATH`; the application does not embed or download them automatically.

Ollama remains an external local runtime. The package detects it and supports degraded mode when it is absent. Docker is not the primary desktop runtime.

PyInstaller is optional for normal development and is intentionally not a project dependency.
