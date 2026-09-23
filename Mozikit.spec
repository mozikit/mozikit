# -*- mode: python ; coding: utf-8 -*-

"""Mozikit Desktop multi-program PyInstaller distribution.

The GUI and console launchers are analyzed independently, then MERGE places
common Python modules and native libraries in the first analysis.  COLLECT
finally emits one directory with both launchers and one shared _internal
directory.  The bundled UV executable is deliberately an external binary at
runtime/uv.exe, not a Python package install.
"""

from pathlib import Path


ROOT_DIR = Path(SPECPATH).resolve()
ASSETS_DIR = ROOT_DIR / "assets"
ICON_PATH = ASSETS_DIR / "mozikit.ico"
BUNDLED_UV_PATH = ROOT_DIR / "build" / "bundled_uv" / "uv.exe"

if not ICON_PATH.exists():
    raise FileNotFoundError(f"Missing required Windows icon: {ICON_PATH}")
if not BUNDLED_UV_PATH.exists():
    raise FileNotFoundError(
        f"Missing bundled UV: {BUNDLED_UV_PATH}. Run scripts/download_uv.ps1 first."
    )


datas = [
    (str(ASSETS_DIR / "mozikit.ico"), "assets"),
    (str(ASSETS_DIR / "mozikit_64.png"), "assets"),
    (str(ASSETS_DIR / "icons"), "assets/icons"),
    (str(ROOT_DIR / "examples"), "examples"),
    (str(ROOT_DIR / "src" / "core" / "workflow_runner.py"), "src/core"),
    (str(ROOT_DIR / "src" / "core" / "_version.py"), "."),
    (str(ROOT_DIR / "official_nodes"), "official_nodes"),
]

hiddenimports = [
    # PySide6 modules
    "PySide6.QtCore",
    "PySide6.QtWidgets",
    "PySide6.QtGui",
    "PySide6.QtNetwork",
    # Project modules retained from the previous frozen build
    "src.main_window",
    "src.views.workflow_canvas",
    "src.views.workflow_tab_widget",
    "src.views.overview_widget",
    "src.views.node_graphics",
    "src.views.node_browser",
    "src.views.node_properties",
    "src.dialogs.settings_dialog",
    "src.core.workflow_executor",
    "src.core.uv_manager",
    "src.core.node_base",
    "src.core.node_repo_manager",
    "src.core.workflow_runner",
    "src.core.custom_node_manager",
    "src.core.ai_node_generator",
    "src.core.code_safety",
    "src.core.github_oauth",
    "src.core.credential_store",
    "src.core.node_version_manager",
    "src.core.providers.github_provider",
    # Runtime dependencies used through dynamic imports
    "json",
    "pathlib",
    "shutil",
    "time",
    "math",
]

common_analysis = dict(
    pathex=[str(ROOT_DIR)],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "scipy",
        "pandas",
        "IPython",
    ],
    noarchive=False,
)

# Keep immutable distribution resources in the first analysis so COLLECT has
# one copy.  MERGE shares common Python modules/native DLLs with the CLI.
gui_a = Analysis(
    [str(ROOT_DIR / "src" / "gui_launcher.py")],
    binaries=[(str(BUNDLED_UV_PATH), "runtime")],
    datas=datas,
    **common_analysis,
)
cli_a = Analysis(
    [str(ROOT_DIR / "src" / "cli_launcher.py")],
    binaries=[],
    datas=[],
    **common_analysis,
)

MERGE(
    (gui_a, "gui_launcher", "MozikitDesktop"),
    (cli_a, "cli_launcher", "mozikit"),
)

gui_pyz = PYZ(gui_a.pure)
cli_pyz = PYZ(cli_a.pure)

gui_exe = EXE(
    gui_pyz,
    gui_a.dependencies,
    gui_a.scripts,
    exclude_binaries=True,
    name="MozikitDesktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_PATH),
)

cli_exe = EXE(
    cli_pyz,
    cli_a.dependencies,
    cli_a.scripts,
    exclude_binaries=True,
    name="mozikit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_PATH),
)

coll = COLLECT(
    gui_exe,
    cli_exe,
    gui_a.binaries,
    gui_a.datas,
    cli_a.binaries,
    cli_a.datas,
    strip=False,
    upx=False,
    name="Mozikit",
)
