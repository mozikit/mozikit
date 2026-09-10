"""
节点仓库管理器
管理官方节点仓库的远程版本发现、选择性安装和更新

架构设计：
- 打包时自带 official_nodes/ 快照（manifest.json + 各节点 node.json/node.py）
- 运行时优先从 user_data/official_nodes/ 加载（用户安装/更新的版本）
- 若用户目录不存在，则回退到 bundled 快照
- 支持从 GitHub 远程仓库拉取特定版本（需 GitHub token，OAuth 或 PAT）
- 支持多版本共存：每个节点可有多个版本，工作流绑定具体版本
"""

import base64
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .code_safety import (
    compute_content_hash,
    review_code_safety,
    safety_review_to_warning,
)
from .log_manager import get_logger
from .node_version_manager import LocalManifest, NodeVersionManager, VersionInfo

logger = get_logger("node_repo_manager")


def _gh_get(url: str, token: str = None, timeout: int = 10) -> Tuple[int, dict]:
    """使用 urllib 发送 GitHub API GET 请求"""
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return resp.status, body
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {}
        return e.code, body
    except Exception as e:
        return 0, {"error": str(e)}


def _parse_version_parts(version: str) -> List[int]:
    """将版本号解析为数值列表（"1.2.3" -> [1, 2, 3]）"""
    parts = []
    for p in str(version).split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return parts


def is_app_version_compatible(app_version: str, min_app_version: str) -> bool:
    """判断当前主程序版本是否满足清单声明的最低版本要求

    复用 _sort_versions 的数值解析思路；版本号缺失或解析失败时按不兼容处理。
    """
    if not min_app_version:
        return True
    if not app_version:
        return False
    try:
        return _parse_version_parts(app_version) >= _parse_version_parts(
            min_app_version
        )
    except Exception:
        return False


@dataclass
class RemoteNodeVersion:
    """远程节点版本信息"""

    version: str
    min_app_version: str = ""
    files: Dict[str, dict] = field(default_factory=dict)  # filename -> {hash, url}

    @classmethod
    def from_dict(cls, data: dict) -> "RemoteNodeVersion":
        return cls(
            version=data.get("version", ""),
            min_app_version=data.get("min_app_version", ""),
            files=data.get("files", {}),
        )


@dataclass
class RemoteNodeInfo:
    """远程节点信息（多版本）"""

    node_type: str
    versions: List[RemoteNodeVersion] = field(default_factory=list)

    @classmethod
    def from_dict(cls, node_type: str, data: dict) -> "RemoteNodeInfo":
        versions = [RemoteNodeVersion.from_dict(v) for v in data.get("versions", [])]
        # 兼容旧格式：单版本无 versions 数组
        if not versions and "version" in data:
            versions = [RemoteNodeVersion.from_dict(data)]
        return cls(node_type=node_type, versions=versions)

    def get_version(self, version: str) -> Optional[RemoteNodeVersion]:
        for v in self.versions:
            if v.version == version:
                return v
        return None

    def latest_version(self) -> Optional[str]:
        """获取最新版本号"""
        if not self.versions:
            return None
        return self._sort_versions([v.version for v in self.versions])[-1]

    @staticmethod
    def _sort_versions(versions: List[str]) -> List[str]:
        return sorted(versions, key=_parse_version_parts)


