"""Shared identity contract for Runtime Daemon clients and servers."""

import hashlib
from pathlib import Path

from src.core import __version__

RUNTIME_PROTOCOL_VERSION = 1


def desired_state_fingerprint(runtime_dir: Path) -> str:
    """Hash runtime configuration and plugin contents in a stable order."""
    candidates = [runtime_dir / "runtimes.json"]
    plugin_root = runtime_dir / "plugins"
    if plugin_root.is_dir():
        candidates.extend(
            path
            for path in plugin_root.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        )
    digest = hashlib.sha256()
    for path in sorted(candidates, key=lambda item: str(item)):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(runtime_dir)
        except ValueError:
            relative = path
        digest.update(str(relative).replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def expected_identity(runtime_dir: Path) -> dict:
    from src.core import resolve_workspace

    return {
        "protocol_version": RUNTIME_PROTOCOL_VERSION,
        "mozikit_version": __version__,
        "desired_state_fingerprint": desired_state_fingerprint(runtime_dir),
        "workspace": str(resolve_workspace().resolve()),
    }
