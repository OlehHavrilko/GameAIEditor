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

Size is driven mainly by faster-whisper/CTranslate2, OpenCV and PySide6. torch is a fully optional dependency (only used by the GPU diagnostics readout) and is excluded from the build entirely, along with pytest, test internals and several other dev-only packages, so the bundle is well under the ~900 MB-1 GB figure torch alone used to add; post-build cleanup removes debug symbols.

For a final GUI-only release change `console=True` to `console=False` in `packaging/game_ai_editor.spec` and rebuild; this hides the console window when the desktop app starts, but CLI output may not be visible.

Known hidden-import candidates to add if the build fails at runtime: `PySide6.QtCore`, `PySide6.QtGui`, `PySide6.QtWidgets`, `game_ai_editor.desktop.app`, `game_ai_editor.desktop.errors`, `game_ai_editor.diagnostics`, `game_ai_editor.orchestration.session`, `game_ai_editor.orchestration.orchestrator`.

FFmpeg and FFprobe are external runtime dependencies. Distribute compatible binaries beside the packaged executable or document their installation and ensure they are available on `PATH`; the application does not embed or download them automatically.

Ollama remains an external local runtime. The package detects it and supports degraded mode when it is absent. Docker is not the primary desktop runtime.

PyInstaller is optional for normal development and is intentionally not a project dependency.
