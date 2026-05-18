"""
GitHub 社区节点提供者
负责从 GitHub 仓库下载、安装和管理外部节点
支持多版本共存，与官方节点/自定义节点一致的版本结构
支持 GitHub OAuth token 访问 private 仓库
使用标准库 urllib 替代 requests，无外部依赖
"""

import base64
import json
import re
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

from src.core.log_manager import get_logger

from ..code_safety import (
    compute_content_hash,
    review_code_safety,
    safety_review_to_warning,
)
from ..node_registry import NodeDefinition, NodeSource, get_registry
from ..node_version_manager import LocalManifest, NodeVersionManager, VersionInfo

logger = get_logger("github_provider")


def _gh_get(url: str, token: str = None, timeout: int = 15) -> Tuple[int, dict]:
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


class GitHubNodeProvider:
    """GitHub 节点管理器 - 支持多版本"""

    GITHUB_API_BASE = "https://api.github.com"

    def __init__(self, user_data_dir: Path, github_token: str = None):
        self.user_data_dir = user_data_dir
        self.github_dir = user_data_dir / "external_nodes" / "github"
        self.github_dir.mkdir(parents=True, exist_ok=True)
        self._github_token = github_token
        self._version_mgr = NodeVersionManager(self.github_dir)

    def set_token(self, token: str):
        self._github_token = token if token else None

    @property
    def version_manager(self) -> NodeVersionManager:
        return self._version_mgr

    @staticmethod
    def parse_url(url: str) -> Optional[Tuple[str, str]]:
        parsed = GitHubNodeProvider.parse_url_info(url)
        if parsed:
            return parsed[0], parsed[1]
        return None

    @staticmethod
    def parse_url_info(url: str) -> Optional[Tuple[str, str, str]]:
        url = url.strip()
        if not url:
            return None
        pattern = r"(?:https?://github\.com/)?([^/]+)/([^/]+?)(?:\.git)?(?:/(.*))?$"
        match = re.search(pattern, url)
        if match:
            owner = match.group(1)
            repo = match.group(2)
            subpath = GitHubNodeProvider._normalize_github_subpath(match.group(3) or "")
            return owner, repo, subpath
        return None

    @staticmethod
    def _normalize_github_subpath(subpath: str) -> str:
        subpath = (subpath or "").strip().strip("/")
        if not subpath:
            return ""

        parts = [part for part in subpath.split("/") if part]
        if len(parts) >= 3 and parts[0] in {"tree", "blob"}:
            return "/".join(parts[2:])
        return "/".join(parts)

    @staticmethod
    def _decode_content(data: dict) -> Optional[str]:
        content = data.get("content")
        if not content:
            return None
        return base64.b64decode(content).decode("utf-8")

    def _get_repo_file_json(
        self, owner: str, repo: str, path: str
    ) -> Tuple[int, Optional[dict]]:
        status, data = _gh_get(
            f"{self.GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}",
            token=self._github_token,
        )
        if status != 200:
            return status, None
        content = self._decode_content(data)
        if not content:
            return status, None
        return status, json.loads(content)

    def fetch_node_info(self, url: str) -> Tuple[bool, Optional[dict]]:
        parsed = self.parse_url_info(url)
        if not parsed:
            return False, {"error": "无效的 GitHub URL"}
        owner, repo, subpath = parsed
        node_path = self._resolve_single_node_path(owner, repo, subpath)
        if not node_path:
            return False, {"error": f"仓库 {owner}/{repo} 中未找到可导入的 node.json"}
        try:
            status, info = self._get_repo_file_json(
                owner, repo, f"{node_path}/node.json"
            )
            if status == 404:
                return False, {"error": f"仓库 {owner}/{repo} 中未找到 node.json"}
            if status == 403:
                return False, {
                    "error": "访问被拒绝，可能需要 GitHub 认证（Private 仓库需要 OAuth）"
                }
            if status != 200:
                return False, {"error": f"GitHub API 错误: HTTP {status}"}
            info["repo_url"] = url
            info["_path"] = node_path
            return True, info
        except Exception as e:
            return False, {"error": f"获取节点信息失败: {str(e)}"}

    def download_node(
        self, url: str, version: Optional[str] = None
    ) -> Optional[NodeDefinition]:
        nodes = self.download_nodes(url, version=version)
        return nodes[0] if len(nodes) == 1 else None

    def download_nodes(
        self, url: str, version: Optional[str] = None
    ) -> List[NodeDefinition]:
        parsed = self.parse_url_info(url)
        if not parsed:
            return []

        owner, repo, subpath = parsed
        node_paths = self._resolve_node_paths(owner, repo, subpath)
        imported = []
        for node_path in node_paths:
            node_def = self._download_node_from_path(
                owner, repo, node_path, url, version=version
            )
            if node_def:
                imported.append(node_def)
        return imported

    def _resolve_single_node_path(
        self, owner: str, repo: str, subpath: str
    ) -> Optional[str]:
        node_paths = self._resolve_node_paths(owner, repo, subpath)
        if len(node_paths) == 1:
            return node_paths[0]
        return None

    def _resolve_node_paths(
        self, owner: str, repo: str, subpath: str = ""
    ) -> List[str]:
        cleaned_subpath = (subpath or "").strip().strip("/")
        candidate_paths: List[str] = []

        if cleaned_subpath:
            if cleaned_subpath.endswith("node.json"):
                candidate_paths.append(
                    str(Path(cleaned_subpath).parent).replace("\\", "/")
                )
            else:
                candidate_paths.append(cleaned_subpath)
        else:
            status, _ = _gh_get(
                f"{self.GITHUB_API_BASE}/repos/{owner}/{repo}/contents/node.json",
                token=self._github_token,
            )
            if status == 200:
                candidate_paths.append("")
            else:
                manifest_paths = self._get_manifest_node_paths(owner, repo)
                if manifest_paths:
                    candidate_paths.extend(manifest_paths)
                else:
                    success, nodes = self.list_repo_nodes(
                        f"https://github.com/{owner}/{repo}"
                    )
                    if success:
                        candidate_paths.extend(
                            node.get("_path", "") for node in nodes if node.get("_path")
                        )

        deduped = []
        for path in candidate_paths:
            normalized = path.strip("/").replace("\\", "/")
            if normalized not in deduped:
                deduped.append(normalized)
        return deduped

    def _get_manifest_node_paths(self, owner: str, repo: str) -> List[str]:
        try:
            status, manifest = self._get_repo_file_json(owner, repo, "manifest.json")
            if status != 200 or not isinstance(manifest, dict):
                return []
            nodes = manifest.get("nodes", [])
            return [str(node).strip().strip("/") for node in nodes if str(node).strip()]
        except Exception:
            return []

    def _download_node_from_path(
        self,
        owner: str,
        repo: str,
        node_path: str,
        repo_url: str,
        version: Optional[str] = None,
    ) -> Optional[NodeDefinition]:
        path_prefix = f"{node_path}/" if node_path else ""
        try:
            status, info = self._get_repo_file_json(
                owner, repo, f"{path_prefix}node.json"
            )
            if status != 200 or not info:
                return None

            node_type = info.get(
                "node_type", node_path or f"github_{owner}_{repo}".lower()
            )
            node_name = info.get("name", repo)

            # 版本处理
            if version is None:
                version = info.get("version", "1.0.0")

            # 使用版本管理器存储
            version_dir = self._version_mgr.create_version_dir(node_type, version)

            info["repo_url"] = repo_url
            info["_path"] = node_path
            info["version"] = version

            with open(version_dir / "node.json", "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=2)

            entry_filename = info.get("entry_file", "node.py")
            source_code = self._download_file(
                owner, repo, f"{path_prefix}{entry_filename}"
            )
            if not source_code:
                source_code = (
                    f"# 节点来源: {repo_url}\n"
                    "# 源代码下载失败，请手动编辑\n\n"
                    "def execute(self, input_data):\n"
                    "    return input_data\n"
                )

            # ── 安全审查：扫描下载的源代码 ──
            safety_result = review_code_safety(source_code)
            metadata = info.setdefault("metadata", {})
            if safety_result.has_risks:
                metadata["safety_warning"] = safety_review_to_warning(safety_result)
                if safety_result.risk_level == "high":
                    logger.warning(
                        "GitHub 节点 %s@%s 包含高风险代码: %s",
                        node_type,
                        version,
                        safety_result.high_risks,
                    )

            # ── 完整性校验：记录源代码 SHA-256 哈希 ──
            file_hashes = metadata.get("file_hashes", {})
            file_hashes[entry_filename] = compute_content_hash(source_code)
            metadata["file_hashes"] = file_hashes

            # 将更新后的 metadata 写回 node.json
            info["metadata"] = metadata
            with open(version_dir / "node.json", "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=2)

            entry_path = version_dir / Path(entry_filename).name
            with open(entry_path, "w", encoding="utf-8") as f:
                f.write(source_code)

            self._download_extra_files(owner, repo, info, version_dir, path_prefix)

            # 记录 registrations 模块文件的哈希
            registrations = info.get("registrations", {})
            for reg_entry in registrations.values():
                module_name = reg_entry.get("module", "")
                if module_name:
                    module_path = version_dir / module_name
                    if module_path.exists():
                        with open(module_path, "rb") as mf:
                            file_hashes[module_name] = compute_content_hash(
                                mf.read().decode("utf-8", errors="replace")
                            )
            if registrations:
                info["metadata"] = metadata
                with open(version_dir / "node.json", "w", encoding="utf-8") as f:
                    json.dump(info, f, ensure_ascii=False, indent=2)

            # 更新清单
            manifest = self._version_mgr.load_manifest(node_type)
            if not manifest:
                manifest = LocalManifest(
                    node_type=node_type,
                    node_name=node_name,
                )
            from datetime import datetime

            manifest.add_or_update_version(
                VersionInfo(
                    version=version,
                    installed_at=datetime.now().isoformat(),
                    source="github",
                )
            )
            if not manifest.current_version:
                manifest.current_version = version
                self._version_mgr.set_current_version(node_type, version)
            self._version_mgr.save_manifest(node_type, manifest)

            # 注册到注册表
            node_def = NodeDefinition(
                node_type=node_type,
                name=node_name,
                description=info.get("description", ""),
                source=NodeSource.GITHUB,
                category=info.get("category", "GitHub"),
                source_code=source_code,
                config_schema=info.get("config_schema", {}),
                repo_url=repo_url,
                metadata=info.get("metadata", {}),
                dependencies=info.get("dependencies", []),
                version=version,
                registrations=info.get("registrations", {}),
            )
            # 立即注册扩展点
            registrations = info.get("registrations", {})
            if registrations:
                from ..node_extension_registries import load_registrations_from_json
                load_registrations_from_json(
                    node_type, registrations, str(version_dir),
                )
            registry = get_registry()
            registry.register_external_node(node_def)
            return node_def
        except Exception as e:
            logger.error("下载节点失败: %s", e)
            return None

    def _download_file(self, owner: str, repo: str, path: str) -> Optional[str]:
        try:
            status, data = _gh_get(
                f"{self.GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}",
                token=self._github_token,
            )
            if status != 200:
                return None
            return base64.b64decode(data["content"]).decode("utf-8")
        except Exception:
            return None

    def _download_extra_files(
        self,
        owner: str,
        repo: str,
        info: dict,
        version_dir: Path,
        path_prefix: str = "",
    ):
        metadata = info.get("metadata", {})
        extra_files = []
        if metadata.get("node_kind") == "playwright_script":
            script_file = metadata.get("script_file", "script.py")
            extra_files.append(script_file)
        # 下载 registrations 中引用的模块文件
        registrations = info.get("registrations", {})
        for reg_entry in registrations.values():
            module_name = reg_entry.get("module", "")
            if module_name and module_name not in extra_files:
                extra_files.append(module_name)
        for filename in extra_files:
            content = self._download_file(owner, repo, f"{path_prefix}{filename}")
            if content:
                with open(
                    version_dir / Path(filename).name, "w", encoding="utf-8"
                ) as f:
                    f.write(content)

    def delete_node(self, node_type: str) -> bool:
        """删除节点（所有版本）"""
        registry = get_registry()
        node_def = registry.get_node(node_type)
        if not node_def or node_def.source != NodeSource.GITHUB:
            return False
        node_dir = self.github_dir / node_type
        if node_dir.exists():
            shutil.rmtree(node_dir)
            registry.unregister_node(node_type)
            return True
        return False

    def delete_node_version(self, node_type: str, version: str) -> bool:
        """删除特定版本"""
        return self._version_mgr.remove_version(node_type, version)

    def list_node_versions(self, node_type: str) -> List[str]:
        """列出节点的所有版本"""
        return self._version_mgr.list_local_versions(node_type)

    def _find_node_dir(self, node_type: str) -> Optional[Path]:
        """查找节点目录（兼容旧结构）"""
        # 新结构
        versions_dir = self.github_dir / node_type / "versions"
        if versions_dir.exists():
            return versions_dir
        # 旧结构
        for config_file in self.github_dir.rglob("node.json"):
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                if config.get("node_type") == node_type:
                    return config_file.parent
            except Exception:
                continue
        return None

    def list_repo_nodes(self, url: str) -> Tuple[bool, List[dict]]:
        parsed = self.parse_url_info(url)
        if not parsed:
            return False, []
        owner, repo, _subpath = parsed
        try:
            status, entries = _gh_get(
                f"{self.GITHUB_API_BASE}/repos/{owner}/{repo}/contents/",
                token=self._github_token,
            )
            if status != 200:
                return False, []
            nodes = []
            for entry in entries:
                if entry.get("type") == "dir":
                    node_json_url = f"{entry['path']}/node.json"
                    try:
                        nstatus, ndata = _gh_get(
                            f"{self.GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{node_json_url}",
                            token=self._github_token,
                            timeout=10,
                        )
                        if nstatus == 200:
                            content = base64.b64decode(ndata["content"]).decode("utf-8")
                            node_info = json.loads(content)
                            node_info["_path"] = entry["path"]
                            nodes.append(node_info)
                    except Exception:
                        continue
            return True, nodes
        except Exception:
            return False, []

    def migrate_legacy_nodes(self) -> List[str]:
        """迁移旧结构的外部节点到新版本结构"""
        migrated = []
        for config_file in self.github_dir.rglob("node.json"):
            node_dir = config_file.parent
            # 检查是否已经是新结构
            if node_dir.parent.name == "versions":
                continue
            node_type = None
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                node_type = config.get("node_type", node_dir.name)
            except Exception:
                continue
            if node_type and self._version_mgr.needs_migration(node_type):
                if self._version_mgr.migrate_legacy_node(node_type):
                    migrated.append(node_type)
        return migrated