@dataclass
class RemoteManifest:
    """远程仓库清单（多版本格式）"""

    repo_name: str = ""
    repo_url: str = ""
    repo_version: str = "0.0.0"
    snapshot_commit: str = ""
    app_min_version: str = ""  # 快照级最低主程序版本要求（旧清单无此字段，视为兼容）
    nodes: Dict[str, RemoteNodeInfo] = field(default_factory=dict)
    legacy_format: bool = False  # 标记是否为旧格式

    @classmethod
    def from_dict(cls, data: dict) -> "RemoteManifest":
        nodes_data = data.get("nodes", {})
        nodes = {}
        legacy_format = False

        if isinstance(nodes_data, list):
            # 旧格式：nodes 是字符串列表
            legacy_format = True
            for node_type in nodes_data:
                nodes[node_type] = RemoteNodeInfo(node_type=node_type)
        elif isinstance(nodes_data, dict):
            # 新格式：nodes 是字典
            for node_type, node_data in nodes_data.items():
                nodes[node_type] = RemoteNodeInfo.from_dict(node_type, node_data)

        return cls(
            repo_name=data.get("repo_name", ""),
            repo_url=data.get("repo_url", ""),
            repo_version=data.get(
                "repo_version", data.get("snapshot_version", "0.0.0")
            ),
            snapshot_commit=data.get("snapshot_commit", ""),
            app_min_version=data.get("app_min_version", ""),
            nodes=nodes,
            legacy_format=legacy_format,
        )

    def to_dict(self) -> dict:
        if self.legacy_format:
            return {
                "repo_name": self.repo_name,
                "repo_url": self.repo_url,
                "snapshot_version": self.repo_version,
                "snapshot_commit": self.snapshot_commit,
                "app_min_version": self.app_min_version,
                "nodes": list(self.nodes.keys()),
            }
        return {
            "repo_name": self.repo_name,
            "repo_url": self.repo_url,
            "repo_version": self.repo_version,
            "snapshot_commit": self.snapshot_commit,
            "app_min_version": self.app_min_version,
            "nodes": {
                k: {
                    "versions": [
                        {
                            "version": v.version,
                            "min_app_version": v.min_app_version,
                            "files": v.files,
                        }
                        for v in n.versions
                    ]
                }
                for k, n in self.nodes.items()
            },
        }


@dataclass
class VersionUpdateInfo:
    """版本更新信息"""

    node_type: str
    local_versions: List[str] = field(default_factory=list)
    remote_versions: List[str] = field(default_factory=list)
    new_versions: List[str] = field(default_factory=list)  # 远程有但本地没有的
    all_versions: List[str] = field(default_factory=list)  # 合并后的所有可用版本


@dataclass
class UpdateCheckResult:
    """更新检查结果"""

    has_updates: bool = False
    repo_version: str = ""
    remote_repo_version: str = ""
    updates: List[VersionUpdateInfo] = field(default_factory=list)
    new_nodes: List[str] = field(default_factory=list)
    error: str = ""


