"""
节点版本管理器
管理节点的多版本存储、迁移和路径解析

存储结构:
    official_nodes/
    └── my_node/
        ├── versions/
        │   ├── 1.0.0/
        │   │   ├── node.json
        │   │   └── node.py
        │   └── 1.2.0/
        │       ├── node.json
        │       └── node.py
        ├── current -> versions/1.2.0   # 符号链接/指向文件
        └── .manifest                   # 本地版本清单

    custom_nodes/
    └── my_custom_node/
        ├── versions/
        │   ├── 1.0.0/
        │   │   ├── node.json
        │   │   └── node.py
        │   └── 2.0.0/
        │       ├── node.json
        │       └── node.py
        └── current -> versions/2.0.0
"""

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .log_manager import get_logger

logger = get_logger("node_version_manager")


@dataclass
class VersionInfo:
    """版本信息"""

    version: str
    installed_at: str = ""
    source: str = ""  # "official", "custom", "external"
    min_app_version: str = ""
    file_hashes: Dict[str, str] = field(default_factory=dict)
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "VersionInfo":
        return cls(
            version=data.get("version", ""),
            installed_at=data.get("installed_at", ""),
            source=data.get("source", ""),
            min_app_version=data.get("min_app_version", ""),
            file_hashes=data.get("file_hashes", {}),
            metadata=data.get("metadata", {}),
        )


