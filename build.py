#!/usr/bin/env python3
"""Build the Mozikit Desktop Windows directory distribution.

The PyInstaller spec contains the multi-program ``MERGE``/``COLLECT`` graph.
This module owns the reproducible version, snapshot, artifact, and smoke-test
steps around that spec.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
SPEC_PATH = ROOT_DIR / "Mozikit.spec"
PYINSTALLER_WORKPATH = ROOT_DIR / "build" / "pyinstaller"
BUNDLED_UV_PATH = ROOT_DIR / "build" / "bundled_uv" / "uv.exe"
DIST_PATH = ROOT_DIR / "dist" / "Mozikit"


def _read_project_version() -> str:
    project_file = ROOT_DIR / "pyproject.toml"
    match = re.search(
        r"^\s*version\s*=\s*[\"']([^\"']+)[\"']",
        project_file.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if not match:
        raise RuntimeError("pyproject.toml does not define project.version")
    return match.group(1)


def get_version_from_git() -> str:
    """Resolve a release version without ever using a commit SHA as a version."""
    env_version = os.environ.get("MOZIKIT_VERSION", "").strip()
    if env_version:
        return env_version.lstrip("v")

    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--exact-match", "--match", "v*"],
            capture_output=True,
            text=True,
            cwd=ROOT_DIR,
            check=False,
        )
        if result.returncode == 0:
            version = result.stdout.strip().lstrip("v")
            if re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
                return version
    except OSError:
        pass
    return _read_project_version()


def generate_version_file(version: str | None = None) -> str:
    """Write the version embedded in both frozen launchers."""
    version = version or get_version_from_git()
    version_file = ROOT_DIR / "src" / "core" / "_version.py"
    version_file.write_text(
        "# Auto-generated version file\n"
        "# Do not edit manually\n"
        f'__version__ = "{version}"\n',
        encoding="utf-8",
    )
    print(f"[OK] Version resolved: {version}")
    return version


def check_requirements() -> None:
    """Check build-only dependencies in the normal Python build environment."""
    print("Checking build dependencies...")
    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("PyInstaller is required; install it in the build environment") from exc
    try:
        import PIL  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("Pillow is required; install it in the build environment") from exc
    try:
        import PySide6  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("PySide6 is required for the Desktop build; install the [gui] extra") from exc
    print("[OK] PyInstaller, Pillow, and PySide6 are available")


def sync_official_nodes_snapshot() -> bool:
    """Refresh the bundled official-node snapshot before packaging."""
    script = ROOT_DIR / "tools" / "sync_official_nodes.py"
    if not script.exists():
        print(f"[ERROR] Official-node sync script is missing: {script}")
        return False
    try:
        subprocess.check_call([sys.executable, str(script)], cwd=ROOT_DIR)
        print("[OK] Official nodes snapshot synced")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"[ERROR] Official-node snapshot sync failed: {exc}")
        return False


def create_spec_file() -> Path:
    """Validate the checked-in shared multi-executable spec."""
    if not SPEC_PATH.exists():
        raise FileNotFoundError(f"Missing PyInstaller spec: {SPEC_PATH}")
    if not BUNDLED_UV_PATH.is_file():
        raise FileNotFoundError(
            f"Bundled UV is missing: {BUNDLED_UV_PATH}. "
            "Run scripts/download_uv.ps1 before building."
        )
    print(f"[OK] Using shared PyInstaller spec: {SPEC_PATH}")
    return SPEC_PATH


def clean_build() -> None:
    """Remove generated build outputs without deleting the downloaded UV."""
    for path in (PYINSTALLER_WORKPATH, ROOT_DIR / "dist", ROOT_DIR / "Mozikit_dir"):
        if path.exists():
            shutil.rmtree(path)
            print(f"  - Deleted {path.relative_to(ROOT_DIR)}")


def build_executable() -> bool:
    """Build the shared directory distribution from ``Mozikit.spec``."""
    try:
        # The generated module is copied into the shared COLLECT tree by the
        # spec.  Generate it here as well as from the higher-level build
        # scripts so direct ``build.build_executable()`` calls are reproducible.
        generate_version_file()
        create_spec_file()
        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            "--workpath",
            str(PYINSTALLER_WORKPATH),
            "--distpath",
            str(ROOT_DIR / "dist"),
            str(SPEC_PATH),
        ]
        subprocess.check_call(command, cwd=ROOT_DIR)
        normalize_distribution_layout()
        print("[OK] PyInstaller build completed")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, RuntimeError) as exc:
        print(f"[ERROR] Build failed: {exc}")
        return False


def normalize_distribution_layout() -> None:
    """Promote user-visible resources out of PyInstaller's ``_internal``.

    PyInstaller 6 puts collected binaries/data below ``_internal`` by
    default.  Mozikit's public directory contract keeps UV, assets, and the
    official-node snapshot beside the launchers, while Python modules remain
    in ``_internal``.
    """
    internal_dir = DIST_PATH / "_internal"
    if not internal_dir.is_dir():
        raise FileNotFoundError(f"PyInstaller internal directory missing: {internal_dir}")
    for name in ("runtime", "official_nodes", "assets", "examples"):
        source = internal_dir / name
        destination = DIST_PATH / name
        if source.exists():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.move(str(source), str(destination))

    version_source = internal_dir / "_version.py"
    version_destination = DIST_PATH / "_version.py"
    if version_source.exists():
        if version_destination.exists():
            version_destination.unlink()
        shutil.move(str(version_source), str(version_destination))


def _run_smoke(executable: Path, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    creationflags = 0x08000000 if os.name == "nt" else 0
    return subprocess.run(
        [str(executable), *args],
        cwd=executable.parent,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        creationflags=creationflags,
        check=False,
    )


def verify_build(run_smoke: bool = True) -> bool:
    """Verify layout and the non-GUI frozen CLI contract."""
    if not DIST_PATH.is_dir():
        print(f"[ERROR] Distribution directory not found: {DIST_PATH}")
        return False

    required = [
        DIST_PATH / "MozikitDesktop.exe",
        DIST_PATH / "mozikit.exe",
        DIST_PATH / "runtime" / "uv.exe",
        DIST_PATH / "_internal",
        DIST_PATH / "official_nodes" / "manifest.json",
        DIST_PATH / "_version.py",
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        for path in missing:
            print(f"[ERROR] Required distribution entry missing: {path}")
        return False

    if not run_smoke:
        print(f"[OK] Directory distribution found: {DIST_PATH}")
        return True

    with tempfile.TemporaryDirectory(prefix="mozikit-build-smoke-") as temp_dir:
        temp_root = Path(temp_dir)
        env = os.environ.copy()
        env["MOZIKIT_APP_DATA_DIR"] = str(temp_root / "appdata")
        env["MOZIKIT_WORKSPACE"] = str(temp_root / "workflows")
        env["PYTHONIOENCODING"] = "utf-8"

        expected_version = get_version_from_git()
        version_result = _run_smoke(DIST_PATH / "mozikit.exe", ["--version"], env)
        if version_result.returncode != 0 or f"v{expected_version}" not in version_result.stdout:
            print(
                "[ERROR] CLI version smoke test failed: "
                f"expected v{expected_version}, got {version_result.stdout!r}; "
                f"{version_result.stderr or ''}"
            )
            return False

        for args in (["--help"],):
            result = _run_smoke(DIST_PATH / "mozikit.exe", list(args), env)
            if result.returncode != 0:
                print(f"[ERROR] CLI smoke test failed ({args}): {result.stderr or result.stdout}")
                return False
        uv_result = _run_smoke(DIST_PATH / "runtime" / "uv.exe", ["--version"], env)
        if uv_result.returncode != 0:
            print(f"[ERROR] Bundled UV smoke test failed: {uv_result.stderr or uv_result.stdout}")
            return False

    print(f"[OK] Frozen CLI and bundled UV smoke tests passed: {DIST_PATH}")
    return True


def create_release_package() -> Path:
    """Create the stable portable ZIP containing the top-level Mozikit dir."""
    source_dir = DIST_PATH
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Source directory not found: {source_dir}")
    release_dir = ROOT_DIR / "release"
    release_dir.mkdir(parents=True, exist_ok=True)
    zip_path = release_dir / "Mozikit-Windows-x64.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in source_dir.rglob("*"):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(source_dir.parent))
    print(f"[OK] Portable ZIP created: {zip_path}")
    return zip_path


def create_portable_package() -> Path:
    """Create a local convenience copy without PATH or Start Menu changes."""
    source_dir = DIST_PATH
    portable_dir = ROOT_DIR / "dist" / "Mozikit_Portable"
    if portable_dir.exists():
        shutil.rmtree(portable_dir)
    shutil.copytree(source_dir, portable_dir)
    if os.name == "nt":
        (portable_dir / "Start_Mozikit.cmd").write_text(
            '@echo off\r\n"%~dp0MozikitDesktop.exe"\r\n',
            encoding="ascii",
        )
    print(f"[OK] Portable convenience directory created: {portable_dir}")
    return portable_dir


def main() -> None:
    print("=" * 60)
    print("Mozikit Desktop Windows Build")
    print("=" * 60)
    if not (ROOT_DIR / "pyproject.toml").exists():
        raise SystemExit("Please run this script from the Mozikit project checkout")

    try:
        check_requirements()
        generate_version_file()
        if not sync_official_nodes_snapshot() and not (ROOT_DIR / "official_nodes" / "manifest.json").exists():
            raise RuntimeError("Official nodes snapshot is required for a Desktop release")
        clean = input("\nClean generated build outputs? (y/N): ").lower().startswith("y")
        if clean:
            clean_build()
        create_spec_file()
        if not build_executable() or not verify_build():
            raise SystemExit(1)
        create_release_package()
        create_portable_package()
    except KeyboardInterrupt:
        print("\n[INFO] Build cancelled")
        raise SystemExit(1)
    except Exception as exc:
        print(f"\n[ERROR] Build failed: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