class NodeRepoManager:
    """节点仓库管理器 - 支持多版本选择性安装"""

    OFFICIAL_REPO_URL = "https://github.com/mozikit/mozikit-official-nodes"
    GITHUB_API_BASE = "https://api.github.com"

    def __init__(self, user_data_dir: Path):
        self._user_data_dir = user_data_dir
        self._user_official_dir = user_data_dir / "official_nodes"
        self._bundled_dir = self._find_bundled_dir()
        self._github_token: Optional[str] = None
        self._version_mgr = NodeVersionManager(self._user_official_dir)

    @staticmethod
    def _find_bundled_dir() -> Path:
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).parent
            bundled = base / "official_nodes"
            if bundled.exists():
                return bundled
        for candidate in [
            Path("official_nodes"),
            Path(__file__).parent.parent.parent / "official_nodes",
        ]:
            if candidate.exists() and (candidate / "manifest.json").exists():
                return candidate.resolve()
        return Path("official_nodes")

    @property
    def bundled_dir(self) -> Path:
        return self._bundled_dir

    @property
    def active_dir(self) -> Path:
        # A user manifest alone (for example after an interrupted install) is
        # not an installed node set and must not hide the bundled snapshot.
        if self._version_mgr.scan_all_nodes():
            return self._user_official_dir
        return self._bundled_dir

    @property
    def version_manager(self) -> NodeVersionManager:
        return self._version_mgr

    def set_github_token(self, token: str):
        self._github_token = token if token else None

    def resolve_official_repo_url(self) -> str:
        """解析官方节点仓库地址（镜像源支持）

        优先级: MOZIKIT_OFFICIAL_NODES_URL 环境变量 > ConfigManager 配置 > 默认值。
        镜像只需是与官方仓库保持同步的 fork（manifest 内 repo_url 指向镜像自身）。
        """
        repo_url, _ = self._resolve_configured_official_repo_url()
        return repo_url

    def _resolve_configured_official_repo_url(self) -> Tuple[str, bool]:
        """Return the configured source and whether it was explicitly set."""
        env_url = os.environ.get("MOZIKIT_OFFICIAL_NODES_URL", "").strip()
        if env_url:
            return env_url, True
        try:
            from .config_manager import ConfigManager

            config_url = ConfigManager().get_official_repo_url().strip()
            if config_url:
                return config_url, True
        except Exception as e:
            logger.warning("读取官方源配置失败，使用默认地址: %s", e)
        return self.OFFICIAL_REPO_URL, False

    def _resolve_effective_repo_url(self) -> str:
        """解析实际使用的官方源地址

        用户侧配置（环境变量 > 配置文件 > 默认）优先；本地 manifest 的 repo_url
        是仓库侧的重定向能力（快照来自镜像时指向镜像自身），仅在用户未显式配置
        源（解析结果仍是默认地址）时作为回退生效，与用户配置职责区分。
        """
        repo_url, explicitly_configured = self._resolve_configured_official_repo_url()
        local_manifest = self.load_local_manifest()
        if local_manifest and not explicitly_configured:
            repo_url = local_manifest.get("repo_url", repo_url)
        return repo_url

    # ── 清单加载 ──

    def load_local_manifest(self) -> Optional[dict]:
        """加载本地 manifest.json（旧格式兼容）"""
        manifest_path = self.active_dir / "manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def _fetch_remote_manifest(self, owner_repo: str) -> Optional[RemoteManifest]:
        """获取远程清单"""
        try:
            status, data = _gh_get(
                f"{self.GITHUB_API_BASE}/repos/{owner_repo}/contents/manifest.json",
                token=self._github_token,
            )
            if status != 200:
                return None
            content = base64.b64decode(data["content"]).decode("utf-8")
            return RemoteManifest.from_dict(json.loads(content))
        except Exception as e:
            logger.error("获取远程清单失败: %s", e)
            return None

    # ── 更新检查 ──

    def check_for_updates(self) -> UpdateCheckResult:
        """检查可用更新 - 返回所有节点的新版本信息"""
        local_manifest = self.load_local_manifest()
        repo_url = self._resolve_effective_repo_url()

        owner_repo = self._parse_github_url(repo_url)
        if not owner_repo:
            return UpdateCheckResult(error=f"无法解析仓库 URL: {repo_url}")

        remote_manifest = self._fetch_remote_manifest(owner_repo)
        if not remote_manifest:
            return UpdateCheckResult(error="无法获取远程 manifest.json")

        result = UpdateCheckResult(
            repo_version=local_manifest.get(
                "repo_version", local_manifest.get("snapshot_version", "0.0.0")
            )
            if local_manifest
            else "0.0.0",
            remote_repo_version=remote_manifest.repo_version,
        )

        # 扫描本地节点
        local_nodes = self._version_mgr.scan_all_nodes()

        for node_type, remote_info in remote_manifest.nodes.items():
            local_versions = local_nodes.get(node_type, [])
            remote_versions = [v.version for v in remote_info.versions]
            new_versions = [v for v in remote_versions if v not in local_versions]

            if new_versions:
                result.has_updates = True
                result.updates.append(
                    VersionUpdateInfo(
                        node_type=node_type,
                        local_versions=local_versions,
                        remote_versions=remote_versions,
                        new_versions=new_versions,
                        all_versions=sorted(set(local_versions + remote_versions)),
                    )
                )

            if node_type not in local_nodes and remote_versions:
                result.new_nodes.append(node_type)

        return result

    # ── 版本安装 ──

    def install_node_version(
        self,
        node_type: str,
        version: str,
        progress_cb=None,
    ) -> Tuple[bool, str]:
        """安装指定节点的指定版本

        Args:
            node_type: 节点类型
            version: 版本号
            progress_cb: 进度回调 (current, total, message)

        Returns:
            (success, message)
        """
        # 获取远程清单
        repo_url = self._resolve_effective_repo_url()

        owner_repo = self._parse_github_url(repo_url)
        if not owner_repo:
            return False, f"无法解析仓库 URL: {repo_url}"

        remote_manifest = self._fetch_remote_manifest(owner_repo)
        if not remote_manifest:
            return False, "无法获取远程 manifest.json"

        remote_info = remote_manifest.nodes.get(node_type)
        if not remote_info:
            return False, f"远程仓库中未找到节点: {node_type}"

        remote_version = remote_info.get_version(version)
        if not remote_version:
            return False, f"远程仓库中未找到版本 {node_type}@{version}"

        # 下载文件
        if progress_cb:
            progress_cb(0, 2, f"开始下载 {node_type}@{version}")

        downloaded_files = {}
        for i, (filename, file_info) in enumerate(remote_version.files.items()):
            if progress_cb:
                progress_cb(i, len(remote_version.files), f"下载 {filename}")

            content = self._download_file(owner_repo, node_type, version, filename)
            if content is None:
                return False, f"下载失败: {node_type}@{version}/{filename}"
            downloaded_files[filename] = content

        # 写入本地
        node_json_content = downloaded_files.get("node.json", {})
        if isinstance(node_json_content, str):
            try:
                node_json_content = json.loads(node_json_content)
            except Exception:
                return False, "node.json 格式错误"

        node_py_content = downloaded_files.get("node.py", "")

        # 安全审查
        if node_py_content:
            safety_result = review_code_safety(node_py_content)
            if safety_result.has_risks:
                metadata = node_json_content.setdefault("metadata", {})
                metadata["safety_warning"] = safety_review_to_warning(safety_result)
                if safety_result.risk_level == "high":
                    logger.warning(
                        "官方节点 %s@%s 包含高风险代码: %s",
                        node_type,
                        version,
                        safety_result.high_risks,
                    )

            # 计算文件哈希
            file_hashes = node_json_content.get("metadata", {}).get("file_hashes", {})
            file_hashes["node.py"] = compute_content_hash(node_py_content)
            node_json_content.setdefault("metadata", {})["file_hashes"] = file_hashes

        # 写入版本目录
        success = self._version_mgr.write_version_files(
            node_type, version, node_json_content, node_py_content
        )
        if not success:
            return False, "写入本地文件失败"

        # 更新清单
        local_node_manifest = self._version_mgr.load_manifest(node_type)
        if not local_node_manifest:
            local_node_manifest = LocalManifest(
                node_type=node_type,
                node_name=node_json_content.get("name", node_type),
            )

        from datetime import datetime

        local_node_manifest.add_or_update_version(
            VersionInfo(
                version=version,
                installed_at=datetime.now().isoformat(),
                source="official",
                min_app_version=remote_version.min_app_version,
                file_hashes={
                    f: compute_content_hash(c) if isinstance(c, str) else ""
                    for f, c in downloaded_files.items()
                },
            )
        )

        # 如果是首次安装，设为 current
        if not local_node_manifest.current_version:
            local_node_manifest.current_version = version
            self._version_mgr.set_current_version(node_type, version)

        self._version_mgr.save_manifest(node_type, local_node_manifest)

        if progress_cb:
            progress_cb(2, 2, f"安装完成 {node_type}@{version}")

        return True, f"成功安装 {node_type}@{version}"

    def _download_file(
        self,
        owner_repo: str,
        node_type: str,
        version: str,
        filename: str,
    ) -> Optional[str]:
        """从 GitHub 下载单个文件"""
        try:
            # 新格式：versions/<node_type>/<version>/<filename>
            path = f"versions/{node_type}/{version}/{filename}"
            status, data = _gh_get(
                f"{self.GITHUB_API_BASE}/repos/{owner_repo}/contents/{path}",
                token=self._github_token,
            )

            # 回退到旧格式：<node_type>/<filename>
            if status == 404:
                path = f"{node_type}/{filename}"
                status, data = _gh_get(
                    f"{self.GITHUB_API_BASE}/repos/{owner_repo}/contents/{path}",
                    token=self._github_token,
                )

            if status != 200:
                logger.error("下载文件失败 %s/%s: HTTP %s", node_type, filename, status)
                return None

            return base64.b64decode(data["content"]).decode("utf-8")
        except Exception as e:
            logger.error("下载文件失败 %s/%s: %s", node_type, filename, e)
            return None

    # ── 旧方法兼容 ──

    def pull_updates(self, progress_cb=None) -> dict:
        """拉取更新 - 已废弃，保留兼容旧代码

        现在只返回更新检查结果，不自动安装。
        调用方应使用 check_for_updates() + install_node_version()
        """
        result = self.check_for_updates()
        if result.error:
            return {"success": False, "error": result.error}

        return {
            "success": True,
            "has_updates": result.has_updates,
            "updates": [
                {
                    "node_type": u.node_type,
                    "new_versions": u.new_versions,
                    "all_versions": u.all_versions,
                }
                for u in result.updates
            ],
            "new_nodes": result.new_nodes,
            "message": "请使用 install_node_version() 安装特定版本",
        }

    def list_remote_versions(self, node_type: str) -> List[str]:
        """列出远程可用的所有版本"""
        repo_url = self._resolve_effective_repo_url()
        owner_repo = self._parse_github_url(repo_url)
        if not owner_repo:
            return []

        remote_manifest = self._fetch_remote_manifest(owner_repo)
        if not remote_manifest:
            return []

        remote_info = remote_manifest.nodes.get(node_type)
        if not remote_info:
            return []

        return [v.version for v in remote_info.versions]

    def list_local_versions(self, node_type: str) -> List[str]:
        """列出本地已安装的版本"""
        return self._version_mgr.list_local_versions(node_type)

    def reset_to_bundled(self) -> bool:
        """重置为打包版本"""
        if self._user_official_dir.exists():
            shutil.rmtree(self._user_official_dir, ignore_errors=True)
        return True

    @staticmethod
    def _parse_github_url(url: str) -> Optional[str]:
        pattern = r"(?:https?://github\.com/|git@github\.com:)([^/]+)/([^/.]+)"
        match = re.search(pattern, url)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
        return None

    @staticmethod
    def _version_gt(v1: str, v2: str) -> bool:
        return _parse_version_parts(v1) > _parse_version_parts(v2)

    def list_private_repos(self) -> List[dict]:
        if not self._github_token:
            return []
        try:
            status, data = _gh_get(
                f"{self.GITHUB_API_BASE}/user/repos?type=private&per_page=100",
                token=self._github_token,
            )
            if status != 200:
                return []
            return [
                {
                    "full_name": r["full_name"],
                    "url": r["html_url"],
                    "description": r.get("description", ""),
                }
                for r in data
                if isinstance(r, dict) and r.get("private")
            ]
        except Exception:
            return []

    def verify_token(self, token: str) -> Tuple[bool, str]:
        try:
            status, data = _gh_get(
                f"{self.GITHUB_API_BASE}/user",
                token=token,
            )
            if status == 200:
                return True, data.get("login", "")
            return False, f"HTTP {status}"
        except Exception as e:
            return False, str(e)
