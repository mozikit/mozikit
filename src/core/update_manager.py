"""Mozikit Desktop update discovery and installer handoff.

The updater is deliberately UI independent.  Both the CLI and the desktop
window use this module so that release selection, manifest validation,
download verification, and installation boundaries cannot drift apart.

The Windows MSI remains the owner of installed files.  A downloaded MSI is
therefore handed to ``msiexec``; the updater never writes into Program Files.
Portable distributions can discover and download a release, but must be
replaced manually because replacing a running portable directory is not a
safe operation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from src.core import runtime_paths


UPDATE_PROTOCOL_VERSION = 1
DEFAULT_REPOSITORY = "mozikit/mozikit"
DEFAULT_API_BASE = "https://api.github.com"
CHANNELS = {"stable", "nightly"}
UPDATE_STATUSES = {
    "idle",
    "up_to_date",
    "update_available",
    "downloaded",
    "pending_install",
    "blocked",
    "error",
}

_VERSION_RE = re.compile(
    r"^(?P<base>\d+\.\d+\.\d+)"
    r"(?:-nightly\.(?P<date>\d{8})\.(?P<ref>[0-9A-Za-z]+))?$"
)
_NIGHTLY_TAG_RE = re.compile(
    r"^v(?P<version>\d+\.\d+\.\d+-nightly\.\d{8}\.[0-9A-Za-z]+)$"
)
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_SOURCE_REF_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class UpdateError(RuntimeError):
    """A stable, machine-readable updater error."""

    def __init__(self, code: str, message: str, *, details: Optional[Mapping[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        result = {"code": self.code, "message": self.message}
        if self.details:
            result["details"] = self.details
        return result


@dataclass(frozen=True)
class ParsedVersion:
    base: tuple[int, int, int]
    nightly: bool
    nightly_date: Optional[int] = None
    nightly_ref: Optional[str] = None


@dataclass(frozen=True)
class UpdateAsset:
    name: str
    kind: str
    url: str
    sha256: str
    size: int
    platform: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "url": self.url,
            "sha256": self.sha256,
            "size": self.size,
        }
        if self.platform:
            result["platform"] = self.platform
        return result


@dataclass(frozen=True)
class UpdateCandidate:
    channel: str
    tag: str
    version: str
    source_ref: str
    assets: tuple[UpdateAsset, ...]
    build_sequence: Optional[int]
    published_at: Optional[str]
    release_id: Optional[int] = None

    def asset(self, kind: str) -> Optional[UpdateAsset]:
        return next((item for item in self.assets if item.kind == kind), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "tag": self.tag,
            "version": self.version,
            "source_ref": self.source_ref,
            "build_sequence": self.build_sequence,
            "published_at": self.published_at,
            "release_id": self.release_id,
            "assets": [asset.to_dict() for asset in self.assets],
        }


@dataclass(frozen=True)
class Installation:
    kind: str
    executable: Optional[str]
    install_dir: Optional[str]
    can_install: bool
    reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "executable": self.executable,
            "install_dir": self.install_dir,
            "can_install": self.can_install,
            "reason": self.reason,
        }


@dataclass
class UpdateResult:
    status: str
    channel: Optional[str]
    current_version: str
    latest_version: Optional[str] = None
    candidate: Optional[UpdateCandidate] = None
    installation: Optional[Installation] = None
    can_install: bool = False
    downloaded_path: Optional[str] = None
    error: Optional[UpdateError] = None
    message: Optional[str] = None
    checked_at: Optional[str] = None

    @property
    def available(self) -> bool:
        return self.status == "update_available"

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "available": self.available,
            "channel": self.channel,
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "can_install": self.can_install,
            "downloaded_path": self.downloaded_path,
            "message": self.message,
            "checked_at": self.checked_at,
        }
        if self.candidate:
            result["candidate"] = self.candidate.to_dict()
        if self.installation:
            result["installation"] = self.installation.to_dict()
        if self.error:
            result["error"] = self.error.to_dict()
        return result


def parse_version(value: str) -> ParsedVersion:
    """Parse a Mozikit stable or nightly version."""
    text = str(value).strip()
    match = _VERSION_RE.fullmatch(text)
    if not match:
        raise UpdateError("invalid_manifest", f"Unsupported Mozikit version: {value}")
    base = tuple(int(part) for part in match.group("base").split("."))
    date_text = match.group("date")
    return ParsedVersion(
        base=base,  # type: ignore[arg-type]
        nightly=date_text is not None,
        nightly_date=int(date_text) if date_text else None,
        nightly_ref=match.group("ref"),
    )


def _parse_timestamp(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).astimezone(timezone.utc).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalise_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    return urllib.parse.urlunparse(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", parsed.query, "")
    )


def _is_allowed_github_url(value: str, *, api: bool = False) -> bool:
    try:
        parsed = urllib.parse.urlparse(value)
    except ValueError:
        return False
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if api:
        return host == "api.github.com"
    return (
        host == "github.com"
        or host == "api.github.com"
        or host == "objects.githubusercontent.com"
        or host.endswith(".githubusercontent.com")
        or host.endswith(".github.com")
    )


class UpdateManager:
    """Discover and install Mozikit Desktop releases.

    ``opener`` and ``popen`` are injectable so all network and process
    boundaries can be tested without contacting GitHub or starting MSI.
    """

    def __init__(
        self,
        *,
        repository: Optional[str] = None,
        api_base: Optional[str] = None,
        opener: Optional[Callable[..., Any]] = None,
        popen: Optional[Callable[..., Any]] = None,
        data_dir: Optional[Path] = None,
        platform: Optional[str] = None,
        frozen: Optional[bool] = None,
        executable: Optional[Path] = None,
        timeout: float = 20.0,
    ):
        self.repository = repository or os.environ.get(
            "MOZIKIT_UPDATE_REPOSITORY", DEFAULT_REPOSITORY
        )
        if not _REPOSITORY_RE.fullmatch(self.repository):
            raise ValueError(f"Invalid update repository: {self.repository}")
        self.api_base = (api_base or os.environ.get("MOZIKIT_UPDATE_API_BASE", DEFAULT_API_BASE)).rstrip(
            "/"
        )
        self._opener = opener or urllib.request.urlopen
        self._popen = popen or subprocess.Popen
        self._data_dir = Path(data_dir) if data_dir else None
        self._platform = platform or sys.platform
        self._frozen = getattr(sys, "frozen", False) if frozen is None else frozen
        self._executable = Path(executable) if executable else None
        self.timeout = timeout

    @property
    def is_windows(self) -> bool:
        return self._platform == "win32" or self._platform.startswith("win")

    @property
    def current_version(self) -> str:
        from src.core import get_version

        return get_version()

    @property
    def default_channel(self) -> str:
        try:
            return "nightly" if parse_version(self.current_version).nightly else "stable"
        except UpdateError:
            return "stable"

    @property
    def update_dir(self) -> Path:
        root = self._data_dir or runtime_paths.get_app_data_dir()
        return root / "updates"

    @property
    def state_path(self) -> Path:
        return self.update_dir / "state.json"

    def get_installation(self) -> Installation:
        """Detect source, MSI, or Portable without touching installation files."""
        if not self._frozen:
            return Installation(
                kind="source",
                executable=None,
                install_dir=None,
                can_install=False,
                reason="源码环境不支持自更新，请使用发行版安装包。",
            )

        executable = self._current_executable()
        if executable is None:
            return Installation(
                kind="unknown",
                executable=None,
                install_dir=None,
                can_install=False,
                reason="无法确定当前 Desktop 可执行文件位置。",
            )

        install_dir = executable.parent
        msi_dir = self._read_msi_install_path()
        if msi_dir and self._same_or_child(executable, Path(msi_dir)):
            if self.is_windows:
                return Installation("msi", str(executable), str(install_dir), True)
            return Installation(
                "msi",
                str(executable),
                str(install_dir),
                False,
                "MSI 更新仅支持 Windows。",
            )

        return Installation(
            kind="portable",
            executable=str(executable),
            install_dir=str(install_dir),
            can_install=False,
            reason="Portable 发行版需要手动替换目录，更新器不会覆盖正在运行的文件。",
        )

    def check(
        self,
        *,
        channel: Optional[str] = None,
        current_version: Optional[str] = None,
    ) -> UpdateResult:
        selected_channel = self._validate_channel(channel or self.default_channel)
        current = current_version or self.current_version
        parse_version(current)
        installation = self.get_installation()
        candidates = self._fetch_candidates(selected_channel)
        latest = self._select_latest(candidates, selected_channel)
        current_candidate = next(
            (item for item in candidates if item.tag == f"v{current}"), None
        )

        if self._is_candidate_newer(latest, current, current_candidate, selected_channel):
            can_install = installation.can_install and latest.asset("msi") is not None
            message = (
                "发现可用更新。"
                if can_install
                else installation.reason or "当前安装方式需要手动升级。"
            )
            result = UpdateResult(
                status="update_available",
                channel=selected_channel,
                current_version=current,
                latest_version=latest.version,
                candidate=latest,
                installation=installation,
                can_install=can_install,
                message=message,
                checked_at=_utc_now(),
            )
        else:
            result = UpdateResult(
                status="up_to_date",
                channel=selected_channel,
                current_version=current,
                latest_version=latest.version,
                candidate=latest,
                installation=installation,
                can_install=False,
                message="当前已是所选频道的最新版本。",
                checked_at=_utc_now(),
            )
        self._save_state(result)
        return result

    def status(self) -> dict[str, Any]:
        """Return the last persisted updater state without network access."""
        state = self._load_state()
        if not state:
            result = UpdateResult(
                status="idle",
                channel=self.default_channel,
                current_version=self.current_version,
                installation=self.get_installation(),
                message="尚未执行更新检查。",
            ).to_dict()
        else:
            result = dict(state)
            result["current_version"] = self.current_version
            result["installation"] = self.get_installation().to_dict()
        result["state_path"] = str(self.state_path)
        return result

    def download_candidate(
        self,
        candidate: UpdateCandidate,
        *,
        kind: str = "msi",
        cancel: Optional[Callable[[], bool]] = None,
    ) -> Path:
        asset = candidate.asset(kind)
        if asset is None:
            raise UpdateError("unsupported", f"更新没有可用的 {kind} 资产。")
        destination_dir = self.update_dir / candidate.tag
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / asset.name
        if destination.exists():
            try:
                self._verify_file(destination, asset)
                return destination
            except UpdateError:
                destination.unlink(missing_ok=True)

        partial = destination.with_suffix(destination.suffix + ".part")
        partial.unlink(missing_ok=True)
        digest = hashlib.sha256()
        total = 0
        try:
            response = self._open_url(asset.url, api=False)
            try:
                with partial.open("wb") as stream:
                    while True:
                        if cancel and cancel():
                            raise UpdateError("cancelled", "更新下载已取消。")
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > asset.size:
                            raise UpdateError(
                                "verification",
                                f"下载文件超过 manifest 声明大小: {asset.name}",
                            )
                        digest.update(chunk)
                        stream.write(chunk)
            finally:
                response.close()
            if total != asset.size or digest.hexdigest().lower() != asset.sha256.lower():
                raise UpdateError(
                    "verification",
                    f"更新文件校验失败: {asset.name}",
                    details={"expected_sha256": asset.sha256, "actual_sha256": digest.hexdigest()},
                )
            os.replace(partial, destination)
            return destination
        except UpdateError:
            partial.unlink(missing_ok=True)
            raise
        except OSError as exc:
            partial.unlink(missing_ok=True)
            raise UpdateError("io", f"保存更新文件失败: {exc}") from exc

    def install_candidate(
        self,
        candidate: UpdateCandidate,
        downloaded_path: Optional[Path] = None,
        *,
        quiet: bool = False,
    ) -> UpdateResult:
        installation = self.get_installation()
        if installation.kind != "msi" or not installation.can_install:
            raise UpdateError(
                "unsupported",
                installation.reason or "当前安装方式不支持自动安装更新。",
            )
        asset = candidate.asset("msi")
        if asset is None:
            raise UpdateError("unsupported", "更新没有 MSI 资产。")
        installer = self._find_msiexec()
        if installer is None:
            raise UpdateError("unsupported", "当前 Windows 环境找不到 msiexec.exe。")
        path = downloaded_path or self.download_candidate(candidate, kind="msi")
        self._verify_file(path, asset)
        args = [installer, "/i", str(path), "/quiet" if quiet else "/passive", "/norestart"]
        creationflags = 0
        if self.is_windows:
            creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        try:
            process = self._popen(
                args,
                cwd=str(path.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                close_fds=True,
            )
        except OSError as exc:
            raise UpdateError("installation", f"启动 MSI 安装程序失败: {exc}") from exc

        result = UpdateResult(
            status="pending_install",
            channel=candidate.channel,
            current_version=self.current_version,
            latest_version=candidate.version,
            candidate=candidate,
            installation=installation,
            can_install=True,
            downloaded_path=str(path),
            message="安装程序已启动，请按安装程序提示完成更新。",
            checked_at=_utc_now(),
        )
        self._save_state(result, process_id=getattr(process, "pid", None))
        return result

    def download_update(
        self,
        result: UpdateResult,
        *,
        cancel: Optional[Callable[[], bool]] = None,
    ) -> UpdateResult:
        """Download and verify an available update without launching MSI."""
        if not result.candidate or not result.available:
            raise UpdateError("unsupported", "没有可下载的更新。")
        path = self.download_candidate(result.candidate, cancel=cancel)
        downloaded = UpdateResult(
            status="downloaded",
            channel=result.channel,
            current_version=result.current_version,
            latest_version=result.latest_version,
            candidate=result.candidate,
            installation=result.installation,
            can_install=result.can_install,
            downloaded_path=str(path),
            message="更新文件已下载并通过 SHA256 校验。",
            checked_at=result.checked_at,
        )
        self._save_state(downloaded)
        return downloaded

    def download_and_install(
        self,
        result: UpdateResult,
        *,
        quiet: bool = False,
        cancel: Optional[Callable[[], bool]] = None,
    ) -> UpdateResult:
        if not result.can_install:
            raise UpdateError("unsupported", "当前安装方式不支持自动安装更新。")
        downloaded = self.download_update(result, cancel=cancel)
        if not downloaded.candidate:
            raise UpdateError("unsupported", "没有可安装的更新。")
        return self.install_candidate(
            downloaded.candidate,
            Path(downloaded.downloaded_path) if downloaded.downloaded_path else None,
            quiet=quiet,
        )

    def _validate_channel(self, channel: str) -> str:
        value = str(channel).strip().lower()
        if value not in CHANNELS:
            raise UpdateError("unsupported", f"不支持的更新频道: {channel}")
        return value

    def _current_executable(self) -> Optional[Path]:
        if self._executable:
            return self._executable.resolve()
        if not self._frozen:
            return None
        try:
            return Path(sys.executable).resolve()
        except OSError:
            return None

    def _read_msi_install_path(self) -> Optional[str]:
        if not self.is_windows:
            return None
        try:
            import winreg
        except ImportError:
            return None
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, r"Software\Mozikit") as key:
                    value, _ = winreg.QueryValueEx(key, "InstallPath")
                    if value:
                        return str(value)
            except (FileNotFoundError, OSError):
                continue
        return None

    @staticmethod
    def _same_or_child(path: Path, root: Path) -> bool:
        try:
            path_key = os.path.normcase(os.path.abspath(str(path)))
            root_key = os.path.normcase(os.path.abspath(str(root)))
            return os.path.commonpath([path_key, root_key]) == root_key
        except (OSError, ValueError):
            return False

    def _find_msiexec(self) -> Optional[str]:
        if not self.is_windows:
            return None
        found = shutil.which("msiexec.exe") or shutil.which("msiexec")
        if found:
            return found
        windir = os.environ.get("WINDIR", r"C:\Windows")
        candidate = Path(windir) / "System32" / "msiexec.exe"
        return str(candidate) if candidate.is_file() else None

    def _fetch_candidates(self, channel: str) -> list[UpdateCandidate]:
        url = f"{self.api_base}/repos/{self.repository}/releases?per_page=100"
        releases = self._fetch_json(url, api=True)
        if not isinstance(releases, list):
            raise UpdateError("invalid_manifest", "GitHub Releases 响应不是数组。")

        candidates: list[UpdateCandidate] = []
        errors: list[UpdateError] = []
        ordered = sorted(
            (item for item in releases if isinstance(item, dict)),
            key=lambda item: _parse_timestamp(item.get("published_at")) or 0,
            reverse=True,
        )
        for release in ordered:
            if not self._release_matches(release, channel):
                continue
            try:
                manifest = self._fetch_release_manifest(release)
                candidates.append(self._candidate_from_release(release, manifest, channel))
            except UpdateError as exc:
                errors.append(exc)

        if not candidates:
            if errors:
                raise errors[0]
            raise UpdateError("network", f"没有找到可用的 {channel} 更新发布。")
        self._validate_nightly_sequences(candidates, channel)
        return candidates

    def _release_matches(self, release: Mapping[str, Any], channel: str) -> bool:
        if release.get("draft") is True:
            return False
        tag = str(release.get("tag_name") or "")
        if channel == "nightly":
            return bool(_NIGHTLY_TAG_RE.fullmatch(tag)) and bool(
                release.get("prerelease") is True or "-nightly." in tag
            )
        try:
            parsed = parse_version(tag.removeprefix("v"))
        except UpdateError:
            return False
        return not parsed.nightly and release.get("prerelease") is not True

    def _fetch_release_manifest(self, release: Mapping[str, Any]) -> Mapping[str, Any]:
        inline = release.get("manifest")
        if isinstance(inline, Mapping):
            return inline
        assets = release.get("assets")
        if not isinstance(assets, list):
            raise UpdateError("invalid_manifest", "Release 缺少资产列表。")
        manifest_asset = next(
            (item for item in assets if isinstance(item, dict) and item.get("name") == "update-manifest.json"),
            None,
        )
        if not manifest_asset:
            raise UpdateError("invalid_manifest", "Release 缺少 update-manifest.json。")
        inline_content = manifest_asset.get("content")
        if isinstance(inline_content, Mapping):
            return inline_content
        manifest_url = manifest_asset.get("browser_download_url") or manifest_asset.get("url")
        if not isinstance(manifest_url, str) or not _is_allowed_github_url(manifest_url):
            raise UpdateError("invalid_manifest", "update-manifest.json 下载地址不受信任。")
        data = self._fetch_json(manifest_url, api=False)
        if not isinstance(data, Mapping):
            raise UpdateError("invalid_manifest", "update-manifest.json 不是对象。")
        return data

    def _candidate_from_release(
        self,
        release: Mapping[str, Any],
        manifest: Mapping[str, Any],
        channel: str,
    ) -> UpdateCandidate:
        tag = str(release.get("tag_name") or "")
        version = str(manifest.get("version") or "")
        expected_version = tag.removeprefix("v")
        parsed = parse_version(version)
        if version != expected_version or (parsed.nightly != (channel == "nightly")):
            raise UpdateError("invalid_manifest", f"Manifest 版本与 release 不一致: {tag}")
        try:
            minimum_updater = int(manifest.get("minimum_updater", 1))
        except (TypeError, ValueError):
            raise UpdateError("invalid_manifest", f"Manifest minimum_updater 无效: {tag}") from None
        if manifest.get("schema") != 1 or minimum_updater > UPDATE_PROTOCOL_VERSION:
            raise UpdateError("unsupported", f"Manifest 需要更新版本的 updater: {tag}")
        if manifest.get("channel") != channel or manifest.get("tag") != tag:
            raise UpdateError("invalid_manifest", f"Manifest 频道或 tag 不一致: {tag}")
        manifest_platform = manifest.get("platform")
        if manifest_platform and manifest_platform != "windows-x64":
            raise UpdateError("unsupported", f"当前发行版不支持更新目标: {manifest_platform}")
        upgrade = manifest.get("upgrade")
        if not isinstance(upgrade, Mapping) or upgrade.get("method") != "msi":
            raise UpdateError("unsupported", f"Manifest 没有受支持的 MSI 更新边界: {tag}")
        if upgrade.get("preserves_user_data") is not True:
            raise UpdateError("invalid_manifest", f"Manifest 未声明保留用户数据: {tag}")

        source_ref = str(manifest.get("source_ref") or "")
        if not _SOURCE_REF_RE.fullmatch(source_ref):
            raise UpdateError("invalid_manifest", f"Manifest source_ref 无效: {tag}")
        raw_assets = manifest.get("assets")
        if not isinstance(raw_assets, list):
            raise UpdateError("invalid_manifest", f"Manifest 缺少 assets: {tag}")
        release_assets = {
            str(item.get("name")): item
            for item in release.get("assets", [])
            if isinstance(item, Mapping) and item.get("name")
        }
        assets: list[UpdateAsset] = []
        for raw in raw_assets:
            if not isinstance(raw, Mapping):
                raise UpdateError("invalid_manifest", f"Manifest asset 不是对象: {tag}")
            name = str(raw.get("name") or "")
            if not name or Path(name).name != name:
                raise UpdateError("invalid_manifest", f"Manifest asset 名称无效: {name}")
            release_asset = release_assets.get(name)
            if not release_asset:
                raise UpdateError("invalid_manifest", f"Manifest asset 未发布: {name}")
            kind = str(raw.get("kind") or "")
            if kind not in {"msi", "portable"}:
                raise UpdateError("invalid_manifest", f"Manifest asset 类型无效: {kind}")
            asset_url = str(raw.get("url") or release_asset.get("browser_download_url") or "")
            if not _is_allowed_github_url(asset_url):
                raise UpdateError("invalid_manifest", f"Manifest asset URL 不受信任: {name}")
            release_url = release_asset.get("browser_download_url")
            if isinstance(release_url, str) and _normalise_url(asset_url) != _normalise_url(release_url):
                raise UpdateError("invalid_manifest", f"Manifest asset URL 与 Release 不一致: {name}")
            digest = str(raw.get("sha256") or "")
            if not _SHA256_RE.fullmatch(digest):
                raise UpdateError("invalid_manifest", f"Manifest SHA256 无效: {name}")
            try:
                size = int(raw.get("size"))
            except (TypeError, ValueError):
                raise UpdateError("invalid_manifest", f"Manifest asset 大小无效: {name}") from None
            if size < 0:
                raise UpdateError("invalid_manifest", f"Manifest asset 大小无效: {name}")
            asset_platform = str(raw.get("platform")) if raw.get("platform") else None
            if asset_platform and asset_platform != "windows-x64":
                raise UpdateError("unsupported", f"当前发行版不支持更新目标: {asset_platform}")
            assets.append(
                UpdateAsset(
                    name=name,
                    kind=kind,
                    url=asset_url,
                    sha256=digest.lower(),
                    size=size,
                    platform=asset_platform,
                )
            )
        if not any(asset.kind == "msi" for asset in assets):
            raise UpdateError("invalid_manifest", f"Manifest 缺少 MSI asset: {tag}")

        sequence = manifest.get("build_sequence")
        if sequence is not None:
            try:
                sequence = int(sequence)
            except (TypeError, ValueError):
                raise UpdateError("invalid_manifest", f"Manifest build_sequence 无效: {tag}") from None
            if sequence < 0:
                raise UpdateError("invalid_manifest", f"Manifest build_sequence 无效: {tag}")
        published_at = str(manifest.get("published_at") or release.get("published_at") or "") or None
        return UpdateCandidate(
            channel=channel,
            tag=tag,
            version=version,
            source_ref=source_ref,
            assets=tuple(assets),
            build_sequence=sequence,
            published_at=published_at,
            release_id=int(release["id"]) if release.get("id") is not None else None,
        )

    @staticmethod
    def _validate_nightly_sequences(candidates: list[UpdateCandidate], channel: str) -> None:
        if channel != "nightly":
            return
        seen: dict[tuple[tuple[int, int, int], Optional[int]], UpdateCandidate] = {}
        for candidate in candidates:
            parsed = parse_version(candidate.version)
            key = (parsed.base, candidate.build_sequence)
            if candidate.build_sequence is None:
                continue
            previous = seen.get(key)
            if previous and previous.source_ref != candidate.source_ref:
                raise UpdateError(
                    "invalid_manifest",
                    "nightly build_sequence 对应多个 source_ref。",
                    details={"build_sequence": candidate.build_sequence},
                )
            seen[key] = candidate

    @staticmethod
    def _select_latest(candidates: list[UpdateCandidate], channel: str) -> UpdateCandidate:
        def key(candidate: UpdateCandidate) -> tuple[Any, ...]:
            parsed = parse_version(candidate.version)
            if channel == "stable":
                return parsed.base, _parse_timestamp(candidate.published_at) or 0, candidate.tag
            return (
                parsed.base,
                candidate.build_sequence is not None,
                candidate.build_sequence if candidate.build_sequence is not None else -1,
                _parse_timestamp(candidate.published_at) or 0,
                parsed.nightly_date or 0,
                candidate.tag,
            )

        return max(candidates, key=key)

    @staticmethod
    def _is_candidate_newer(
        candidate: UpdateCandidate,
        current_version: str,
        current_candidate: Optional[UpdateCandidate],
        channel: str,
    ) -> bool:
        current = parse_version(current_version)
        target = parse_version(candidate.version)
        if channel == "stable":
            if target.base > current.base:
                return True
            return current.nightly and target.base >= current.base

        # Explicitly selecting nightly is a channel switch from stable.  A
        # same-base nightly is useful even when the installed stable release
        # has the same base version.
        if not current.nightly:
            return target.base >= current.base
        if target.base != current.base:
            return target.base > current.base
        if current_candidate and current_candidate.tag == candidate.tag:
            return False
        if current_candidate:
            if candidate.build_sequence is not None and current_candidate.build_sequence is not None:
                return candidate.build_sequence > current_candidate.build_sequence
            candidate_time = _parse_timestamp(candidate.published_at)
            current_time = _parse_timestamp(current_candidate.published_at)
            if candidate_time is not None and current_time is not None:
                return candidate_time > current_time
        if target.nightly_date != current.nightly_date:
            return (target.nightly_date or 0) > (current.nightly_date or 0)
        # A local nightly built outside GitHub does not have a trustworthy
        # sequence.  A new manifest with a sequence is still actionable on
        # the same day; SHA strings themselves are never used for ordering.
        return candidate.tag != f"v{current_version}" and candidate.build_sequence is not None

    def _fetch_json(self, url: str, *, api: bool) -> Any:
        if not _is_allowed_github_url(url, api=api):
            raise UpdateError("network", f"拒绝访问非 GitHub 更新地址: {url}")
        try:
            response = self._open_url(url, api=api)
            try:
                body = response.read(1024 * 1024 + 1)
            finally:
                response.close()
            if len(body) > 1024 * 1024:
                raise UpdateError("invalid_manifest", "更新 manifest 超过大小限制。")
            return json.loads(body.decode("utf-8"))
        except UpdateError:
            raise
        except json.JSONDecodeError as exc:
            raise UpdateError("invalid_manifest", f"更新响应不是有效 JSON: {url}") from exc
        except OSError as exc:
            raise UpdateError("network", f"访问更新服务失败: {exc}") from exc

    def _open_url(self, url: str, *, api: bool) -> Any:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json" if api else "application/octet-stream",
                "User-Agent": "Mozikit-Updater/1",
            },
        )
        try:
            response = self._opener(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            remaining = exc.headers.get("X-RateLimit-Remaining") if exc.headers else None
            if exc.code == 429 or (exc.code == 403 and remaining == "0"):
                raise UpdateError("rate_limited", "GitHub 更新服务暂时限流，请稍后重试。") from exc
            raise UpdateError("network", f"更新服务返回 HTTP {exc.code}。") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise UpdateError("network", f"访问更新服务失败: {exc}") from exc
        status = response.getcode() if hasattr(response, "getcode") else 200
        if status and status >= 400:
            if status == 429:
                raise UpdateError("rate_limited", "GitHub 更新服务暂时限流，请稍后重试。")
            raise UpdateError("network", f"更新服务返回 HTTP {status}。")
        return response

    @staticmethod
    def _verify_file(path: Path, asset: UpdateAsset) -> None:
        if not path.is_file() or path.stat().st_size != asset.size:
            raise UpdateError("verification", f"更新文件大小校验失败: {path.name}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest().lower()
        if actual != asset.sha256.lower():
            raise UpdateError(
                "verification",
                f"更新文件 SHA256 校验失败: {path.name}",
                details={"expected_sha256": asset.sha256, "actual_sha256": actual},
            )

    def _save_state(self, result: UpdateResult, *, process_id: Optional[int] = None) -> None:
        payload = result.to_dict()
        if process_id is not None:
            payload["installer_pid"] = process_id
        try:
            self.update_dir.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            os.replace(temporary, self.state_path)
        except OSError:
            # A read-only profile must not make a network check fail.  The
            # result is still returned to the caller and can be displayed.
            return

    def _load_state(self) -> Optional[dict[str, Any]]:
        try:
            if not self.state_path.is_file():
                return None
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, json.JSONDecodeError):
            return None


__all__ = [
    "CHANNELS",
    "DEFAULT_REPOSITORY",
    "Installation",
    "UpdateAsset",
    "UpdateCandidate",
    "UpdateError",
    "UpdateManager",
    "UpdateResult",
    "parse_version",
]
