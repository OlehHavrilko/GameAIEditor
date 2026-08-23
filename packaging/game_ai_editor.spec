# PyInstaller configuration for the desktop MVP.
from pathlib import Path
import shutil

project_root = Path(SPECPATH).parent

analysis = Analysis(
    [str(project_root / "packaging" / "entrypoint.py")],
    pathex=[str(project_root / "src")],
    datas=[
        (str(project_root / "config"), "config"),
        (
            str(project_root / ".venv" / "Lib" / "site-packages" / "faster_whisper" / "assets"),
            "faster_whisper/assets",
        ),
    ],
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "game_ai_editor.desktop.app",
        "game_ai_editor.desktop.errors",
        "game_ai_editor.diagnostics",
        "game_ai_editor.orchestration.session",
        "game_ai_editor.orchestration.orchestrator",
    ],
    excludes=[
        "pytest",
        "_pytest",
        "torch",
        "torchvision",
        "torchgen",
        "functorch",
        "IPython",
        "jupyter",
        "notebook",
        "matplotlib",
        "tensorboard",
        "mypy",
        "setuptools._vendor.mypy",
    ],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, name="game_ai_editor", console=False)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    name="game_ai_editor",
)

# Post-build cleanup: remove debug symbols and known heavy optional artifacts.
dist_internal = project_root / "dist" / "game_ai_editor" / "_internal"
if dist_internal.exists():
    for pattern in ("**/*.lib", "**/*.pdb", "**/*.a", "**/__pycache__", "**/*_test.py"):
        for path in dist_internal.glob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