@dataclass
class LocalManifest:
    """本地节点版本清单"""

    node_type: str = ""
    node_name: str = ""
    current_version: str = ""
    versions: List[VersionInfo] = field(default_factory=list)
    legacy_migrated: bool = False

    def to_dict(self) -> dict:
        return {
            "node_type": self.node_type,
            "node_name": self.node_name,
            "current_version": self.current_version,
            "versions": [v.to_dict() for v in self.versions],
            "legacy_migrated": self.legacy_migrated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LocalManifest":
        return cls(
            node_type=data.get("node_type", ""),
            node_name=data.get("node_name", ""),
            current_version=data.get("current_version", ""),
            versions=[VersionInfo.from_dict(v) for v in data.get("versions", [])],
            legacy_migrated=data.get("legacy_migrated", False),
        )

    def get_version(self, version: str) -> Optional[VersionInfo]:
        """获取指定版本信息"""
        for v in self.versions:
            if v.version == version:
                return v
        return None

    def has_version(self, version: str) -> bool:
        """检查是否有指定版本"""
        return any(v.version == version for v in self.versions)

    def add_or_update_version(self, version_info: VersionInfo):
        """添加或更新版本信息"""
        for i, v in enumerate(self.versions):
            if v.version == version_info.version:
                self.versions[i] = version_info
                return
        self.versions.append(version_info)

    def remove_version(self, version: str) -> bool:
        """移除版本信息"""
        for i, v in enumerate(self.versions):
            if v.version == version:
                self.versions.pop(i)
                return True
        return False


class NodeVersionManager:
    """节点版本管理器 - 处理多版本存储的核心逻辑"""

    MANIFEST_FILENAME = ".manifest"
    VERSIONS_DIR = "versions"
    CURRENT_LINK = "current"
    LEGACY_VERSION = "0.0.0-legacy"

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    # ── 路径解析 ──

    def get_node_dir(self, node_type: str) -> Path:
        """获取节点根目录"""
        return self.base_dir / node_type

    def get_versions_dir(self, node_type: str) -> Path:
        """获取版本目录"""
        return self.get_node_dir(node_type) / self.VERSIONS_DIR

    def get_version_dir(self, node_type: str, version: str) -> Path:
        """获取指定版本的目录"""
        return self.get_versions_dir(node_type) / version

    def get_manifest_path(self, node_type: str) -> Path:
        """获取清单文件路径"""
        return self.get_node_dir(node_type) / self.MANIFEST_FILENAME

    def get_current_link_path(self, node_type: str) -> Path:
        """获取 current 链接/文件路径"""
        return self.get_node_dir(node_type) / self.CURRENT_LINK

    def get_node_json_path(self, node_type: str, version: Optional[str] = None) -> Path:
        """获取 node.json 路径

        Args:
            node_type: 节点类型
            version: 版本号，None 则使用 current 指向的版本
        """
        if version is None:
            version = self.resolve_current_version(node_type)
        if not version:
            # 回退到旧结构
            return self.get_node_dir(node_type) / "node.json"
        return self.get_version_dir(node_type, version) / "node.json"

    def get_node_py_path(self, node_type: str, version: Optional[str] = None) -> Path:
        """获取 node.py 路径"""
        if version is None:
            version = self.resolve_current_version(node_type)
        if not version:
            return self.get_node_dir(node_type) / "node.py"
        return self.get_version_dir(node_type, version) / "node.py"

    # ── 版本解析 ──

    def resolve_current_version(self, node_type: str) -> Optional[str]:
        """解析 current 指向的版本号"""
        node_dir = self.get_node_dir(node_type)
        if not node_dir.exists():
            return None

        # 1. 检查 current 符号链接/文件
        current_link = node_dir / self.CURRENT_LINK
        if current_link.exists():
            if current_link.is_symlink():
                target = current_link.resolve()
                return target.name
            else:
                # 可能是包含版本号的文本文件
                try:
                    return current_link.read_text().strip()
                except Exception:
                    pass

        # 2. 检查 .manifest
        manifest = self.load_manifest(node_type)
        if manifest and manifest.current_version:
            return manifest.current_version

        # 3. 检查 versions/ 目录
        versions_dir = node_dir / self.VERSIONS_DIR
        if versions_dir.exists():
            versions = sorted([d.name for d in versions_dir.iterdir() if d.is_dir()])
            if versions:
                return versions[-1]  # 最新版本

        # 4. 旧结构：直接放在节点目录下
        if (node_dir / "node.json").exists():
            return None  # 表示旧结构，无版本

        return None

    def resolve_version_for_execution(
        self,
        node_type: str,
        requested_version: Optional[str] = None,
        default_policy: str = "latest",
    ) -> Tuple[Optional[str], Optional[Path]]:
        """解析执行时使用的版本

        Args:
            node_type: 节点类型
            requested_version: 工作流中指定的版本
            default_policy: 默认策略: "latest", "current", "prompt"

        Returns:
            (resolved_version, node_py_path) 或 (None, None) 如果无法解析
        """
        # 1. 如果指定了版本，优先使用
        if requested_version:
            version_dir = self.get_version_dir(node_type, requested_version)
            node_py = version_dir / "node.py"
            if node_py.exists():
                return requested_version, node_py
            # 版本不存在
            logger.warning("节点 %s 请求版本 %s 不存在", node_type, requested_version)
            # 继续尝试回退

        # 2. 尝试 current / latest
        current_version = self.resolve_current_version(node_type)
        if current_version:
            version_dir = self.get_version_dir(node_type, current_version)
            node_py = version_dir / "node.py"
            if node_py.exists():
                return current_version, node_py

        # 3. 回退到旧结构
        old_node_py = self.get_node_dir(node_type) / "node.py"
        if old_node_py.exists():
            return None, old_node_py  # None version 表示旧结构

        return None, None

    # ── 清单管理 ──

    def load_manifest(self, node_type: str) -> Optional[LocalManifest]:
        """加载本地清单"""
        manifest_path = self.get_manifest_path(node_type)
        if not manifest_path.exists():
            return None
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                return LocalManifest.from_dict(json.load(f))
        except Exception as e:
            logger.error("加载清单失败 %s: %s", node_type, e)
            return None

    def save_manifest(self, node_type: str, manifest: LocalManifest):
        """保存本地清单"""
        manifest_path = self.get_manifest_path(node_type)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest.to_dict(), f, ensure_ascii=False, indent=2)

    # ── 版本操作 ──

    def list_local_versions(self, node_type: str) -> List[str]:
        """列出本地已安装的所有版本"""
        versions_dir = self.get_versions_dir(node_type)
        if not versions_dir.exists():
            return []
        return sorted([d.name for d in versions_dir.iterdir() if d.is_dir()])

    def version_exists(self, node_type: str, version: str) -> bool:
        """检查版本是否已安装"""
        return self.get_version_dir(node_type, version).exists()

    def set_current_version(self, node_type: str, version: str) -> bool:
        """设置 current 指向的版本"""
        version_dir = self.get_version_dir(node_type, version)
        if not version_dir.exists():
            return False

        node_dir = self.get_node_dir(node_type)
        current_link = node_dir / self.CURRENT_LINK

        # 删除旧的（处理符号链接、junction 和普通文件/目录）
        if current_link.exists() or current_link.is_symlink():
            try:
                # 先尝试 unlink（适用于符号链接和 junction）
                current_link.unlink()
            except OSError:
                # 如果是普通目录，使用 rmtree
                if current_link.is_dir():
                    shutil.rmtree(current_link)
                else:
                    raise

        # 创建新的符号链接（Windows 需要管理员权限，回退到文本文件）
        try:
            if os.name == "nt":
                # Windows: 使用 junction 或文本文件
                import _winapi

                try:
                    _winapi.CreateJunction(str(version_dir), str(current_link))
                except Exception:
                    # CreateJunction 失败时可能已创建空目录，清理后回退文本文件
                    if current_link.is_dir():
                        current_link.rmdir()
                    current_link.write_text(version, encoding="utf-8")
            else:
                current_link.symlink_to(version_dir, target_is_directory=True)
        except Exception:
            # 回退到文本文件（清理可能的半成品目录）
            if current_link.exists() and current_link.is_dir():
                shutil.rmtree(current_link, ignore_errors=True)
            current_link.write_text(version, encoding="utf-8")

        # 更新清单
        manifest = self.load_manifest(node_type)
        if manifest:
            manifest.current_version = version
            self.save_manifest(node_type, manifest)

        return True

    def create_version_dir(self, node_type: str, version: str) -> Path:
        """创建版本目录"""
        version_dir = self.get_version_dir(node_type, version)
        version_dir.mkdir(parents=True, exist_ok=True)
        return version_dir

    def remove_version(self, node_type: str, version: str) -> bool:
        """移除指定版本"""
        version_dir = self.get_version_dir(node_type, version)
        if not version_dir.exists():
            return False

        # 检查是否为 current
        current = self.resolve_current_version(node_type)
        if current == version:
            logger.warning("无法删除当前默认版本 %s/%s", node_type, version)
            return False

        shutil.rmtree(version_dir)

        # 更新清单
        manifest = self.load_manifest(node_type)
        if manifest:
            manifest.remove_version(version)
            if manifest.current_version == version:
                manifest.current_version = ""
            self.save_manifest(node_type, manifest)

        return True

    # ── 旧结构迁移 ──

    def needs_migration(self, node_type: str) -> bool:
        """检查节点是否需要从旧结构迁移"""
        node_dir = self.get_node_dir(node_type)
        if not node_dir.exists():
            return False
        # 有 node.json 但没有 versions/ 目录
        has_legacy = (node_dir / "node.json").exists()
        has_versions = (node_dir / self.VERSIONS_DIR).exists()
        return has_legacy and not has_versions

    def migrate_legacy_node(self, node_type: str) -> bool:
        """将旧结构节点迁移到新版本结构"""
        node_dir = self.get_node_dir(node_type)
        if not node_dir.exists():
            return False

        legacy_json = node_dir / "node.json"
        legacy_py = node_dir / "node.py"

        if not legacy_json.exists():
            return False

        # 读取旧 node.json 获取版本号
        version = self.LEGACY_VERSION
        try:
            with open(legacy_json, "r", encoding="utf-8") as f:
                config = json.load(f)
                version = config.get("version", self.LEGACY_VERSION)
        except Exception:
            pass

        # 创建版本目录
        version_dir = self.create_version_dir(node_type, version)

        # 移动文件
        for src in [legacy_json, legacy_py]:
            if src.exists():
                dst = version_dir / src.name
                if dst.exists():
                    dst.unlink()
                shutil.move(str(src), str(dst))

        # 创建 manifest
        manifest = LocalManifest(
            node_type=node_type,
            current_version=version,
            versions=[
                VersionInfo(
                    version=version,
                    source="legacy",
                    metadata={"migrated_from_legacy": True},
                )
            ],
            legacy_migrated=True,
        )
        self.save_manifest(node_type, manifest)

        # 设置 current
        self.set_current_version(node_type, version)

        logger.info("节点 %s 已从旧结构迁移到版本 %s", node_type, version)
        return True

    def migrate_all_legacy_nodes(self) -> List[str]:
        """迁移所有旧结构节点"""
        migrated = []
        if not self.base_dir.exists():
            return migrated

        for node_dir in self.base_dir.iterdir():
            if node_dir.is_dir() and self.needs_migration(node_dir.name):
                if self.migrate_legacy_node(node_dir.name):
                    migrated.append(node_dir.name)

        return migrated

    def scan_all_nodes(self) -> Dict[str, List[str]]:
        """扫描所有节点及其版本"""
        result = {}
        if not self.base_dir.exists():
            return result

        for node_dir in self.base_dir.iterdir():
            if not node_dir.is_dir():
                continue
            versions = self.list_local_versions(node_dir.name)
            if versions:
                result[node_dir.name] = versions
            elif (node_dir / "node.json").exists():
                result[node_dir.name] = [self.LEGACY_VERSION]

        return result

    def get_version_metadata(self, node_type: str, version: str) -> Optional[dict]:
        """获取指定版本的 node.json 内容"""
        node_json = self.get_node_json_path(node_type, version)
        if not node_json.exists():
            return None
        try:
            with open(node_json, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def write_version_files(
        self,
        node_type: str,
        version: str,
        node_json_content: dict,
        node_py_content: str,
    ) -> bool:
        """写入版本文件"""
        version_dir = self.create_version_dir(node_type, version)

        try:
            node_json_path = version_dir / "node.json"
            with open(node_json_path, "w", encoding="utf-8") as f:
                json.dump(node_json_content, f, ensure_ascii=False, indent=2)

            node_py_path = version_dir / "node.py"
            with open(node_py_path, "w", encoding="utf-8") as f:
                f.write(node_py_content)

            return True
        except Exception as e:
            logger.error("写入版本文件失败 %s@%s: %s", node_type, version, e)
            return False
